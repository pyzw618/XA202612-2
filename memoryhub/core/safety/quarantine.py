"""Encrypted REVIEW quarantine storage.

The quarantine is deliberately separate from normal memory, vector, evidence,
and logging stores.  It keeps the original event only as an AES-GCM ciphertext;
the plaintext metadata contains no event body or user identifier.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SafetyResult,
    canonical_sha256,
)
from memoryhub.core.safety.detector import SensitiveDetector

if TYPE_CHECKING:
    from memoryhub.config import ReviewQuarantineConfig

_SCHEMA_VERSION = "1.0"
_REVIEW_ID_RE = re.compile(r"^review_[0-9a-f]{32}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_DEFAULT_MAX_RECORD_BYTES = 4 * 1024 * 1024
_RECORD_KEYS = frozenset(
    {
        "schema_version",
        "review_id",
        "audit_id",
        "event_ref",
        "input_fingerprint",
        "decision",
        "reason_codes",
        "highest_level",
        "rule_set_version",
        "rule_set_digest",
        "policy_version",
        "policy_digest",
        "created_at",
        "expires_at",
        "key_id",
        "nonce",
        "ciphertext",
    }
)
_AAD_KEYS = tuple(sorted(_RECORD_KEYS - {"nonce", "ciphertext"}))


class QuarantineError(RuntimeError):
    """Stable-code quarantine failure that never includes input data."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class QuarantineReceipt:
    """Safe receipt for a quarantined event."""

    review_id: str
    audit_id: str
    event_ref: str
    input_fingerprint: str
    created_at: datetime
    expires_at: datetime
    record_hash: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _utc_text(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QuarantineError("quarantine.invalid_record")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise QuarantineError("quarantine.invalid_record") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QuarantineError("quarantine.invalid_record")
    return parsed.astimezone(timezone.utc)


def _strict_json_object(raw: bytes) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise QuarantineError("quarantine.invalid_record")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except QuarantineError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise QuarantineError("quarantine.invalid_record") from None
    if not isinstance(value, dict):
        raise QuarantineError("quarantine.invalid_record")
    return value


class ReviewQuarantineStore:
    """AES-GCM store for events whose safety decision is REVIEW."""

    def __init__(
        self,
        directory: str | Path,
        *,
        encryption_key: bytes,
        key_id: str = "default",
        retention_days: int = 30,
        max_record_bytes: int = _DEFAULT_MAX_RECORD_BYTES,
        now_factory: Callable[[], datetime] | None = None,
    ):
        if not isinstance(encryption_key, bytes) or len(encryption_key) != 32:
            raise QuarantineError("quarantine.invalid_key")
        if not isinstance(key_id, str) or _SAFE_ID_RE.fullmatch(key_id) is None:
            raise QuarantineError("quarantine.invalid_key_id")
        if type(retention_days) is not int or retention_days <= 0:
            raise QuarantineError("quarantine.invalid_retention")
        if type(max_record_bytes) is not int or max_record_bytes <= 0:
            raise QuarantineError("quarantine.invalid_size_limit")
        if now_factory is not None and not callable(now_factory):
            raise QuarantineError("quarantine.invalid_clock")

        try:
            self._directory = Path(directory).absolute()
            retention = timedelta(days=retention_days)
        except (TypeError, ValueError, OverflowError, OSError):
            raise QuarantineError("quarantine.invalid_config") from None
        self._key = bytes(encryption_key)
        self._key_id = key_id
        self._retention = retention
        self._max_record_bytes = max_record_bytes
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._ensure_directory()

    @classmethod
    def from_config(
        cls,
        config: "ReviewQuarantineConfig",
        *,
        encryption_key: bytes,
        now_factory: Callable[[], datetime] | None = None,
    ) -> "ReviewQuarantineStore":
        """用已解析配置和外部设备密钥构造 REVIEW 隔离区。"""
        if not config.enabled:
            raise QuarantineError("quarantine.disabled")
        return cls(
            config.directory,
            encryption_key=encryption_key,
            key_id=config.key_id,
            retention_days=config.retention_days,
            max_record_bytes=config.max_record_bytes,
            now_factory=now_factory,
        )

    @property
    def directory(self) -> Path:
        return self._directory

    def _now(self) -> datetime:
        try:
            value = self._now_factory()
            if not isinstance(value, datetime):
                raise TypeError
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(timezone.utc)
        except Exception:
            raise QuarantineError("quarantine.invalid_clock")

    def _ensure_directory(self) -> None:
        self._reject_symlink_ancestors()
        try:
            if not os.path.lexists(self._directory):
                self._directory.mkdir(parents=True, mode=0o700)
        except FileExistsError:
            # Another process may win first-use initialization. Validate the
            # resulting filesystem object below before trusting it.
            pass
        except OSError:
            raise QuarantineError("quarantine.storage_unavailable") from None
        self._reject_symlink_ancestors()
        try:
            info = self._directory.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise QuarantineError("quarantine.unsafe_directory")
            os.chmod(self._directory, 0o700)
            if os.name == "posix":
                mode = stat.S_IMODE(self._directory.stat().st_mode)
                if mode & 0o077:
                    raise QuarantineError("quarantine.unsafe_directory")
        except QuarantineError:
            raise
        except OSError:
            raise QuarantineError("quarantine.storage_unavailable") from None

    def _reject_symlink_ancestors(self) -> None:
        current = Path(self._directory.anchor)
        for part in self._directory.parts[1:]:
            current /= part
            if not os.path.lexists(current):
                continue
            try:
                info = current.lstat()
                is_junction = getattr(current, "is_junction", None)
                if stat.S_ISLNK(info.st_mode) or (
                    callable(is_junction) and is_junction()
                ):
                    raise QuarantineError("quarantine.unsafe_directory")
            except QuarantineError:
                raise
            except OSError:
                raise QuarantineError("quarantine.storage_unavailable") from None

    def _fsync_directory(self, error_code: str) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        fd: int | None = None
        try:
            fd = os.open(self._directory, flags)
            os.fsync(fd)
        except OSError:
            raise QuarantineError(error_code) from None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _event_ref(self, event_id: str) -> str:
        return hmac.new(
            self._key,
            b"memoryhub.quarantine.event-ref.v1\0" + event_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _input_fingerprint(self, event_digest: str) -> str:
        return hmac.new(
            self._key,
            b"memoryhub.quarantine.input.v1\0" + event_digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _validate_safe_metadata(result: SafetyResult, audit_id: str) -> None:
        if not isinstance(audit_id, str) or _SAFE_ID_RE.fullmatch(audit_id) is None:
            raise QuarantineError("quarantine.unsafe_metadata")
        if any(
            _SAFE_CODE_RE.fullmatch(code) is None
            for code in result.decision.reason_codes
        ):
            raise QuarantineError("quarantine.unsafe_metadata")
        for value in (
            result.report.rule_set_version,
            result.decision.policy_version,
        ):
            if _SAFE_ID_RE.fullmatch(value) is None:
                raise QuarantineError("quarantine.unsafe_metadata")

    def put(
        self,
        event: MemoryEvent,
        result: SafetyResult,
        detector: SensitiveDetector,
        *,
        audit_id: str,
    ) -> QuarantineReceipt:
        """Encrypt and exclusively create one REVIEW record."""

        if not isinstance(event, MemoryEvent) or not isinstance(result, SafetyResult):
            raise QuarantineError("quarantine.invalid_input")
        if not isinstance(detector, SensitiveDetector):
            raise QuarantineError("quarantine.invalid_detector")
        try:
            validated = detector.validate_result(event, result)
        except Exception:
            raise QuarantineError("quarantine.validation_failed") from None
        if validated.decision.action is not SafetyAction.REVIEW:
            raise QuarantineError("quarantine.decision_not_review")
        if validated.sanitized_event is not None:
            raise QuarantineError("quarantine.invalid_review_result")
        if validated.audit.audit_id != audit_id:
            raise QuarantineError("quarantine.audit_mismatch")
        event_digest = canonical_sha256(event.model_dump(mode="json"))
        if event_digest != validated.report.event_digest:
            raise QuarantineError("quarantine.event_mismatch")
        self._validate_safe_metadata(validated, audit_id)
        self._ensure_directory()

        now = self._now()
        try:
            expires_at = now + self._retention
        except (OverflowError, ValueError):
            raise QuarantineError("quarantine.invalid_clock") from None
        review_id = f"review_{uuid.uuid4().hex}"
        event_ref = self._event_ref(event.event_id)
        fingerprint = self._input_fingerprint(event_digest)
        header: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "review_id": review_id,
            "audit_id": audit_id,
            "event_ref": event_ref,
            "input_fingerprint": fingerprint,
            "decision": SafetyAction.REVIEW.value,
            "reason_codes": list(validated.decision.reason_codes),
            "highest_level": validated.report.highest_level.value,
            "rule_set_version": validated.report.rule_set_version,
            "rule_set_digest": validated.report.rule_set_digest,
            "policy_version": validated.decision.policy_version,
            "policy_digest": validated.decision.policy_digest,
            "created_at": _utc_text(now),
            "expires_at": _utc_text(expires_at),
            "key_id": self._key_id,
        }
        nonce = os.urandom(12)
        plaintext = _canonical_json(event.model_dump(mode="json"))
        ciphertext = AESGCM(self._key).encrypt(
            nonce, plaintext, _canonical_json(header)
        )
        record = {
            **header,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        raw = _canonical_json(record) + b"\n"
        if len(raw) > self._max_record_bytes:
            raise QuarantineError("quarantine.record_too_large")
        path = self._path_for(review_id)
        temporary = self._directory / f".{review_id}.{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd: int | None = None
        published = False
        try:
            fd = os.open(temporary, flags, 0o600)
            with os.fdopen(fd, "wb", closefd=True) as stream:
                fd = None
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            if os.path.lexists(path):
                raise QuarantineError("quarantine.record_exists")
            os.replace(temporary, path)
            published = True
            if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                raise QuarantineError("quarantine.unsafe_file_permissions")
            self._fsync_directory("quarantine.write_failed")
        except FileExistsError:
            raise QuarantineError("quarantine.record_exists") from None
        except QuarantineError:
            try:
                temporary.unlink(missing_ok=True)
                if published:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
                if published:
                    path.unlink(missing_ok=True)
            except OSError:
                pass
            raise QuarantineError("quarantine.write_failed") from None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

        return QuarantineReceipt(
            review_id=review_id,
            audit_id=audit_id,
            event_ref=event_ref,
            input_fingerprint=fingerprint,
            created_at=now,
            expires_at=expires_at,
            record_hash=hashlib.sha256(raw).hexdigest(),
        )

    def _path_for(self, review_id: str) -> Path:
        if not isinstance(review_id, str) or _REVIEW_ID_RE.fullmatch(review_id) is None:
            raise QuarantineError("quarantine.invalid_review_id")
        return self._directory / f"{review_id}.json"

    @staticmethod
    def _validated_record(
        record: dict[str, object], review_id: str
    ) -> dict[str, object]:
        if frozenset(record) != _RECORD_KEYS:
            raise QuarantineError("quarantine.invalid_record")
        if (
            record.get("schema_version") != _SCHEMA_VERSION
            or record.get("review_id") != review_id
            or record.get("decision") != SafetyAction.REVIEW.value
        ):
            raise QuarantineError("quarantine.invalid_record")
        for key in ("audit_id", "key_id", "rule_set_version", "policy_version"):
            value = record.get(key)
            if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
                raise QuarantineError("quarantine.invalid_record")
        for key in (
            "event_ref",
            "input_fingerprint",
            "rule_set_digest",
            "policy_digest",
        ):
            value = record.get(key)
            if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
                raise QuarantineError("quarantine.invalid_record")
        reason_codes = record.get("reason_codes")
        if not isinstance(reason_codes, list) or any(
            not isinstance(code, str) or _SAFE_CODE_RE.fullmatch(code) is None
            for code in reason_codes
        ):
            raise QuarantineError("quarantine.invalid_record")
        _parse_utc(record.get("created_at"))
        _parse_utc(record.get("expires_at"))
        if not isinstance(record.get("highest_level"), str):
            raise QuarantineError("quarantine.invalid_record")
        try:
            base64.b64decode(str(record["nonce"]), validate=True)
            base64.b64decode(str(record["ciphertext"]), validate=True)
        except (ValueError, TypeError):
            raise QuarantineError("quarantine.invalid_record") from None
        return record

    def _read_record(self, review_id: str) -> tuple[dict[str, object], bytes]:
        self._ensure_directory()
        path = self._path_for(review_id)
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise QuarantineError("quarantine.unsafe_record")
            if info.st_size <= 0:
                raise QuarantineError("quarantine.invalid_record")
            if info.st_size > self._max_record_bytes:
                raise QuarantineError("quarantine.record_too_large")
            if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
                raise QuarantineError("quarantine.unsafe_file_permissions")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb", closefd=True) as stream:
                raw = stream.read(self._max_record_bytes + 1)
        except FileNotFoundError:
            raise QuarantineError("quarantine.not_found") from None
        except QuarantineError:
            raise
        except OSError:
            raise QuarantineError("quarantine.read_failed") from None
        if len(raw) > self._max_record_bytes:
            raise QuarantineError("quarantine.record_too_large")
        return self._validated_record(_strict_json_object(raw), review_id), raw

    def _decrypt_record(
        self,
        review_id: str,
    ) -> tuple[MemoryEvent, dict[str, object], bytes]:
        record, raw = self._read_record(review_id)
        if record["key_id"] != self._key_id:
            raise QuarantineError("quarantine.key_mismatch")
        aad = {key: record[key] for key in _AAD_KEYS}
        try:
            nonce = base64.b64decode(str(record["nonce"]), validate=True)
            ciphertext = base64.b64decode(str(record["ciphertext"]), validate=True)
            plaintext = AESGCM(self._key).decrypt(
                nonce, ciphertext, _canonical_json(aad)
            )
        except InvalidTag:
            raise QuarantineError("quarantine.integrity_error") from None
        except (ValueError, TypeError):
            raise QuarantineError("quarantine.invalid_record") from None
        try:
            event = MemoryEvent.model_validate_json(plaintext)
        except Exception:
            raise QuarantineError("quarantine.invalid_event") from None
        digest = canonical_sha256(event.model_dump(mode="json"))
        if not hmac.compare_digest(
            str(record["input_fingerprint"]),
            self._input_fingerprint(digest),
        ):
            raise QuarantineError("quarantine.event_mismatch")
        if not hmac.compare_digest(
            str(record["event_ref"]), self._event_ref(event.event_id)
        ):
            raise QuarantineError("quarantine.event_mismatch")
        return event, record, raw

    def load(self, review_id: str) -> MemoryEvent:
        """Authenticate and decrypt a quarantined event for privileged review."""

        event, record, _ = self._decrypt_record(review_id)
        if _parse_utc(record["expires_at"]) <= self._now():
            raise QuarantineError("quarantine.expired")
        return event

    def assert_persisted(self, receipt: QuarantineReceipt) -> QuarantineReceipt:
        """确认隔离回执与磁盘上的认证密文记录逐字段一致。"""
        if type(receipt) is not QuarantineReceipt:
            raise QuarantineError("quarantine.receipt_invalid")
        try:
            _, record, raw = self._decrypt_record(receipt.review_id)
            valid = (
                record["audit_id"] == receipt.audit_id
                and record["event_ref"] == receipt.event_ref
                and record["input_fingerprint"] == receipt.input_fingerprint
                and _parse_utc(record["created_at"]) == receipt.created_at
                and _parse_utc(record["expires_at"]) == receipt.expires_at
                and hmac.compare_digest(
                    hashlib.sha256(raw).hexdigest(),
                    receipt.record_hash,
                )
            )
        except QuarantineError:
            raise
        except Exception:
            raise QuarantineError("quarantine.receipt_invalid") from None
        if not valid:
            raise QuarantineError("quarantine.receipt_invalid")
        return receipt

    def delete(self, review_id: str) -> None:
        """Remove one authenticated quarantine record."""

        self._decrypt_record(review_id)
        try:
            self._path_for(review_id).unlink()
            self._fsync_directory("quarantine.delete_failed")
        except FileNotFoundError:
            raise QuarantineError("quarantine.not_found") from None
        except OSError:
            raise QuarantineError("quarantine.delete_failed") from None

    def cleanup_expired(self, *, now: datetime | None = None) -> int:
        """Authenticate and remove records beyond the configured retention window."""

        if now is None:
            reference = self._now()
        else:
            try:
                if not isinstance(now, datetime):
                    raise TypeError
                if now.tzinfo is None or now.utcoffset() is None:
                    raise ValueError
                reference = now.astimezone(timezone.utc)
            except Exception:
                raise QuarantineError("quarantine.invalid_clock") from None
        removed = 0
        failures = 0
        self._ensure_directory()
        try:
            candidates = tuple(self._directory.glob("review_*.json"))
        except OSError:
            raise QuarantineError("quarantine.cleanup_failed") from None
        for path in candidates:
            review_id = path.stem
            try:
                _, record, _ = self._decrypt_record(review_id)
            except QuarantineError:
                failures += 1
                continue
            if _parse_utc(record["expires_at"]) > reference:
                continue
            try:
                path.unlink()
            except OSError:
                raise QuarantineError("quarantine.cleanup_failed") from None
            removed += 1
        if removed:
            self._fsync_directory("quarantine.cleanup_failed")
        if failures:
            raise QuarantineError("quarantine.cleanup_incomplete")
        return removed
