"""安全处置审计的最小化 JSONL 持久化与 HMAC 哈希链。"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import threading
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from memoryhub import __version__ as MEMORYHUB_VERSION
from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    SafetyAction,
    SafetyResult,
    SensitiveLevel,
    ToolCallResult,
    canonical_sha256,
)

if TYPE_CHECKING:
    from memoryhub.config import SafetyAuditConfig
    from memoryhub.core.safety.detector import SensitiveDetector


_ZERO_HASH = "0" * 64
_SEGMENT_RE = re.compile(r"^safety-audit-(\d{8})\.jsonl$")
_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SAFE_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_JSON_POINTER_RE = re.compile(r"(?:/(?:[^~/]|~[01])*)+")
_INPUT_DOMAIN = b"memoryhub.safety_audit.input_fingerprint.v1\x00"
_RECORD_DOMAIN = b"memoryhub.safety_audit.record.v1\x00"
_ANCHOR_DOMAIN = b"memoryhub.safety_audit.retention_anchor.v1\x00"
_HEAD_DOMAIN = b"memoryhub.safety_audit.head.v1\x00"
_EVENT_REF_DOMAIN = b"memoryhub.safety_audit.event_reference.v1\x00"
_PATH_SEGMENT_DOMAIN = b"memoryhub.safety_audit.path_segment.v1\x00"
_SCHEMA_PATH_SEGMENTS = frozenset(
    field_name
    for model_type in (MemoryEvent, ToolCallResult, EventQuality)
    for field_name in model_type.model_fields
)
_SCHEMA_LIST_PATH_SEGMENTS = frozenset({"issues", "redactions", "tool_calls"})

_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}


class SafetyAuditLogError(RuntimeError):
    """仅暴露稳定代码的审计持久化错误。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hmac_hex(key: bytes, domain: bytes, payload: bytes) -> str:
    return hmac.new(key, domain + payload, hashlib.sha256).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _strict_json_loads(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise SafetyAuditLogError("audit.invalid_json") from None
    if not isinstance(value, dict):
        raise SafetyAuditLogError("audit.invalid_json")
    return value


def _record_hash(key: bytes, payload: dict[str, Any]) -> str:
    unsigned = dict(payload)
    unsigned.pop("record_hash", None)
    return _hmac_hex(key, _RECORD_DOMAIN, _canonical_json_bytes(unsigned))


class SafetyAuditCategoryCount(BaseModel):
    """一个不携带命中原文的敏感类别计数。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    category: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    count: int = Field(ge=1)


class SafetyAuditLogRecord(BaseModel):
    """写入 JSONL 的最小安全处置审计投影。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = "1.0"
    chain_id: str = Field(pattern=r"^chain_[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    audit_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
    )
    event_id: str = Field(min_length=1, max_length=65_536)
    created_at: datetime
    policy_version: str = Field(min_length=1, max_length=128)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_set_version: str = Field(min_length=1, max_length=128)
    rule_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_version: str = Field(min_length=1, max_length=128)
    component_registry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: SafetyAction
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    exception_ids: tuple[str, ...] = Field(default_factory=tuple)
    highest_risk: SensitiveLevel
    category_counts: tuple[SafetyAuditCategoryCount, ...] = Field(default_factory=tuple)
    finding_count: int = Field(ge=0)
    field_paths: tuple[str, ...] = Field(default_factory=tuple)
    redaction_count: int = Field(ge=0)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint_key_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    processing_time_ms: float = Field(ge=0.0)
    previous_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("processing_time_ms", mode="before")
    @classmethod
    def validate_processing_time(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("processing_time_ms must be a finite number")
        converted = float(value)
        if not math.isfinite(converted):
            raise ValueError("processing_time_ms must be a finite number")
        return converted

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("reason_codes must be sorted and unique")
        if any(_SAFE_CODE_RE.fullmatch(item) is None for item in value):
            raise ValueError("reason_codes must contain stable codes")
        return value

    @field_validator("exception_ids")
    @classmethod
    def validate_exception_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("exception_ids must be sorted and unique")
        if any(_SAFE_CODE_RE.fullmatch(item) is None for item in value):
            raise ValueError("exception_ids must contain stable identifiers")
        return value

    @field_validator("field_paths")
    @classmethod
    def validate_field_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("field_paths must be sorted and unique")
        if any(
            len(path) > 4_096 or _JSON_POINTER_RE.fullmatch(path) is None
            for path in value
        ):
            raise ValueError("field_paths must be bounded JSON Pointers")
        return value

    @model_validator(mode="after")
    def validate_projection(self) -> "SafetyAuditLogRecord":
        categories = tuple(item.category for item in self.category_counts)
        if categories != tuple(sorted(set(categories))):
            raise ValueError("category_counts must be sorted and unique")
        if sum(item.count for item in self.category_counts) != self.finding_count:
            raise ValueError("category_counts must cover every finding")
        if len(self.field_paths) > self.finding_count:
            raise ValueError("field_paths cannot outnumber findings")
        if self.redaction_count > self.finding_count:
            raise ValueError("redaction_count cannot outnumber findings")
        if self.decision in (SafetyAction.ALLOW, SafetyAction.MASK):
            if self.output_hash is None:
                raise ValueError("ALLOW/MASK audit requires output_hash")
        elif self.output_hash is not None:
            raise ValueError("REVIEW/REJECT audit must not expose output_hash")
        if self.sequence == 1:
            if self.previous_record_hash != _ZERO_HASH:
                raise ValueError("genesis record must use the zero previous hash")
        elif self.previous_record_hash == _ZERO_HASH:
            raise ValueError("non-genesis record cannot use the zero previous hash")
        return self


class SafetyAuditVerification(BaseModel):
    """显式验链的无敏感摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    chain_id: str
    record_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    first_sequence: int | None = Field(default=None, ge=1)
    last_sequence: int | None = Field(default=None, ge=1)
    head_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    anchored: bool = False


class _RetentionAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = "1.0"
    chain_id: str = Field(pattern=r"^chain_[0-9a-f]{32}$")
    first_retained_segment: int = Field(ge=1)
    first_retained_sequence: int = Field(ge=2)
    previous_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    fingerprint_key_id: str
    anchor_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class _AuditHead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"] = "1.0"
    chain_id: str = Field(pattern=r"^chain_[0-9a-f]{32}$")
    last_sequence: int = Field(ge=0)
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    updated_at: datetime
    fingerprint_key_id: str
    head_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("updated_at")
    @classmethod
    def normalize_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_genesis(self) -> "_AuditHead":
        if (self.last_sequence == 0) != (self.record_hash == _ZERO_HASH):
            raise ValueError("genesis head must use sequence zero and zero hash")
        return self


class SafetyAuditLog:
    """追加写、可轮转并可显式验链的安全处置审计日志。"""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        fingerprint_key: bytes,
        fingerprint_key_id: str = "default",
        rotate_max_bytes: int = 16 * 1024 * 1024,
        retention_days: int | None = 180,
        max_record_bytes: int = 64 * 1024,
        lock_timeout_seconds: float = 5.0,
        verify_on_start: bool = True,
    ):
        if (
            not isinstance(fingerprint_key, bytes)
            or len(fingerprint_key) < 32
            or not isinstance(fingerprint_key_id, str)
            or _SAFE_KEY_ID_RE.fullmatch(fingerprint_key_id) is None
        ):
            raise SafetyAuditLogError("audit.invalid_key")
        if (
            isinstance(rotate_max_bytes, bool)
            or not isinstance(rotate_max_bytes, int)
            or rotate_max_bytes <= 0
            or isinstance(max_record_bytes, bool)
            or not isinstance(max_record_bytes, int)
            or max_record_bytes <= 0
            or isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(float(lock_timeout_seconds))
            or lock_timeout_seconds <= 0
            or retention_days is not None
            and (
                isinstance(retention_days, bool)
                or not isinstance(retention_days, int)
                or retention_days <= 0
            )
        ):
            raise SafetyAuditLogError("audit.invalid_config")

        try:
            self.directory = Path(directory).absolute()
        except (TypeError, ValueError, OSError):
            raise SafetyAuditLogError("audit.invalid_config") from None
        self.fingerprint_key = fingerprint_key
        self.fingerprint_key_id = fingerprint_key_id
        self.rotate_max_bytes = rotate_max_bytes
        self.retention_days = retention_days
        self.max_record_bytes = max_record_bytes
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self._lock_path = self.directory / ".safety-audit.lock"
        self._anchor_path = self.directory / ".safety-audit-anchor.json"
        self._head_path = self.directory / ".safety-audit-head.json"

        self._ensure_directory()
        self._initialize_head()
        if verify_on_start:
            self.verify()

    @classmethod
    def from_config(
        cls,
        config: "SafetyAuditConfig",
        *,
        fingerprint_key: bytes,
        verify_on_start: bool = True,
    ) -> "SafetyAuditLog":
        """用已解析配置和外部设备密钥构造审计日志。"""
        if not config.enabled:
            raise SafetyAuditLogError("audit.disabled")
        return cls(
            config.directory,
            fingerprint_key=fingerprint_key,
            fingerprint_key_id=config.key_id,
            rotate_max_bytes=config.rotate_max_bytes,
            retention_days=config.retention_days,
            max_record_bytes=config.max_record_bytes,
            lock_timeout_seconds=config.lock_timeout_seconds,
            verify_on_start=verify_on_start,
        )

    @property
    def anchor_path(self) -> Path:
        return self._anchor_path

    @property
    def head_path(self) -> Path:
        return self._head_path

    def append(
        self,
        event: MemoryEvent,
        result: SafetyResult,
        detector: "SensitiveDetector",
    ) -> SafetyAuditLogRecord:
        """验证原子结果后，追加一条二次最小化的审计记录。"""
        try:
            trusted = detector.validate_result(event, result)
        except Exception:
            raise SafetyAuditLogError("audit.result_invalid") from None

        try:
            projection = self._project(event, trusted, detector)
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.projection_failed") from None

        try:
            with self._exclusive_lock():
                records, segments, anchor, head = self._read_and_verify_locked()
                previous = (
                    records[-1][1].record_hash
                    if records
                    else (
                        anchor.previous_record_hash
                        if anchor is not None
                        else head.record_hash
                    )
                )
                sequence = (
                    records[-1][1].sequence + 1
                    if records
                    else (
                        anchor.first_retained_sequence
                        if anchor is not None
                        else head.last_sequence + 1
                    )
                )
                chain_id = (
                    records[-1][1].chain_id
                    if records
                    else (anchor.chain_id if anchor is not None else head.chain_id)
                )
                payload = {
                    **projection,
                    "chain_id": chain_id,
                    "sequence": sequence,
                    "previous_record_hash": previous,
                }
                draft = SafetyAuditLogRecord.model_validate(
                    {**payload, "record_hash": _ZERO_HASH}
                )
                payload = draft.model_dump(mode="json", exclude={"record_hash"})
                payload["record_hash"] = _record_hash(self.fingerprint_key, payload)
                record = SafetyAuditLogRecord.model_validate(payload)
                line = _canonical_json_bytes(record.model_dump(mode="json")) + b"\n"
                if len(line) > self.max_record_bytes:
                    raise SafetyAuditLogError("audit.record_too_large")

                current_index = segments[-1][0] if segments else 1
                current_path = self._segment_path(current_index)
                current_info = (
                    self._secure_stat(current_path) if current_path.exists() else None
                )
                current_size = current_info.st_size if current_info is not None else 0
                retention_rotation = (
                    current_info is not None
                    and self.retention_days is not None
                    and datetime.fromtimestamp(
                        current_info.st_mtime,
                        tz=timezone.utc,
                    )
                    < _utc_now() - timedelta(days=self.retention_days)
                )
                rotated = current_size > 0 and (
                    current_size + len(line) > self.rotate_max_bytes
                    or retention_rotation
                )
                if rotated:
                    current_index += 1
                    current_path = self._segment_path(current_index)
                    if os.path.lexists(current_path):
                        raise SafetyAuditLogError("audit.segment_conflict")
                self._append_line(current_path, line)
                self._write_head(record)
                if rotated:
                    self._enforce_retention_locked(current_index)
                return record
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.append_failed") from None

    def verify(self) -> SafetyAuditVerification:
        """严格解析全部保留段并验证 HMAC 链。"""
        try:
            with self._exclusive_lock():
                records, segments, anchor, head = self._read_and_verify_locked()
                if records:
                    first = records[0][1]
                    last = records[-1][1]
                    chain_id = last.chain_id
                    first_sequence = first.sequence
                    last_sequence = last.sequence
                    head_hash = last.record_hash
                else:
                    chain_id = head.chain_id
                    first_sequence = None
                    last_sequence = None
                    head_hash = (
                        anchor.previous_record_hash
                        if anchor is not None
                        else head.record_hash
                    )
                return SafetyAuditVerification(
                    chain_id=chain_id,
                    record_count=len(records),
                    segment_count=len(segments),
                    first_sequence=first_sequence,
                    last_sequence=last_sequence,
                    head_hash=head_hash,
                    anchored=anchor is not None,
                )
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.verify_failed") from None

    def list_records(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[SafetyAuditLogRecord], int]:
        """返回已验链的审计记录分页（新的在前）；供管理后台只读展示。"""
        if type(limit) is not int or limit <= 0 or type(offset) is not int or offset < 0:
            raise SafetyAuditLogError("audit.invalid_query")
        try:
            with self._exclusive_lock():
                records, _, _, _ = self._read_and_verify_locked()
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.list_failed") from None
        ordered = [record for _, record in records]  # 升序（按 sequence）
        total = len(ordered)
        page = list(reversed(ordered))[offset : offset + limit]
        return page, total

    def assert_persisted(
        self,
        record: SafetyAuditLogRecord,
    ) -> SafetyAuditLogRecord:
        """确认 Gate 收到的完整记录与已 fsync 的链中记录逐字段一致。"""
        if type(record) is not SafetyAuditLogRecord:
            raise SafetyAuditLogError("audit.record_not_persisted")
        try:
            expected = _canonical_json_bytes(record.model_dump(mode="json"))
            with self._exclusive_lock():
                records, _, _, _ = self._read_and_verify_locked()
                for _, persisted in records:
                    if persisted.sequence != record.sequence:
                        continue
                    actual = _canonical_json_bytes(persisted.model_dump(mode="json"))
                    if hmac.compare_digest(actual, expected):
                        return record
                    break
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.record_not_persisted") from None
        raise SafetyAuditLogError("audit.record_not_persisted")

    def enforce_retention(self) -> int:
        """删除超过保留期的连续已关闭段，并先写入认证 anchor。"""
        try:
            with self._exclusive_lock():
                _, segments, _, _ = self._read_and_verify_locked()
                current_index = segments[-1][0] if segments else 1
                return self._enforce_retention_locked(current_index)
        except SafetyAuditLogError:
            raise
        except Exception:
            raise SafetyAuditLogError("audit.retention_failed") from None

    def _project(
        self,
        event: MemoryEvent,
        result: SafetyResult,
        detector: "SensitiveDetector",
    ) -> dict[str, Any]:
        if (
            result.report.rule_set_digest != detector.rule_set_digest
            or result.report.rule_set_version != detector.rule_set_version
        ):
            raise SafetyAuditLogError("audit.snapshot_mismatch")

        category_by_rule = detector.effective_rule_categories
        component_digest = detector.effective_component_registry_digest

        category_counter: Counter[str] = Counter()
        for finding in result.audit.findings:
            matched_category = category_by_rule.get(
                (finding.rule_name, finding.rule_version)
            )
            if matched_category is None:
                raise SafetyAuditLogError("audit.category_snapshot_mismatch")
            category = matched_category
            category_counter[category] += 1

        output_hash: str | None = None
        if result.sanitized_event is not None:
            output_hash = canonical_sha256(
                result.sanitized_event.model_dump(mode="json")
            )

        processing_time = getattr(result.audit, "processing_time_ms", 0.0)
        if (
            isinstance(processing_time, bool)
            or not isinstance(processing_time, (int, float))
            or not math.isfinite(float(processing_time))
            or processing_time < 0
        ):
            raise SafetyAuditLogError("audit.invalid_processing_time")

        input_fingerprint = _hmac_hex(
            self.fingerprint_key,
            _INPUT_DOMAIN,
            bytes.fromhex(result.report.event_digest),
        )
        redaction_count = sum(
            finding.action is SafetyAction.MASK
            for finding in result.decision.finding_decisions
        )
        return {
            "schema_version": "1.0",
            "audit_id": result.audit.audit_id,
            "event_id": self._safe_event_reference(event.event_id),
            "created_at": result.audit.created_at,
            "policy_version": result.decision.policy_version,
            "policy_digest": result.decision.policy_digest,
            "rule_set_version": result.report.rule_set_version,
            "rule_set_digest": result.report.rule_set_digest,
            "component_version": MEMORYHUB_VERSION,
            "component_registry_digest": component_digest,
            "decision": result.decision.action,
            "reason_codes": tuple(sorted(set(result.decision.reason_codes))),
            "exception_ids": tuple(sorted(set(result.decision.exception_ids))),
            "highest_risk": result.report.highest_level,
            "category_counts": tuple(
                SafetyAuditCategoryCount(category=category, count=count)
                for category, count in sorted(category_counter.items())
            ),
            "finding_count": len(result.audit.findings),
            "field_paths": tuple(
                sorted(
                    {
                        self._safe_field_path(finding.field_path, detector)
                        for finding in result.audit.findings
                    }
                )
            ),
            "redaction_count": redaction_count,
            "input_fingerprint": input_fingerprint,
            "fingerprint_key_id": self.fingerprint_key_id,
            "output_hash": output_hash,
            "processing_time_ms": float(processing_time),
        }

    def _safe_event_reference(
        self,
        value: str,
    ) -> str:
        digest = _hmac_hex(
            self.fingerprint_key,
            _EVENT_REF_DOMAIN,
            value.encode("utf-8", errors="surrogatepass"),
        )
        return f"event_{digest[:24]}"

    def _safe_field_path(
        self,
        value: str,
        detector: "SensitiveDetector",
    ) -> str:
        if _JSON_POINTER_RE.fullmatch(value) is None:
            raise SafetyAuditLogError("audit.invalid_field_path")
        projected: list[str] = []
        previous_segment: str | None = None
        for encoded_segment in value[1:].split("/"):
            segment = encoded_segment.replace("~1", "/").replace("~0", "~")
            schema_controlled = segment in _SCHEMA_PATH_SEGMENTS or (
                segment.isdecimal() and previous_segment in _SCHEMA_LIST_PATH_SEGMENTS
            )
            if (
                len(segment) <= 256
                and schema_controlled
                and not self._text_is_sensitive(
                    segment,
                    detector,
                    "/audit/path_segment",
                )
            ):
                replacement = segment
            else:
                digest = _hmac_hex(
                    self.fingerprint_key,
                    _PATH_SEGMENT_DOMAIN,
                    segment.encode("utf-8", errors="surrogatepass"),
                )
                replacement = f"seg_{digest[:24]}"
            projected.append(replacement.replace("~", "~0").replace("/", "~1"))
            previous_segment = segment
        return "/" + "/".join(projected)

    @staticmethod
    def _text_is_sensitive(
        value: str,
        detector: "SensitiveDetector",
        field_path: str,
    ) -> bool:
        try:
            return bool(detector.scan_text(value, field_path=field_path))
        except Exception:
            return True

    def _read_and_verify_locked(
        self,
    ) -> tuple[
        list[tuple[int, SafetyAuditLogRecord]],
        list[tuple[int, Path]],
        _RetentionAnchor | None,
        _AuditHead,
    ]:
        head = self._read_head()
        anchor = self._read_anchor()
        all_segments = self._segments()
        if anchor is not None:
            if anchor.chain_id != head.chain_id:
                raise SafetyAuditLogError("audit.anchor_mismatch")
            segments = [
                item
                for item in all_segments
                if item[0] >= anchor.first_retained_segment
            ]
        else:
            segments = all_segments
        records: list[tuple[int, SafetyAuditLogRecord]] = []
        expected_hash = (
            anchor.previous_record_hash if anchor is not None else _ZERO_HASH
        )
        expected_sequence = anchor.first_retained_sequence if anchor is not None else 1
        expected_chain = head.chain_id

        if anchor is not None and (
            not segments or segments[0][0] != anchor.first_retained_segment
        ):
            raise SafetyAuditLogError("audit.anchor_mismatch")

        for segment_index, path in segments:
            with self._open_read(path) as stream:
                saw_line = False
                for raw_line in stream:
                    saw_line = True
                    if not raw_line.endswith(b"\n"):
                        raise SafetyAuditLogError("audit.incomplete_record")
                    if len(raw_line) > self.max_record_bytes:
                        raise SafetyAuditLogError("audit.record_too_large")
                    encoded = raw_line[:-1]
                    if not encoded:
                        raise SafetyAuditLogError("audit.invalid_json")
                    payload = _strict_json_loads(encoded)
                    try:
                        record = SafetyAuditLogRecord.model_validate(payload)
                    except Exception:
                        raise SafetyAuditLogError("audit.record_invalid") from None
                    canonical = _canonical_json_bytes(record.model_dump(mode="json"))
                    if not hmac.compare_digest(encoded, canonical):
                        raise SafetyAuditLogError("audit.noncanonical_json")
                    expected_record_hash = _record_hash(
                        self.fingerprint_key,
                        record.model_dump(mode="json"),
                    )
                    if not hmac.compare_digest(
                        record.record_hash, expected_record_hash
                    ):
                        raise SafetyAuditLogError("audit.record_hash_mismatch")
                    if record.sequence != expected_sequence:
                        raise SafetyAuditLogError("audit.sequence_mismatch")
                    if not hmac.compare_digest(
                        record.previous_record_hash,
                        expected_hash,
                    ):
                        raise SafetyAuditLogError("audit.previous_hash_mismatch")
                    if expected_chain is None:
                        expected_chain = record.chain_id
                    elif record.chain_id != expected_chain:
                        raise SafetyAuditLogError("audit.chain_id_mismatch")
                    records.append((segment_index, record))
                    expected_sequence += 1
                    expected_hash = record.record_hash
                if not saw_line:
                    raise SafetyAuditLogError("audit.empty_segment")
        if not records:
            if anchor is not None:
                raise SafetyAuditLogError("audit.anchor_mismatch")
            if head.last_sequence != 0 or head.record_hash != _ZERO_HASH:
                raise SafetyAuditLogError("audit.tail_truncated")
            return records, segments, anchor, head

        last = records[-1][1]
        if head.last_sequence > last.sequence:
            raise SafetyAuditLogError("audit.tail_truncated")
        if head.last_sequence == last.sequence:
            if not hmac.compare_digest(head.record_hash, last.record_hash):
                raise SafetyAuditLogError("audit.head_mismatch")
            return records, segments, anchor, head

        if head.last_sequence == 0:
            checkpoint_matches = head.record_hash == _ZERO_HASH
        else:
            checkpoint = next(
                (
                    record
                    for _, record in records
                    if record.sequence == head.last_sequence
                ),
                None,
            )
            checkpoint_matches = checkpoint is not None and hmac.compare_digest(
                checkpoint.record_hash,
                head.record_hash,
            )
            if (
                not checkpoint_matches
                and anchor is not None
                and head.last_sequence == anchor.first_retained_sequence - 1
            ):
                checkpoint_matches = hmac.compare_digest(
                    head.record_hash,
                    anchor.previous_record_hash,
                )
        if not checkpoint_matches:
            raise SafetyAuditLogError("audit.head_mismatch")
        head = self._write_head(last)
        return records, segments, anchor, head

    def _initialize_head(self) -> None:
        with self._exclusive_lock():
            if os.path.lexists(self._head_path):
                self._read_head()
                return
            if self._segments() or os.path.lexists(self._anchor_path):
                raise SafetyAuditLogError("audit.head_missing")
            self._write_head_values(
                chain_id=f"chain_{secrets.token_hex(16)}",
                last_sequence=0,
                record_hash=_ZERO_HASH,
            )

    def _read_head(self) -> _AuditHead:
        if not os.path.lexists(self._head_path):
            raise SafetyAuditLogError("audit.head_missing")
        raw = self._read_small_file(self._head_path, 64 * 1024)
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise SafetyAuditLogError("audit.head_invalid")
        payload = _strict_json_loads(raw[:-1])
        try:
            head = _AuditHead.model_validate(payload)
        except Exception:
            raise SafetyAuditLogError("audit.head_invalid") from None
        unsigned = head.model_dump(mode="json", exclude={"head_hash"})
        expected = _hmac_hex(
            self.fingerprint_key,
            _HEAD_DOMAIN,
            _canonical_json_bytes(unsigned),
        )
        if (
            head.fingerprint_key_id != self.fingerprint_key_id
            or not hmac.compare_digest(head.head_hash, expected)
            or raw[:-1] != _canonical_json_bytes(head.model_dump(mode="json"))
        ):
            raise SafetyAuditLogError("audit.head_invalid")
        return head

    def _write_head(self, record: SafetyAuditLogRecord) -> _AuditHead:
        return self._write_head_values(
            chain_id=record.chain_id,
            last_sequence=record.sequence,
            record_hash=record.record_hash,
        )

    def _write_head_values(
        self,
        *,
        chain_id: str,
        last_sequence: int,
        record_hash: str,
    ) -> _AuditHead:
        draft = _AuditHead(
            chain_id=chain_id,
            last_sequence=last_sequence,
            record_hash=record_hash,
            updated_at=_utc_now(),
            fingerprint_key_id=self.fingerprint_key_id,
            head_hash=_ZERO_HASH,
        )
        unsigned = draft.model_dump(mode="json", exclude={"head_hash"})
        head = _AuditHead.model_validate(
            {
                **unsigned,
                "head_hash": _hmac_hex(
                    self.fingerprint_key,
                    _HEAD_DOMAIN,
                    _canonical_json_bytes(unsigned),
                ),
            }
        )
        self._atomic_write_json(
            self._head_path,
            head.model_dump(mode="json"),
            error_code="audit.head_write_failed",
        )
        return head

    def _read_anchor(self) -> _RetentionAnchor | None:
        if not os.path.lexists(self._anchor_path):
            return None
        raw = self._read_small_file(self._anchor_path, 64 * 1024)
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise SafetyAuditLogError("audit.anchor_invalid")
        payload = _strict_json_loads(raw[:-1])
        try:
            anchor = _RetentionAnchor.model_validate(payload)
        except Exception:
            raise SafetyAuditLogError("audit.anchor_invalid") from None
        unsigned = anchor.model_dump(mode="json", exclude={"anchor_hash"})
        expected = _hmac_hex(
            self.fingerprint_key,
            _ANCHOR_DOMAIN,
            _canonical_json_bytes(unsigned),
        )
        if (
            anchor.fingerprint_key_id != self.fingerprint_key_id
            or not hmac.compare_digest(anchor.anchor_hash, expected)
            or raw[:-1] != _canonical_json_bytes(anchor.model_dump(mode="json"))
        ):
            raise SafetyAuditLogError("audit.anchor_invalid")
        return anchor

    def _enforce_retention_locked(self, current_index: int) -> int:
        if self.retention_days is None:
            return 0
        cutoff = _utc_now() - timedelta(days=self.retention_days)
        records, segments, anchor, _ = self._read_and_verify_locked()
        stale = (
            [
                item
                for item in self._segments()
                if item[0] < anchor.first_retained_segment
            ]
            if anchor is not None
            else []
        )
        for _, path in stale:
            self._reject_symlink(path)
            os.unlink(path)
        if stale:
            self._fsync_directory()
        prune: list[tuple[int, Path]] = []
        for index, path in segments:
            if index >= current_index:
                break
            modified = datetime.fromtimestamp(
                self._secure_stat(path).st_mtime,
                tz=timezone.utc,
            )
            if modified >= cutoff:
                break
            prune.append((index, path))
        if not prune:
            return len(stale)

        pruned_indexes = {index for index, _ in prune}
        retained = [
            (index, record) for index, record in records if index not in pruned_indexes
        ]
        if not retained:
            raise SafetyAuditLogError("audit.retention_invalid")
        first_segment, first_record = retained[0]
        anchor_payload = {
            "schema_version": "1.0",
            "chain_id": first_record.chain_id,
            "first_retained_segment": first_segment,
            "first_retained_sequence": first_record.sequence,
            "previous_record_hash": first_record.previous_record_hash,
            "created_at": _utc_now(),
            "fingerprint_key_id": self.fingerprint_key_id,
        }
        anchor_payload["anchor_hash"] = _hmac_hex(
            self.fingerprint_key,
            _ANCHOR_DOMAIN,
            _canonical_json_bytes(
                {
                    key: (
                        value.isoformat().replace("+00:00", "Z")
                        if isinstance(value, datetime)
                        else value
                    )
                    for key, value in anchor_payload.items()
                }
            ),
        )
        anchor = _RetentionAnchor.model_validate(anchor_payload)
        self._atomic_write_json(
            self._anchor_path,
            anchor.model_dump(mode="json"),
        )
        for _, path in prune:
            self._reject_symlink(path)
            os.unlink(path)
        self._fsync_directory()
        return len(stale) + len(prune)

    def _segments(self) -> list[tuple[int, Path]]:
        result: list[tuple[int, Path]] = []
        try:
            entries = list(os.scandir(self.directory))
        except OSError:
            raise SafetyAuditLogError("audit.directory_unavailable") from None
        for entry in entries:
            match = _SEGMENT_RE.fullmatch(entry.name)
            if match is None:
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise SafetyAuditLogError("audit.symlink_rejected")
            path = self.directory / entry.name
            self._secure_stat(path)
            result.append((int(match.group(1)), path))
        result.sort(key=lambda item: item[0])
        if len({index for index, _ in result}) != len(result):
            raise SafetyAuditLogError("audit.segment_conflict")
        return result

    def _segment_path(self, index: int) -> Path:
        return self.directory / f"safety-audit-{index:08d}.jsonl"

    def _ensure_directory(self) -> None:
        self._reject_symlink_ancestors()
        if not os.path.lexists(self.directory):
            try:
                self.directory.mkdir(parents=True, mode=0o700)
            except FileExistsError:
                # Another process may win first-use initialization. The lstat
                # checks below still reject a symlink or non-directory winner.
                pass
            except OSError:
                raise SafetyAuditLogError("audit.directory_unavailable") from None
        self._reject_symlink_ancestors()
        self._reject_symlink(self.directory)
        try:
            mode = os.lstat(self.directory).st_mode
        except OSError:
            raise SafetyAuditLogError("audit.directory_unavailable") from None
        if not stat.S_ISDIR(mode):
            raise SafetyAuditLogError("audit.directory_unavailable")
        if os.name != "nt":
            try:
                os.chmod(self.directory, 0o700)
            except OSError:
                raise SafetyAuditLogError("audit.permission_failed") from None

    def _reject_symlink_ancestors(self) -> None:
        current = Path(self.directory.anchor)
        for part in self.directory.parts[1:]:
            current /= part
            if not os.path.lexists(current):
                continue
            try:
                info = os.lstat(current)
                is_junction = getattr(current, "is_junction", None)
                if stat.S_ISLNK(info.st_mode) or (
                    callable(is_junction) and is_junction()
                ):
                    raise SafetyAuditLogError("audit.symlink_rejected")
            except SafetyAuditLogError:
                raise
            except OSError:
                raise SafetyAuditLogError("audit.path_unavailable") from None

    def _reject_symlink(self, path: Path) -> None:
        try:
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise SafetyAuditLogError("audit.symlink_rejected")
        except FileNotFoundError:
            return
        except SafetyAuditLogError:
            raise
        except OSError:
            raise SafetyAuditLogError("audit.path_unavailable") from None

    def _secure_stat(self, path: Path) -> os.stat_result:
        self._reject_symlink(path)
        try:
            info = os.stat(path, follow_symlinks=False)
        except OSError:
            raise SafetyAuditLogError("audit.path_unavailable") from None
        if not stat.S_ISREG(info.st_mode):
            raise SafetyAuditLogError("audit.path_unavailable")
        if os.name != "nt":
            try:
                os.chmod(path, 0o600)
                info = os.stat(path, follow_symlinks=False)
            except OSError:
                raise SafetyAuditLogError("audit.permission_failed") from None
            if stat.S_IMODE(info.st_mode) & 0o077:
                raise SafetyAuditLogError("audit.permission_failed")
        return info

    def _safe_open_fd(self, path: Path, flags: int, *, mode: int = 0o600) -> int:
        self._reject_symlink(path)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags, mode)
        except OSError:
            raise SafetyAuditLogError("audit.open_failed") from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise SafetyAuditLogError("audit.path_unavailable")
            if os.name != "nt":
                fchmod = getattr(os, "fchmod", None)
                if fchmod is None:
                    raise SafetyAuditLogError("audit.permission_failed")
                fchmod(fd, 0o600)
        except Exception:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def _open_read(self, path: Path) -> Iterator[Any]:
        fd = self._safe_open_fd(path, os.O_RDONLY)
        stream = os.fdopen(fd, "rb", closefd=True)
        try:
            yield stream
        finally:
            stream.close()

    def _read_small_file(self, path: Path, limit: int) -> bytes:
        with self._open_read(path) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise SafetyAuditLogError("audit.file_too_large")
        return raw

    def _append_line(self, path: Path, line: bytes) -> None:
        fd = self._safe_open_fd(
            path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        )
        try:
            offset = 0
            while offset < len(line):
                written = os.write(fd, line[offset:])
                if written <= 0:
                    raise SafetyAuditLogError("audit.append_failed")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        self._fsync_directory()

    def _atomic_write_json(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        error_code: str = "audit.anchor_write_failed",
    ) -> None:
        self._reject_symlink(path)
        raw = _canonical_json_bytes(payload) + b"\n"
        temporary = self.directory / (
            f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        fd: int | None = None
        try:
            fd = self._safe_open_fd(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    raise SafetyAuditLogError(error_code)
                offset += written
            os.fsync(fd)
            os.close(fd)
            fd = None
            self._reject_symlink(path)
            os.replace(temporary, path)
            if os.name != "nt":
                os.chmod(path, 0o600)
            self._fsync_directory()
        except Exception:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise SafetyAuditLogError(error_code) from None

    def _fsync_directory(self) -> None:
        if os.name == "nt":
            return
        try:
            fd = os.open(
                self.directory,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise SafetyAuditLogError("audit.fsync_failed") from None

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        key = os.path.normcase(str(self.directory))
        with _LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.RLock())
        with thread_lock:
            fd = self._safe_open_fd(
                self._lock_path,
                os.O_RDWR | os.O_CREAT,
            )
            acquired = False
            deadline = time.monotonic() + self.lock_timeout_seconds
            try:
                while not acquired:
                    try:
                        if os.name == "nt":
                            import msvcrt

                            if os.fstat(fd).st_size == 0:
                                os.write(fd, b"\x00")
                                os.fsync(fd)
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(  # type: ignore[attr-defined]
                                fd,
                                fcntl.LOCK_EX  # type: ignore[attr-defined]
                                | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                            )
                        acquired = True
                    except (OSError, BlockingIOError):
                        if time.monotonic() >= deadline:
                            raise SafetyAuditLogError("audit.lock_timeout") from None
                        time.sleep(0.01)
                yield
            finally:
                if acquired:
                    try:
                        if os.name == "nt":
                            import msvcrt

                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(  # type: ignore[attr-defined]
                                fd,
                                fcntl.LOCK_UN,  # type: ignore[attr-defined]
                            )
                    except OSError:
                        pass
                os.close(fd)
