"""Mandatory write gate between safety processing and every ordinary sink."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SafetyResult,
    SensitiveLevel,
    canonical_sha256,
)
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.detector import SensitiveDetector
from memoryhub.core.safety.quarantine import (
    QuarantineReceipt,
    ReviewQuarantineStore,
)

if TYPE_CHECKING:
    from memoryhub.config import SafetyConfig
    from memoryhub.core.safety.user_rules import UserRuleService

_APPROVED_WRITE_TOKEN = object()


class SafetyGateError(RuntimeError):
    """Stable-code gate failure that never includes event content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SafeLogRecord:
    """Minimal ordinary-log projection; contains no event body or user ID."""

    audit_id: str
    action: SafetyAction
    highest_level: SensitiveLevel
    reason_codes: tuple[str, ...]
    rule_set_version: str
    policy_version: str
    output_hash: str
    audit_record_hash: str = ""


class ApprovedWrite:
    """Gate-issued capability binding an immutable safe event to an audit record."""

    __slots__ = (
        "_action",
        "_audit_id",
        "_audit_record_hash",
        "_audit_sequence",
        "_event",
        "_issuer_id",
        "_mac",
        "_output_hash",
    )
    _event: MemoryEvent | None
    _action: SafetyAction | None
    _audit_id: str
    _audit_record_hash: str
    _audit_sequence: int
    _output_hash: str
    _issuer_id: str
    _mac: str

    def __init__(
        self,
        *,
        _token: object | None = None,
        event: MemoryEvent | None = None,
        action: SafetyAction | None = None,
        audit_id: str = "",
        audit_record_hash: str = "",
        audit_sequence: int = 0,
        output_hash: str = "",
        issuer_id: str = "",
        mac: str = "",
    ):
        if _token is not _APPROVED_WRITE_TOKEN:
            raise SafetyGateError("gate.approved_write_forged")
        object.__setattr__(self, "_event", event)
        object.__setattr__(self, "_action", action)
        object.__setattr__(self, "_audit_id", audit_id)
        object.__setattr__(self, "_audit_record_hash", audit_record_hash)
        object.__setattr__(self, "_audit_sequence", audit_sequence)
        object.__setattr__(self, "_output_hash", output_hash)
        object.__setattr__(self, "_issuer_id", issuer_id)
        object.__setattr__(self, "_mac", mac)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("ApprovedWrite is immutable")

    def __repr__(self) -> str:
        return (
            "ApprovedWrite("
            f"audit_id={self.audit_id!r}, action={self.action.value!r}, "
            f"output_hash={self.output_hash!r})"
        )

    @property
    def safe_event(self) -> MemoryEvent:
        event = self._event
        if event is None:
            raise SafetyGateError("gate.approved_write_invalid")
        return event

    @property
    def action(self) -> SafetyAction:
        action = self._action
        if action not in (SafetyAction.ALLOW, SafetyAction.MASK):
            raise SafetyGateError("gate.approved_write_invalid")
        return action

    @property
    def audit_id(self) -> str:
        return self._audit_id

    @property
    def audit_record_hash(self) -> str:
        return self._audit_record_hash

    @property
    def audit_sequence(self) -> int:
        return self._audit_sequence

    @property
    def output_hash(self) -> str:
        return self._output_hash


ApprovedCallback = Callable[[ApprovedWrite], object]
LogCallback = Callable[[SafeLogRecord], object]
DetectorProvider = Callable[[MemoryEvent], SensitiveDetector]


@dataclass(frozen=True, slots=True)
class GuardedCallbacks:
    """Ordinary sinks.  Every content sink receives only ApprovedWrite."""

    sqlite: ApprovedCallback | None = None
    embedding: ApprovedCallback | None = None
    vector: ApprovedCallback | None = None
    evidence: ApprovedCallback | None = None
    log: LogCallback | None = None

    def approved_callbacks(self) -> tuple[ApprovedCallback, ...]:
        return tuple(
            callback
            for callback in (
                self.sqlite,
                self.embedding,
                self.vector,
                self.evidence,
            )
            if callback is not None
        )


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """Safe result of routing one event through the mandatory gate."""

    action: SafetyAction
    audit_id: str
    approved: ApprovedWrite | None = field(default=None, repr=False)
    review: QuarantineReceipt | None = None
    log_record: SafeLogRecord | None = None


class SafetyWriteGate:
    """Owns one detector and is the sole issuer of ordinary-write capabilities."""

    def __init__(
        self,
        detector: SensitiveDetector | None,
        audit_log: SafetyAuditLog,
        *,
        quarantine: ReviewQuarantineStore | None = None,
        detector_provider: DetectorProvider | None = None,
    ):
        if (detector is None) == (detector_provider is None):
            raise SafetyGateError("gate.invalid_detector")
        if detector is not None and not isinstance(detector, SensitiveDetector):
            raise SafetyGateError("gate.invalid_detector")
        if detector_provider is not None and not callable(detector_provider):
            raise SafetyGateError("gate.invalid_detector")
        if type(audit_log) is not SafetyAuditLog:
            raise SafetyGateError("gate.invalid_audit_log")
        if quarantine is not None and type(quarantine) is not ReviewQuarantineStore:
            raise SafetyGateError("gate.invalid_quarantine")
        self._detector = detector
        self._detector_provider = detector_provider
        self._audit_log = audit_log
        self._quarantine = quarantine
        self._capability_key = secrets.token_bytes(32)
        self._issuer_id = secrets.token_hex(16)

    @property
    def audit_log(self) -> SafetyAuditLog:
        """只读访问底层审计日志（供管理后台展示/验链）。"""
        return self._audit_log

    @property
    def quarantine(self) -> ReviewQuarantineStore | None:
        """只读访问底层 REVIEW 隔离区（供管理后台审查）。"""
        return self._quarantine

    @classmethod
    def from_config(
        cls,
        detector: SensitiveDetector,
        config: "SafetyConfig",
        *,
        audit_hmac_key: bytes,
        quarantine_key: bytes,
    ) -> "SafetyWriteGate":
        """以同一 SafetyConfig 装配强制审计与 REVIEW 隔离。"""
        if (
            isinstance(audit_hmac_key, bytes)
            and isinstance(quarantine_key, bytes)
            and hmac.compare_digest(audit_hmac_key, quarantine_key)
        ):
            raise SafetyGateError("gate.key_reuse")
        audit_log = SafetyAuditLog.from_config(
            config.audit,
            fingerprint_key=audit_hmac_key,
        )
        quarantine = ReviewQuarantineStore.from_config(
            config.quarantine,
            encryption_key=quarantine_key,
        )
        return cls(detector, audit_log, quarantine=quarantine)

    @classmethod
    def from_provider_config(
        cls,
        detector_provider: DetectorProvider,
        config: "SafetyConfig",
        *,
        audit_hmac_key: bytes,
        quarantine_key: bytes,
    ) -> "SafetyWriteGate":
        """装配按事件选择不可变检测快照的 Gate，供用户级规则使用。"""
        if not callable(detector_provider):
            raise SafetyGateError("gate.invalid_detector")
        if (
            isinstance(audit_hmac_key, bytes)
            and isinstance(quarantine_key, bytes)
            and hmac.compare_digest(audit_hmac_key, quarantine_key)
        ):
            raise SafetyGateError("gate.key_reuse")
        audit_log = SafetyAuditLog.from_config(
            config.audit,
            fingerprint_key=audit_hmac_key,
        )
        quarantine = ReviewQuarantineStore.from_config(
            config.quarantine,
            encryption_key=quarantine_key,
        )
        return cls(
            None,
            audit_log,
            quarantine=quarantine,
            detector_provider=detector_provider,
        )

    @classmethod
    def from_user_rule_config(
        cls,
        user_rule_service: "UserRuleService",
        config: "SafetyConfig",
        *,
        audit_hmac_key: bytes,
        quarantine_key: bytes,
    ) -> "SafetyWriteGate":
        """Compose user overlays while enforcing three-way safety-key separation."""
        from memoryhub.core.safety.user_rules import UserRuleError, UserRuleService

        if not isinstance(user_rule_service, UserRuleService):
            raise SafetyGateError("gate.invalid_detector")
        try:
            user_rule_service.assert_key_separation(
                audit_hmac_key,
                quarantine_key,
            )
            provider = user_rule_service.detector_provider(config)
        except UserRuleError as exc:
            code = (
                "gate.key_reuse"
                if exc.code == "user_rule.key_reuse"
                else ("gate.invalid_detector")
            )
            raise SafetyGateError(code) from None
        except Exception:
            raise SafetyGateError("gate.invalid_detector") from None
        return cls.from_provider_config(
            provider,
            config,
            audit_hmac_key=audit_hmac_key,
            quarantine_key=quarantine_key,
        )

    def _detector_for(self, event: MemoryEvent) -> SensitiveDetector:
        """为一条事件固定检测器；provider 异常和非法结果均失败关闭。"""
        detector = self._detector
        provider_failed = False
        if self._detector_provider is not None:
            try:
                detector = self._detector_provider(event)
            except Exception:
                provider_failed = True
                detector = None
        if provider_failed or not isinstance(detector, SensitiveDetector):
            raise SafetyGateError("gate.detector_unavailable")
        return detector

    @staticmethod
    def _canonical_capability_payload(
        *,
        issuer_id: str,
        audit_id: str,
        audit_record_hash: str,
        audit_sequence: int,
        action: SafetyAction,
        output_hash: str,
        event: MemoryEvent,
    ) -> bytes:
        payload = {
            "issuer_id": issuer_id,
            "audit_id": audit_id,
            "audit_record_hash": audit_record_hash,
            "audit_sequence": audit_sequence,
            "action": action.value,
            "output_hash": output_hash,
            "safe_event": event.model_dump(mode="json"),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def _mac_for(
        self,
        *,
        audit_id: str,
        audit_record_hash: str,
        audit_sequence: int,
        action: SafetyAction,
        output_hash: str,
        event: MemoryEvent,
    ) -> str:
        return hmac.new(
            self._capability_key,
            self._canonical_capability_payload(
                issuer_id=self._issuer_id,
                audit_id=audit_id,
                audit_record_hash=audit_record_hash,
                audit_sequence=audit_sequence,
                action=action,
                output_hash=output_hash,
                event=event,
            ),
            hashlib.sha256,
        ).hexdigest()

    def _issue_approved(
        self,
        result: SafetyResult,
        audit_id: str,
        audit_record_hash: str,
        audit_sequence: int,
    ) -> ApprovedWrite:
        event = result.sanitized_event
        if event is None or result.decision.action not in (
            SafetyAction.ALLOW,
            SafetyAction.MASK,
        ):
            raise SafetyGateError("gate.safe_event_missing")
        output_hash = canonical_sha256(event.model_dump(mode="json"))
        mac = self._mac_for(
            audit_id=audit_id,
            audit_record_hash=audit_record_hash,
            audit_sequence=audit_sequence,
            action=result.decision.action,
            output_hash=output_hash,
            event=event,
        )
        return ApprovedWrite(
            _token=_APPROVED_WRITE_TOKEN,
            event=event,
            action=result.decision.action,
            audit_id=audit_id,
            audit_record_hash=audit_record_hash,
            audit_sequence=audit_sequence,
            output_hash=output_hash,
            issuer_id=self._issuer_id,
            mac=mac,
        )

    def verify_approved(self, approved: ApprovedWrite) -> ApprovedWrite:
        """Verify a capability before any individually guarded callback."""

        if not isinstance(approved, ApprovedWrite):
            raise SafetyGateError("gate.approved_write_required")
        try:
            event = approved.safe_event
            action = approved.action
            output_hash = canonical_sha256(event.model_dump(mode="json"))
            expected = self._mac_for(
                audit_id=approved.audit_id,
                audit_record_hash=approved.audit_record_hash,
                audit_sequence=approved.audit_sequence,
                action=action,
                output_hash=output_hash,
                event=event,
            )
        except Exception:
            raise SafetyGateError("gate.approved_write_invalid") from None
        if approved._issuer_id != self._issuer_id:
            raise SafetyGateError("gate.approved_write_wrong_issuer")
        if output_hash != approved.output_hash or not hmac.compare_digest(
            approved._mac,
            expected,
        ):
            raise SafetyGateError("gate.approved_write_invalid")
        return approved

    def guarded_call(
        self,
        approved: ApprovedWrite,
        callback: ApprovedCallback,
    ) -> object:
        """Invoke one content sink only after capability verification."""

        verified = self.verify_approved(approved)
        if not callable(callback):
            raise SafetyGateError("gate.invalid_callback")
        try:
            return callback(verified)
        except SafetyGateError:
            raise
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).exception(
                "guarded_call downstream failure: %s", exc
            )
            raise SafetyGateError("gate.downstream_failed") from exc

    @staticmethod
    def _audit_identity(
        result: SafetyResult,
        audit_record: object,
    ) -> tuple[str, str, int]:
        try:
            audit_id = getattr(audit_record, "audit_id")
            record_hash = getattr(audit_record, "record_hash")
            sequence = getattr(audit_record, "sequence")
            valid = (
                isinstance(audit_id, str)
                and audit_id == result.audit.audit_id
                and isinstance(record_hash, str)
                and re_full_hash(record_hash)
                and type(sequence) is int
                and sequence > 0
            )
        except Exception:
            raise SafetyGateError("gate.audit_record_invalid") from None
        if not valid:
            raise SafetyGateError("gate.audit_record_invalid")
        return audit_id, record_hash, sequence

    def route(self, event: MemoryEvent) -> GateOutcome:
        """Process, revalidate, audit, then route exactly one event."""

        if not isinstance(event, MemoryEvent):
            raise SafetyGateError("gate.memory_event_required")
        detector = self._detector_for(event)
        try:
            result = detector.process(event)
        except Exception:
            raise SafetyGateError("gate.processing_failed") from None
        try:
            validated = detector.validate_result(event, result)
        except Exception:
            raise SafetyGateError("gate.validation_failed") from None
        try:
            audit_record = self._audit_log.append(event, validated, detector)
        except Exception:
            raise SafetyGateError("gate.audit_failed") from None
        audit_id, audit_record_hash, audit_sequence = self._audit_identity(
            validated,
            audit_record,
        )
        try:
            self._audit_log.assert_persisted(audit_record)
        except Exception:
            raise SafetyGateError("gate.audit_record_invalid") from None
        action = validated.decision.action

        approved: ApprovedWrite | None = None
        review: QuarantineReceipt | None = None
        if action in (SafetyAction.ALLOW, SafetyAction.MASK):
            approved = self._issue_approved(
                validated,
                audit_id,
                audit_record_hash,
                audit_sequence,
            )
        elif action is SafetyAction.REVIEW:
            if self._quarantine is None:
                raise SafetyGateError("gate.quarantine_unavailable")
            try:
                review = self._quarantine.put(
                    event,
                    validated,
                    detector,
                    audit_id=audit_id,
                )
                self._quarantine.assert_persisted(review)
            except Exception:
                raise SafetyGateError("gate.quarantine_failed") from None
        elif action is not SafetyAction.REJECT:
            raise SafetyGateError("gate.invalid_decision")

        output_hash = approved.output_hash if approved is not None else ""
        safe_log = SafeLogRecord(
            audit_id=audit_id,
            action=action,
            highest_level=validated.report.highest_level,
            reason_codes=validated.decision.reason_codes,
            rule_set_version=validated.report.rule_set_version,
            policy_version=validated.decision.policy_version,
            output_hash=output_hash,
            audit_record_hash=audit_record_hash,
        )
        return GateOutcome(
            action=action,
            audit_id=audit_id,
            approved=approved,
            review=review,
            log_record=safe_log,
        )

    def dispatch(
        self,
        event: MemoryEvent,
        callbacks: GuardedCallbacks | None = None,
    ) -> GateOutcome:
        """Route and invoke ordinary sinks only for ALLOW/MASK."""

        selected = callbacks or GuardedCallbacks()
        if not isinstance(selected, GuardedCallbacks):
            raise SafetyGateError("gate.invalid_callbacks")
        outcome = self.route(event)
        if outcome.approved is None:
            return outcome
        for callback in selected.approved_callbacks():
            self.guarded_call(outcome.approved, callback)
        if selected.log is not None:
            if not callable(selected.log):
                raise SafetyGateError("gate.invalid_callback")
            log_record = outcome.log_record
            if log_record is None:
                raise SafetyGateError("gate.safe_log_missing")
            try:
                selected.log(log_record)
            except Exception:
                raise SafetyGateError("gate.downstream_failed") from None
        return outcome


def re_full_hash(value: str) -> bool:
    """Small dependency-free lowercase SHA-256 validator."""

    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
