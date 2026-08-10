"""Per-user sensitive-information rules with encrypted matcher persistence.

The matcher is a write-only secret.  Repositories receive only AES-256-GCM
ciphertexts and keyed fingerprints; safe views deliberately omit plaintext
matcher material.  SQLite keeps a current row plus an append-only row for each
revision, while updates and soft deletes use optimistic concurrency.

This module does not mutate the built-in rule library.  ``compile_overlay()``
returns an immutable in-memory overlay, and ``detector_provider()`` adapts that
overlay to ``SafetyWriteGate``'s per-event detector provider.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SensitiveLevel,
    SensitiveRule,
)
from memoryhub.safety_rules.regex_safety import validate_regex_safety

if TYPE_CHECKING:
    from memoryhub.config import SafetyConfig
    from memoryhub.core.safety.detector import SensitiveDetector


_SCHEMA_VERSION = "1.0"
_RULE_ID_RE = re.compile(r"^ur_[0-9a-f]{32}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_STABLE_CODE_RE = re.compile(r"^user_rule\.[a-z0-9_.-]+$")
_MAX_USER_ID_CHARS = 128
_MAX_LABEL_CHARS = 128
_DEFAULT_MAX_RULES_PER_USER = 100
_MAX_REVISIONS_PER_RULE = 100
_DEFAULT_MAX_MATCHER_CHARS = 2_048
_DEFAULT_DETECTOR_CACHE_SIZE = 256
_MAX_COMPILED_PATTERN_CHARS = 4_096
_FIXED_REPLACEMENT = "[REDACTED_USER_DEFINED]"
_CONTENT_PATH_PATTERN = (
    r"\A(?:/text\Z|/payload(?=/|\Z)|"
    r"/tool_calls/[0-9]+/(?:arguments|result|error)(?=/|\Z))"
)

_HKDF_SALT = b"memoryhub.user-rules.hkdf.salt.v1"
_ENCRYPTION_INFO = b"memoryhub.user-rules.encryption-key.v1"
_FINGERPRINT_INFO = b"memoryhub.user-rules.fingerprint-key.v1"
_USER_REF_DOMAIN = b"memoryhub.user-rules.user-ref.v1\0"
_USER_ENCRYPTION_DOMAIN = b"memoryhub.user-rules.user-encryption.v1\0"
_MATCHER_FINGERPRINT_DOMAIN = b"memoryhub.user-rules.matcher-fingerprint.v1\0"
_OVERLAY_DIGEST_DOMAIN = b"memoryhub.user-rules.overlay-digest.v1\0"
_BASE_CONFIG_DOMAIN = b"memoryhub.user-rules.base-config.v1\0"


class UserRuleError(RuntimeError):
    """A non-sensitive user-rule failure represented only by a stable code."""

    def __init__(self, code: str):
        if not isinstance(code, str) or _STABLE_CODE_RE.fullmatch(code) is None:
            code = "user_rule.internal_error"
        self.code = code
        super().__init__(code)


class UserRuleKind(str, Enum):
    """Matcher syntax exposed by the management API."""

    LITERAL = "literal"
    ADVANCED_REGEX = "advanced_regex"


class UserRuleEffect(str, Enum):
    """Pipeline effect exposed by the management API."""

    MASK_MATCH = "mask_match"
    DROP_EVENT = "drop_event"


@dataclass(frozen=True, slots=True)
class UserRuleView:
    """Safe API projection; plaintext matcher and ciphertext are both absent."""

    rule_id: str
    label: str
    kind: UserRuleKind
    effect: UserRuleEffect
    case_sensitive: bool
    replacement: str
    revision: int
    enabled: bool
    deleted: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserRuleOverlay:
    """Immutable user-specific detector overlay held only in process memory."""

    rule_set_id: str
    rule_set_version: str
    snapshot_digest: str
    rules: tuple[SensitiveRule, ...]
    revision_vector: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class _StoredUserRule:
    """Encrypted repository record.  It intentionally has no matcher field."""

    user_ref: str
    rule_id: str
    label: str
    kind: str
    effect: str
    case_sensitive: bool
    replacement: str
    revision: int
    enabled: bool
    deleted: bool
    matcher_nonce: bytes
    matcher_ciphertext: bytes
    matcher_fingerprint: str
    key_id: str
    created_at: datetime
    updated_at: datetime


class UserRuleRepository(Protocol):
    """Persistence contract consumed by ``UserRuleService``."""

    def create(self, record: _StoredUserRule, *, max_rules_per_user: int) -> None:
        """Atomically enforce quota and append revision one."""

    def get(self, user_ref: str, rule_id: str) -> _StoredUserRule | None:
        """Return the current row scoped by both user and opaque rule ID."""

    def list(
        self,
        user_ref: str,
        *,
        include_deleted: bool,
    ) -> tuple[_StoredUserRule, ...]:
        """Return current rows for one user."""

    def replace(
        self,
        record: _StoredUserRule,
        *,
        expected_revision: int,
    ) -> None:
        """Atomically compare, replace current state, and append history."""

    def history(
        self,
        user_ref: str,
        rule_id: str,
    ) -> tuple[_StoredUserRule, ...]:
        """Return every immutable revision for one user-owned rule."""


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise UserRuleError("user_rule.internal_error") from None


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise UserRuleError("user_rule.corrupt_record")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError):
        raise UserRuleError("user_rule.corrupt_record") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise UserRuleError("user_rule.corrupt_record")
    return parsed.astimezone(timezone.utc)


def _derive_subkey(master_key: bytes, info: bytes) -> bytes:
    try:
        return HKDF(
            algorithm=SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=info,
        ).derive(master_key)
    except Exception:
        raise UserRuleError("user_rule.key_unavailable") from None


class InMemoryUserRuleRepository:
    """Thread-safe encrypted repository for unit tests and ephemeral runtimes."""

    def __init__(self) -> None:
        self._current: dict[tuple[str, str], _StoredUserRule] = {}
        self._history: dict[tuple[str, str], list[_StoredUserRule]] = {}
        self._lock = threading.RLock()

    def create(self, record: _StoredUserRule, *, max_rules_per_user: int) -> None:
        key = (record.user_ref, record.rule_id)
        with self._lock:
            total_count = sum(
                1
                for candidate in self._current.values()
                if candidate.user_ref == record.user_ref
            )
            if total_count >= max_rules_per_user:
                raise UserRuleError("user_rule.limit_exceeded")
            if key in self._current:
                raise UserRuleError("user_rule.conflict")
            self._current[key] = record
            self._history[key] = [record]

    def get(self, user_ref: str, rule_id: str) -> _StoredUserRule | None:
        with self._lock:
            return self._current.get((user_ref, rule_id))

    def list(
        self,
        user_ref: str,
        *,
        include_deleted: bool,
    ) -> tuple[_StoredUserRule, ...]:
        with self._lock:
            records = [
                record
                for record in self._current.values()
                if record.user_ref == user_ref
                and (include_deleted or not record.deleted)
            ]
            return tuple(
                sorted(records, key=lambda item: (item.created_at, item.rule_id))
            )

    def replace(
        self,
        record: _StoredUserRule,
        *,
        expected_revision: int,
    ) -> None:
        key = (record.user_ref, record.rule_id)
        with self._lock:
            current = self._current.get(key)
            if current is None or current.deleted:
                raise UserRuleError("user_rule.not_found")
            if current.revision != expected_revision:
                raise UserRuleError("user_rule.conflict")
            if record.revision != expected_revision + 1:
                raise UserRuleError("user_rule.invalid_revision")
            self._current[key] = record
            self._history[key].append(record)

    def history(
        self,
        user_ref: str,
        rule_id: str,
    ) -> tuple[_StoredUserRule, ...]:
        with self._lock:
            return tuple(self._history.get((user_ref, rule_id), ()))


class SQLiteUserRuleRepository:
    """SQLite current-state store with an independent append-only history table."""

    _COLUMNS = (
        "user_ref, rule_id, label, kind, effect, case_sensitive, replacement, "
        "revision, enabled, deleted, matcher_nonce, matcher_ciphertext, "
        "matcher_fingerprint, key_id, created_at, updated_at"
    )

    def __init__(self, database_path: str | Path):
        if not isinstance(database_path, (str, Path)):
            raise UserRuleError("user_rule.storage_error")
        try:
            path_text = os.fspath(database_path)
            if not path_text or "\x00" in path_text:
                raise ValueError
            if path_text != ":memory:":
                parent = Path(path_text).expanduser().absolute().parent
                parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                path_text,
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
        except (OSError, TypeError, ValueError, sqlite3.Error):
            raise UserRuleError("user_rule.storage_error") from None
        self._lock = threading.RLock()
        self._closed = False
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS user_sensitive_rules (
                user_ref TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                label TEXT NOT NULL,
                kind TEXT NOT NULL
                    CHECK (kind IN ('literal', 'advanced_regex')),
                effect TEXT NOT NULL
                    CHECK (effect IN ('mask_match', 'drop_event')),
                case_sensitive INTEGER NOT NULL
                    CHECK (case_sensitive IN (0, 1)),
                replacement TEXT NOT NULL
                    CHECK (replacement = '[REDACTED_USER_DEFINED]'),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                matcher_nonce BLOB NOT NULL CHECK (length(matcher_nonce) = 12),
                matcher_ciphertext BLOB NOT NULL,
                matcher_fingerprint TEXT NOT NULL
                    CHECK (length(matcher_fingerprint) = 64),
                key_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_ref, rule_id)
            ) WITHOUT ROWID
            """,
            """
            CREATE TABLE IF NOT EXISTS user_sensitive_rule_versions (
                user_ref TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                label TEXT NOT NULL,
                kind TEXT NOT NULL
                    CHECK (kind IN ('literal', 'advanced_regex')),
                effect TEXT NOT NULL
                    CHECK (effect IN ('mask_match', 'drop_event')),
                case_sensitive INTEGER NOT NULL
                    CHECK (case_sensitive IN (0, 1)),
                replacement TEXT NOT NULL
                    CHECK (replacement = '[REDACTED_USER_DEFINED]'),
                revision INTEGER NOT NULL CHECK (revision >= 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
                matcher_nonce BLOB NOT NULL CHECK (length(matcher_nonce) = 12),
                matcher_ciphertext BLOB NOT NULL,
                matcher_fingerprint TEXT NOT NULL
                    CHECK (length(matcher_fingerprint) = 64),
                key_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_ref, rule_id, revision),
                FOREIGN KEY (user_ref, rule_id)
                    REFERENCES user_sensitive_rules (user_ref, rule_id)
                    ON DELETE RESTRICT
            ) WITHOUT ROWID
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_user_sensitive_rules_scope
            ON user_sensitive_rules (user_ref, deleted, created_at, rule_id)
            """,
        )
        with self._lock:
            try:
                for statement in statements:
                    self._connection.execute(statement)
            except sqlite3.Error:
                self.close()
                raise UserRuleError("user_rule.storage_error") from None

    @staticmethod
    def _parameters(record: _StoredUserRule) -> tuple[object, ...]:
        return (
            record.user_ref,
            record.rule_id,
            record.label,
            record.kind,
            record.effect,
            int(record.case_sensitive),
            record.replacement,
            record.revision,
            int(record.enabled),
            int(record.deleted),
            sqlite3.Binary(record.matcher_nonce),
            sqlite3.Binary(record.matcher_ciphertext),
            record.matcher_fingerprint,
            record.key_id,
            _utc_text(record.created_at),
            _utc_text(record.updated_at),
        )

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> _StoredUserRule:
        if len(row) != 16:
            raise UserRuleError("user_rule.corrupt_record")
        try:
            case_sensitive = row[5]
            revision = row[7]
            enabled = row[8]
            deleted = row[9]
            if (
                not isinstance(case_sensitive, int)
                or not isinstance(revision, int)
                or not isinstance(enabled, int)
                or not isinstance(deleted, int)
            ):
                raise ValueError
            if (
                case_sensitive not in (0, 1)
                or enabled not in (0, 1)
                or deleted not in (0, 1)
            ):
                raise ValueError
            nonce_value = row[10]
            ciphertext_value = row[11]
            if not isinstance(nonce_value, (bytes, bytearray, memoryview)):
                raise ValueError
            if not isinstance(ciphertext_value, (bytes, bytearray, memoryview)):
                raise ValueError
            nonce = bytes(nonce_value)
            ciphertext = bytes(ciphertext_value)
            return _StoredUserRule(
                user_ref=str(row[0]),
                rule_id=str(row[1]),
                label=str(row[2]),
                kind=str(row[3]),
                effect=str(row[4]),
                case_sensitive=bool(case_sensitive),
                replacement=str(row[6]),
                revision=revision,
                enabled=bool(enabled),
                deleted=bool(deleted),
                matcher_nonce=nonce,
                matcher_ciphertext=ciphertext,
                matcher_fingerprint=str(row[12]),
                key_id=str(row[13]),
                created_at=_parse_utc(row[14]),
                updated_at=_parse_utc(row[15]),
            )
        except UserRuleError:
            raise
        except (TypeError, ValueError, OverflowError):
            raise UserRuleError("user_rule.corrupt_record") from None

    def _ensure_open(self) -> None:
        if self._closed:
            raise UserRuleError("user_rule.storage_error")

    def _rollback(self) -> None:
        try:
            self._connection.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def create(self, record: _StoredUserRule, *, max_rules_per_user: int) -> None:
        insert = (
            f"INSERT INTO user_sensitive_rules ({self._COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        insert_history = (
            f"INSERT INTO user_sensitive_rule_versions ({self._COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM user_sensitive_rules
                    WHERE user_ref = ?
                    """,
                    (record.user_ref,),
                ).fetchone()
                if row is None or type(row[0]) is not int:
                    raise UserRuleError("user_rule.storage_error")
                if row[0] >= max_rules_per_user:
                    raise UserRuleError("user_rule.limit_exceeded")
                parameters = self._parameters(record)
                self._connection.execute(insert, parameters)
                self._connection.execute(insert_history, parameters)
                self._connection.execute("COMMIT")
            except UserRuleError:
                self._rollback()
                raise
            except sqlite3.IntegrityError:
                self._rollback()
                raise UserRuleError("user_rule.conflict") from None
            except sqlite3.Error:
                self._rollback()
                raise UserRuleError("user_rule.storage_error") from None

    def get(self, user_ref: str, rule_id: str) -> _StoredUserRule | None:
        with self._lock:
            self._ensure_open()
            try:
                row = self._connection.execute(
                    f"""
                    SELECT {self._COLUMNS}
                    FROM user_sensitive_rules
                    WHERE user_ref = ? AND rule_id = ?
                    """,
                    (user_ref, rule_id),
                ).fetchone()
            except sqlite3.Error:
                raise UserRuleError("user_rule.storage_error") from None
        return None if row is None else self._from_row(row)

    def list(
        self,
        user_ref: str,
        *,
        include_deleted: bool,
    ) -> tuple[_StoredUserRule, ...]:
        deleted_clause = "" if include_deleted else "AND deleted = 0"
        with self._lock:
            self._ensure_open()
            try:
                rows = self._connection.execute(
                    f"""
                    SELECT {self._COLUMNS}
                    FROM user_sensitive_rules
                    WHERE user_ref = ? {deleted_clause}
                    ORDER BY created_at ASC, rule_id ASC
                    """,
                    (user_ref,),
                ).fetchall()
            except sqlite3.Error:
                raise UserRuleError("user_rule.storage_error") from None
        return tuple(self._from_row(row) for row in rows)

    def replace(
        self,
        record: _StoredUserRule,
        *,
        expected_revision: int,
    ) -> None:
        assignments = (
            "label = ?, kind = ?, effect = ?, case_sensitive = ?, "
            "replacement = ?, revision = ?, enabled = ?, deleted = ?, "
            "matcher_nonce = ?, matcher_ciphertext = ?, "
            "matcher_fingerprint = ?, key_id = ?, created_at = ?, updated_at = ?"
        )
        update_parameters = self._parameters(record)[2:] + (
            record.user_ref,
            record.rule_id,
            expected_revision,
        )
        insert_history = (
            f"INSERT INTO user_sensitive_rule_versions ({self._COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        with self._lock:
            self._ensure_open()
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                current = self._connection.execute(
                    """
                    SELECT revision, deleted
                    FROM user_sensitive_rules
                    WHERE user_ref = ? AND rule_id = ?
                    """,
                    (record.user_ref, record.rule_id),
                ).fetchone()
                if current is None or current[1] != 0:
                    raise UserRuleError("user_rule.not_found")
                if current[0] != expected_revision:
                    raise UserRuleError("user_rule.conflict")
                if record.revision != expected_revision + 1:
                    raise UserRuleError("user_rule.invalid_revision")
                cursor = self._connection.execute(
                    f"""
                    UPDATE user_sensitive_rules
                    SET {assignments}
                    WHERE user_ref = ? AND rule_id = ?
                      AND revision = ? AND deleted = 0
                    """,
                    update_parameters,
                )
                if cursor.rowcount != 1:
                    raise UserRuleError("user_rule.conflict")
                self._connection.execute(
                    insert_history,
                    self._parameters(record),
                )
                self._connection.execute("COMMIT")
            except UserRuleError:
                self._rollback()
                raise
            except sqlite3.IntegrityError:
                self._rollback()
                raise UserRuleError("user_rule.conflict") from None
            except sqlite3.Error:
                self._rollback()
                raise UserRuleError("user_rule.storage_error") from None

    def history(
        self,
        user_ref: str,
        rule_id: str,
    ) -> tuple[_StoredUserRule, ...]:
        with self._lock:
            self._ensure_open()
            try:
                rows = self._connection.execute(
                    f"""
                    SELECT {self._COLUMNS}
                    FROM user_sensitive_rule_versions
                    WHERE user_ref = ? AND rule_id = ?
                    ORDER BY revision ASC
                    """,
                    (user_ref, rule_id),
                ).fetchall()
            except sqlite3.Error:
                raise UserRuleError("user_rule.storage_error") from None
        return tuple(self._from_row(row) for row in rows)

    def close(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            if getattr(self, "_closed", True):
                return
            try:
                self._connection.close()
            except sqlite3.Error:
                raise UserRuleError("user_rule.storage_error") from None
            finally:
                self._closed = True

    def __enter__(self) -> "SQLiteUserRuleRepository":
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class UserRuleService:
    """Validate, encrypt, version, and compile per-user safety rules."""

    FIXED_REPLACEMENT = _FIXED_REPLACEMENT
    CONTENT_PATH_PATTERN = _CONTENT_PATH_PATTERN

    def __init__(
        self,
        repository: UserRuleRepository,
        *,
        master_key: bytes,
        key_id: str = "default",
        max_rules_per_user: int = _DEFAULT_MAX_RULES_PER_USER,
        max_matcher_chars: int = _DEFAULT_MAX_MATCHER_CHARS,
        allow_advanced_regex: bool = False,
        detector_cache_size: int = _DEFAULT_DETECTOR_CACHE_SIZE,
        now_factory: Callable[[], datetime] | None = None,
    ):
        if not isinstance(master_key, bytes) or len(master_key) != 32:
            raise UserRuleError("user_rule.key_unavailable")
        if not isinstance(key_id, str) or _KEY_ID_RE.fullmatch(key_id) is None:
            raise UserRuleError("user_rule.invalid_key_id")
        if (
            type(max_rules_per_user) is not int
            or max_rules_per_user <= 0
            or type(max_matcher_chars) is not int
            or max_matcher_chars <= 0
            or type(detector_cache_size) is not int
            or detector_cache_size <= 0
        ):
            raise UserRuleError("user_rule.invalid_limits")
        if type(allow_advanced_regex) is not bool:
            raise UserRuleError("user_rule.invalid_limits")
        if now_factory is not None and not callable(now_factory):
            raise UserRuleError("user_rule.invalid_clock")
        for method_name in ("create", "get", "list", "replace", "history"):
            if not callable(getattr(repository, method_name, None)):
                raise UserRuleError("user_rule.invalid_repository")

        self._repository = repository
        self._key_id = key_id
        self._max_rules_per_user = max_rules_per_user
        self._max_matcher_chars = max_matcher_chars
        self._allow_advanced_regex = allow_advanced_regex
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self._encryption_root_key = _derive_subkey(master_key, _ENCRYPTION_INFO)
        self._fingerprint_key = _derive_subkey(master_key, _FINGERPRINT_INFO)
        self._detector_cache_size = detector_cache_size
        self._detector_cache: OrderedDict[tuple[str, str, str], SensitiveDetector] = (
            OrderedDict()
        )
        self._cache_lock = threading.RLock()

    @classmethod
    def with_sqlite(
        cls,
        database_path: str | Path,
        *,
        master_key: bytes,
        key_id: str = "default",
        max_rules_per_user: int = _DEFAULT_MAX_RULES_PER_USER,
        max_matcher_chars: int = _DEFAULT_MAX_MATCHER_CHARS,
        allow_advanced_regex: bool = False,
        detector_cache_size: int = _DEFAULT_DETECTOR_CACHE_SIZE,
        now_factory: Callable[[], datetime] | None = None,
    ) -> "UserRuleService":
        repository = SQLiteUserRuleRepository(database_path)
        try:
            return cls(
                repository,
                master_key=master_key,
                key_id=key_id,
                max_rules_per_user=max_rules_per_user,
                max_matcher_chars=max_matcher_chars,
                allow_advanced_regex=allow_advanced_regex,
                detector_cache_size=detector_cache_size,
                now_factory=now_factory,
            )
        except Exception:
            repository.close()
            raise

    def _now(self) -> datetime:
        try:
            value = self._now_factory()
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError
            return value.astimezone(timezone.utc)
        except Exception:
            raise UserRuleError("user_rule.invalid_clock") from None

    def _user_ref(self, user_id: str) -> str:
        if (
            not isinstance(user_id, str)
            or not user_id
            or not user_id.strip()
            or len(user_id) > _MAX_USER_ID_CHARS
        ):
            raise UserRuleError("user_rule.invalid_user_id")
        try:
            encoded = user_id.encode("utf-8")
        except UnicodeError:
            raise UserRuleError("user_rule.invalid_user_id") from None
        return hmac.new(
            self._fingerprint_key,
            _USER_REF_DOMAIN + encoded,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _rule_id(value: str) -> str:
        if not isinstance(value, str) or _RULE_ID_RE.fullmatch(value) is None:
            raise UserRuleError("user_rule.invalid_rule_id")
        return value

    @staticmethod
    def _label(value: str) -> str:
        normalized = value.strip() if isinstance(value, str) else ""
        if (
            not isinstance(value, str)
            or not normalized
            or len(normalized) > _MAX_LABEL_CHARS
            or any(
                ord(character) < 0x20 or ord(character) == 0x7F for character in value
            )
        ):
            raise UserRuleError("user_rule.invalid_label")
        try:
            normalized.encode("utf-8")
        except UnicodeError:
            raise UserRuleError("user_rule.invalid_label") from None
        return normalized

    @staticmethod
    def _kind(value: UserRuleKind | str) -> UserRuleKind:
        try:
            return value if isinstance(value, UserRuleKind) else UserRuleKind(value)
        except (TypeError, ValueError):
            raise UserRuleError("user_rule.invalid_kind") from None

    @staticmethod
    def _effect(value: UserRuleEffect | str) -> UserRuleEffect:
        try:
            return value if isinstance(value, UserRuleEffect) else UserRuleEffect(value)
        except (TypeError, ValueError):
            raise UserRuleError("user_rule.invalid_effect") from None

    @staticmethod
    def _strict_bool(value: bool, code: str) -> bool:
        if type(value) is not bool:
            raise UserRuleError(code)
        return value

    @staticmethod
    def _expected_revision(value: int) -> int:
        if type(value) is not int or value <= 0:
            raise UserRuleError("user_rule.invalid_revision")
        return value

    def _compiled_pattern(
        self,
        *,
        kind: UserRuleKind,
        matcher: str,
        case_sensitive: bool,
        effect: UserRuleEffect,
    ) -> str:
        if (
            not isinstance(matcher, str)
            or not matcher
            or len(matcher) > self._max_matcher_chars
        ):
            raise UserRuleError("user_rule.invalid_matcher")
        try:
            matcher.encode("utf-8")
        except UnicodeError:
            raise UserRuleError("user_rule.invalid_matcher") from None

        semantic_matcher = self._semantic_matcher(kind, matcher)
        if kind is UserRuleKind.ADVANCED_REGEX:
            if not self._allow_advanced_regex:
                raise UserRuleError("user_rule.advanced_regex_disabled")
            try:
                validate_regex_safety(semantic_matcher)
            except Exception:
                raise UserRuleError("user_rule.unsafe_regex") from None
            pattern = semantic_matcher
        else:
            pattern = re.escape(semantic_matcher)

        if not case_sensitive:
            pattern = f"(?i:{pattern})"
        if len(pattern) > _MAX_COMPILED_PATTERN_CHARS:
            raise UserRuleError("user_rule.invalid_matcher")
        try:
            validate_regex_safety(pattern)
            compiled = re.compile(pattern)
        except Exception:
            code = (
                "user_rule.unsafe_regex"
                if kind is UserRuleKind.ADVANCED_REGEX
                else "user_rule.invalid_matcher"
            )
            raise UserRuleError(code) from None
        if compiled.search("") is not None:
            raise UserRuleError("user_rule.invalid_matcher")
        if (
            effect is UserRuleEffect.MASK_MATCH
            and compiled.search(_FIXED_REPLACEMENT) is not None
        ):
            raise UserRuleError("user_rule.invalid_matcher")
        return pattern

    def _semantic_matcher(
        self,
        kind: UserRuleKind,
        matcher: str,
    ) -> str:
        if kind is UserRuleKind.ADVANCED_REGEX:
            return matcher
        try:
            from memoryhub.core.safety.detector import normalize_sensitive_text

            normalized = normalize_sensitive_text(matcher)
        except Exception:
            raise UserRuleError("user_rule.invalid_matcher") from None
        if not normalized or len(normalized) > self._max_matcher_chars:
            raise UserRuleError("user_rule.invalid_matcher")
        return normalized

    def _matcher_fingerprint(
        self,
        *,
        user_ref: str,
        kind: UserRuleKind,
        matcher: str,
        case_sensitive: bool,
    ) -> str:
        payload = _canonical_json(
            {
                "case_sensitive": case_sensitive,
                "kind": kind.value,
                "matcher": self._semantic_matcher(kind, matcher),
                "user_ref": user_ref,
            }
        )
        return hmac.new(
            self._fingerprint_key,
            _MATCHER_FINGERPRINT_DOMAIN + payload,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _aad(record: _StoredUserRule) -> bytes:
        return _canonical_json(
            {
                "schema_version": _SCHEMA_VERSION,
                "user_ref": record.user_ref,
                "rule_id": record.rule_id,
                "label": record.label,
                "kind": record.kind,
                "effect": record.effect,
                "case_sensitive": record.case_sensitive,
                "replacement": record.replacement,
                "revision": record.revision,
                "enabled": record.enabled,
                "deleted": record.deleted,
                "matcher_fingerprint": record.matcher_fingerprint,
                "key_id": record.key_id,
                "created_at": _utc_text(record.created_at),
                "updated_at": _utc_text(record.updated_at),
            }
        )

    def _user_encryption_key(self, user_ref: str) -> bytes:
        return hmac.new(
            self._encryption_root_key,
            _USER_ENCRYPTION_DOMAIN + user_ref.encode("ascii"),
            hashlib.sha256,
        ).digest()

    def assert_key_separation(self, *other_keys: bytes) -> None:
        """Fail before storage/Gate creation when another safety role reuses this key."""
        for candidate in other_keys:
            if not isinstance(candidate, bytes) or len(candidate) < 32:
                raise UserRuleError("user_rule.key_unavailable")
            candidate_root = _derive_subkey(candidate, _ENCRYPTION_INFO)
            if hmac.compare_digest(candidate_root, self._encryption_root_key):
                raise UserRuleError("user_rule.key_reuse")

    def _encrypted_record(
        self,
        *,
        user_ref: str,
        rule_id: str,
        label: str,
        kind: UserRuleKind,
        effect: UserRuleEffect,
        case_sensitive: bool,
        matcher: str,
        revision: int,
        enabled: bool,
        deleted: bool,
        created_at: datetime,
        updated_at: datetime,
    ) -> _StoredUserRule:
        fingerprint = self._matcher_fingerprint(
            user_ref=user_ref,
            kind=kind,
            matcher=matcher,
            case_sensitive=case_sensitive,
        )
        nonce = secrets.token_bytes(12)
        unencrypted = _StoredUserRule(
            user_ref=user_ref,
            rule_id=rule_id,
            label=label,
            kind=kind.value,
            effect=effect.value,
            case_sensitive=case_sensitive,
            replacement=_FIXED_REPLACEMENT,
            revision=revision,
            enabled=enabled,
            deleted=deleted,
            matcher_nonce=nonce,
            matcher_ciphertext=b"",
            matcher_fingerprint=fingerprint,
            key_id=self._key_id,
            created_at=created_at,
            updated_at=updated_at,
        )
        try:
            ciphertext = AESGCM(self._user_encryption_key(user_ref)).encrypt(
                nonce,
                matcher.encode("utf-8"),
                self._aad(unencrypted),
            )
        except Exception:
            raise UserRuleError("user_rule.encryption_error") from None
        return replace(unencrypted, matcher_ciphertext=ciphertext)

    def _validate_stored(self, record: _StoredUserRule) -> None:
        try:
            if (
                _FINGERPRINT_RE.fullmatch(record.user_ref) is None
                or _RULE_ID_RE.fullmatch(record.rule_id) is None
                or _FINGERPRINT_RE.fullmatch(record.matcher_fingerprint) is None
                or _KEY_ID_RE.fullmatch(record.key_id) is None
                or record.replacement != _FIXED_REPLACEMENT
                or type(record.revision) is not int
                or record.revision <= 0
                or type(record.enabled) is not bool
                or type(record.deleted) is not bool
                or type(record.case_sensitive) is not bool
                or not isinstance(record.matcher_nonce, bytes)
                or len(record.matcher_nonce) != 12
                or not isinstance(record.matcher_ciphertext, bytes)
                or len(record.matcher_ciphertext) < 16
                or not isinstance(record.created_at, datetime)
                or record.created_at.tzinfo is None
                or not isinstance(record.updated_at, datetime)
                or record.updated_at.tzinfo is None
                or record.updated_at < record.created_at
            ):
                raise ValueError
            self._label(record.label)
            self._kind(record.kind)
            self._effect(record.effect)
        except UserRuleError:
            raise UserRuleError("user_rule.corrupt_record") from None
        except (TypeError, ValueError):
            raise UserRuleError("user_rule.corrupt_record") from None

    def _decrypt_matcher(self, record: _StoredUserRule) -> str:
        self._validate_stored(record)
        if record.key_id != self._key_id:
            raise UserRuleError("user_rule.key_mismatch")
        unencrypted = replace(record, matcher_ciphertext=b"")
        try:
            plaintext = AESGCM(self._user_encryption_key(record.user_ref)).decrypt(
                record.matcher_nonce,
                record.matcher_ciphertext,
                self._aad(unencrypted),
            )
            matcher = plaintext.decode("utf-8")
        except InvalidTag:
            raise UserRuleError("user_rule.integrity_error") from None
        except (TypeError, ValueError, UnicodeError):
            raise UserRuleError("user_rule.corrupt_record") from None
        expected = self._matcher_fingerprint(
            user_ref=record.user_ref,
            kind=self._kind(record.kind),
            matcher=matcher,
            case_sensitive=record.case_sensitive,
        )
        if not hmac.compare_digest(expected, record.matcher_fingerprint):
            raise UserRuleError("user_rule.integrity_error")
        return matcher

    def _to_view(self, record: _StoredUserRule) -> UserRuleView:
        # Authenticating the ciphertext prevents a tampered metadata row from
        # being returned even though the plaintext itself is intentionally dropped.
        self._decrypt_matcher(record)
        return UserRuleView(
            rule_id=record.rule_id,
            label=record.label,
            kind=self._kind(record.kind),
            effect=self._effect(record.effect),
            case_sensitive=record.case_sensitive,
            replacement=record.replacement,
            revision=record.revision,
            enabled=record.enabled,
            deleted=record.deleted,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def create_rule(
        self,
        user_id: str,
        *,
        label: str,
        kind: UserRuleKind | str,
        effect: UserRuleEffect | str,
        matcher: str,
        case_sensitive: bool = False,
        enabled: bool = True,
    ) -> UserRuleView:
        user_ref = self._user_ref(user_id)
        normalized_label = self._label(label)
        normalized_kind = self._kind(kind)
        normalized_effect = self._effect(effect)
        normalized_case = self._strict_bool(
            case_sensitive, "user_rule.invalid_case_sensitive"
        )
        normalized_enabled = self._strict_bool(enabled, "user_rule.invalid_enabled")
        self._compiled_pattern(
            kind=normalized_kind,
            matcher=matcher,
            case_sensitive=normalized_case,
            effect=normalized_effect,
        )
        now = self._now()
        record = self._encrypted_record(
            user_ref=user_ref,
            rule_id=f"ur_{uuid.uuid4().hex}",
            label=normalized_label,
            kind=normalized_kind,
            effect=normalized_effect,
            case_sensitive=normalized_case,
            matcher=matcher,
            revision=1,
            enabled=normalized_enabled,
            deleted=False,
            created_at=now,
            updated_at=now,
        )
        self._repository.create(
            record,
            max_rules_per_user=self._max_rules_per_user,
        )
        return self._to_view(record)

    def _current(
        self,
        user_id: str,
        rule_id: str,
        *,
        include_deleted: bool,
    ) -> tuple[str, _StoredUserRule]:
        user_ref = self._user_ref(user_id)
        normalized_rule_id = self._rule_id(rule_id)
        record = self._repository.get(user_ref, normalized_rule_id)
        if record is None:
            raise UserRuleError("user_rule.not_found")
        if record.user_ref != user_ref or record.rule_id != normalized_rule_id:
            raise UserRuleError("user_rule.integrity_error")
        self._decrypt_matcher(record)
        if record.deleted and not include_deleted:
            raise UserRuleError("user_rule.not_found")
        return user_ref, record

    def get_rule(
        self,
        user_id: str,
        rule_id: str,
        *,
        include_deleted: bool = False,
    ) -> UserRuleView:
        _, record = self._current(
            user_id,
            rule_id,
            include_deleted=include_deleted,
        )
        return self._to_view(record)

    def list_rules(
        self,
        user_id: str,
        *,
        include_deleted: bool = False,
    ) -> tuple[UserRuleView, ...]:
        if type(include_deleted) is not bool:
            raise UserRuleError("user_rule.invalid_query")
        user_ref = self._user_ref(user_id)
        records = self._repository.list(user_ref, include_deleted=True)
        if any(record.user_ref != user_ref for record in records):
            raise UserRuleError("user_rule.integrity_error")
        for record in records:
            self._decrypt_matcher(record)
        visible = (
            records
            if include_deleted
            else tuple(record for record in records if not record.deleted)
        )
        return tuple(self._to_view(record) for record in visible)

    def update_rule(
        self,
        user_id: str,
        rule_id: str,
        *,
        expected_revision: int,
        label: str | None = None,
        kind: UserRuleKind | str | None = None,
        effect: UserRuleEffect | str | None = None,
        matcher: str | None = None,
        case_sensitive: bool | None = None,
        enabled: bool | None = None,
    ) -> UserRuleView:
        expected = self._expected_revision(expected_revision)
        if all(
            value is None
            for value in (label, kind, effect, matcher, case_sensitive, enabled)
        ):
            raise UserRuleError("user_rule.invalid_update")
        user_ref, current = self._current(
            user_id,
            rule_id,
            include_deleted=False,
        )
        if current.revision != expected:
            raise UserRuleError("user_rule.conflict")
        if current.revision >= _MAX_REVISIONS_PER_RULE - 1:
            # Reserve the final bounded revision for a soft-delete tombstone.
            raise UserRuleError("user_rule.limit_exceeded")
        current_matcher = self._decrypt_matcher(current)
        next_label = current.label if label is None else self._label(label)
        next_kind = self._kind(current.kind if kind is None else kind)
        next_effect = self._effect(current.effect if effect is None else effect)
        next_matcher = current_matcher if matcher is None else matcher
        next_case = (
            current.case_sensitive
            if case_sensitive is None
            else self._strict_bool(case_sensitive, "user_rule.invalid_case_sensitive")
        )
        next_enabled = (
            current.enabled
            if enabled is None
            else self._strict_bool(enabled, "user_rule.invalid_enabled")
        )
        self._compiled_pattern(
            kind=next_kind,
            matcher=next_matcher,
            case_sensitive=next_case,
            effect=next_effect,
        )
        record = self._encrypted_record(
            user_ref=user_ref,
            rule_id=current.rule_id,
            label=next_label,
            kind=next_kind,
            effect=next_effect,
            case_sensitive=next_case,
            matcher=next_matcher,
            revision=expected + 1,
            enabled=next_enabled,
            deleted=False,
            created_at=current.created_at,
            updated_at=self._now(),
        )
        self._repository.replace(record, expected_revision=expected)
        return self._to_view(record)

    def delete_rule(
        self,
        user_id: str,
        rule_id: str,
        *,
        expected_revision: int,
    ) -> UserRuleView:
        expected = self._expected_revision(expected_revision)
        user_ref, current = self._current(
            user_id,
            rule_id,
            include_deleted=False,
        )
        if current.revision != expected:
            raise UserRuleError("user_rule.conflict")
        if current.revision >= _MAX_REVISIONS_PER_RULE:
            raise UserRuleError("user_rule.limit_exceeded")
        matcher = self._decrypt_matcher(current)
        record = self._encrypted_record(
            user_ref=user_ref,
            rule_id=current.rule_id,
            label=current.label,
            kind=self._kind(current.kind),
            effect=self._effect(current.effect),
            case_sensitive=current.case_sensitive,
            matcher=matcher,
            revision=expected + 1,
            enabled=False,
            deleted=True,
            created_at=current.created_at,
            updated_at=self._now(),
        )
        self._repository.replace(record, expected_revision=expected)
        return self._to_view(record)

    def list_rule_versions(
        self,
        user_id: str,
        rule_id: str,
    ) -> tuple[UserRuleView, ...]:
        user_ref = self._user_ref(user_id)
        normalized_rule_id = self._rule_id(rule_id)
        records = self._repository.history(user_ref, normalized_rule_id)
        if not records:
            raise UserRuleError("user_rule.not_found")
        if any(
            record.user_ref != user_ref or record.rule_id != normalized_rule_id
            for record in records
        ):
            raise UserRuleError("user_rule.integrity_error")
        return tuple(self._to_view(record) for record in records)

    def _overlay_digest(
        self,
        user_ref: str,
        records: tuple[_StoredUserRule, ...],
    ) -> str:
        payload = _canonical_json(
            {
                "schema_version": _SCHEMA_VERSION,
                "user_ref": user_ref,
                "rules": [
                    {
                        "rule_id": record.rule_id,
                        "label": record.label,
                        "kind": record.kind,
                        "effect": record.effect,
                        "case_sensitive": record.case_sensitive,
                        "replacement": record.replacement,
                        "revision": record.revision,
                        "enabled": record.enabled,
                        "matcher_fingerprint": record.matcher_fingerprint,
                    }
                    for record in records
                ],
            }
        )
        return hmac.new(
            self._fingerprint_key,
            _OVERLAY_DIGEST_DOMAIN + payload,
            hashlib.sha256,
        ).hexdigest()

    def compile_overlay(self, user_id: str) -> UserRuleOverlay:
        user_ref = self._user_ref(user_id)
        records = self._repository.list(user_ref, include_deleted=True)
        if any(record.user_ref != user_ref for record in records):
            raise UserRuleError("user_rule.integrity_error")
        authenticated = tuple(
            (record, self._decrypt_matcher(record)) for record in records
        )
        active = tuple(
            sorted(
                (
                    (record, matcher)
                    for record, matcher in authenticated
                    if record.enabled and not record.deleted
                ),
                key=lambda item: item[0].rule_id,
            )
        )
        rules: list[SensitiveRule] = []
        try:
            for record, matcher in active:
                kind = self._kind(record.kind)
                effect = self._effect(record.effect)
                pattern = self._compiled_pattern(
                    kind=kind,
                    matcher=matcher,
                    case_sensitive=record.case_sensitive,
                    effect=effect,
                )
                rules.append(
                    SensitiveRule(
                        name=f"user.rule.{record.rule_id[3:]}",
                        version=f"1.{record.revision}.0",
                        pattern=pattern,
                        level=SensitiveLevel.HIGH,
                        action=(
                            SafetyAction.MASK
                            if effect is UserRuleEffect.MASK_MATCH
                            else SafetyAction.REJECT
                        ),
                        reason_code="user_rule.match",
                        reason="User-defined sensitive information matched.",
                        standard_source="User-defined local safety rule.",
                        replacement=_FIXED_REPLACEMENT,
                        match_group=0,
                        path_pattern=_CONTENT_PATH_PATTERN,
                    )
                )
        except UserRuleError:
            raise
        except Exception:
            raise UserRuleError("user_rule.compile_error") from None
        return UserRuleOverlay(
            rule_set_id="memoryhub.user-rule-overlay",
            rule_set_version=_SCHEMA_VERSION,
            snapshot_digest=self._overlay_digest(
                user_ref,
                tuple(record for record, _ in active),
            ),
            rules=tuple(rules),
            revision_vector=tuple(
                (record.rule_id, record.revision) for record, _ in active
            ),
        )

    def _base_config_digest(self, config: "SafetyConfig") -> str:
        try:
            payload = _canonical_json(
                {
                    "rule_set_id": config.rule_set_id,
                    "rule_set_version": config.rule_set_version,
                    "rule_set_digest": config.rule_set_digest,
                    "policy": config.policy.model_dump(mode="json"),
                    "auto_mask": config.auto_mask,
                    "reject_on_detect": config.reject_on_detect,
                    "limits": {
                        "max_depth": config.max_depth,
                        "max_field_chars": config.max_field_chars,
                        "max_scan_bytes": config.max_scan_bytes,
                        "max_scanned_fields": config.max_scanned_fields,
                        "max_candidates": config.max_candidates,
                        "max_findings": config.max_findings,
                        "max_path_chars": config.max_path_chars,
                    },
                }
            )
        except UserRuleError:
            raise
        except Exception:
            raise UserRuleError("user_rule.detector_error") from None
        return hmac.new(
            self._fingerprint_key,
            _BASE_CONFIG_DOMAIN + payload,
            hashlib.sha256,
        ).hexdigest()

    def detector_for(
        self,
        user_id: str,
        safety_config: "SafetyConfig",
    ) -> "SensitiveDetector":
        """Build or reuse a detector bound to one user and one revision snapshot."""

        from memoryhub.config import SafetyConfig
        from memoryhub.core.safety.detector import SensitiveDetector

        if not isinstance(safety_config, SafetyConfig):
            raise UserRuleError("user_rule.detector_error")
        user_ref = self._user_ref(user_id)
        overlay = self.compile_overlay(user_id)
        base_digest = self._base_config_digest(safety_config)
        cache_key = (user_ref, base_digest, overlay.snapshot_digest)
        with self._cache_lock:
            cached = self._detector_cache.get(cache_key)
            if cached is not None:
                self._detector_cache.move_to_end(cache_key)
                return cached

        try:
            if not overlay.rules:
                detector = SensitiveDetector.from_config(safety_config)
            else:
                from memoryhub.core.safety.detector import SafetyRuleOverlay

                detector = SensitiveDetector(
                    rules=safety_config.rules,
                    rule_snapshot=safety_config.rule_snapshot,
                    rule_overlay=SafetyRuleOverlay(
                        rules=overlay.rules,
                        keyed_digest=overlay.snapshot_digest,
                        revision=f"user-{overlay.snapshot_digest[:16]}",
                    ),
                    rule_set_id=safety_config.rule_set_id,
                    rule_set_version=safety_config.rule_set_version,
                    rule_set_digest=safety_config.rule_set_digest,
                    policy=safety_config.policy,
                    auto_mask=safety_config.auto_mask,
                    reject_on_detect=safety_config.reject_on_detect,
                    max_depth=safety_config.max_depth,
                    max_field_chars=safety_config.max_field_chars,
                    max_scan_bytes=safety_config.max_scan_bytes,
                    max_scanned_fields=safety_config.max_scanned_fields,
                    max_candidates=safety_config.max_candidates,
                    max_findings=safety_config.max_findings,
                    max_path_chars=safety_config.max_path_chars,
                )
        except Exception:
            raise UserRuleError("user_rule.detector_error") from None

        with self._cache_lock:
            # Only the newest revision/config detector for a user remains cached.
            stale = [
                key
                for key in self._detector_cache
                if key[0] == user_ref and key != cache_key
            ]
            for key in stale:
                self._detector_cache.pop(key, None)
            self._detector_cache[cache_key] = detector
            self._detector_cache.move_to_end(cache_key)
            while len(self._detector_cache) > self._detector_cache_size:
                self._detector_cache.popitem(last=False)
        return detector

    def detector_for_event(
        self,
        event: MemoryEvent,
        safety_config: "SafetyConfig",
    ) -> "SensitiveDetector":
        if not isinstance(event, MemoryEvent) or not event.user_id:
            raise UserRuleError("user_rule.invalid_user_id")
        return self.detector_for(event.user_id, safety_config)

    def detector_provider(
        self,
        safety_config: "SafetyConfig",
    ) -> Callable[[MemoryEvent], "SensitiveDetector"]:
        """Return a side-effect-free adapter suitable for ``SafetyWriteGate``."""

        def provide(event: MemoryEvent) -> "SensitiveDetector":
            return self.detector_for_event(event, safety_config)

        return provide

    def close(self) -> None:
        close = getattr(self._repository, "close", None)
        if callable(close):
            close()
        with self._cache_lock:
            self._detector_cache.clear()


def build_user_rule_service(
    database_path: str | Path,
    master_key: bytes,
    *,
    key_id: str = "default",
    max_rules_per_user: int = _DEFAULT_MAX_RULES_PER_USER,
    max_matcher_chars: int = _DEFAULT_MAX_MATCHER_CHARS,
    allow_advanced_regex: bool = False,
    detector_cache_size: int = _DEFAULT_DETECTOR_CACHE_SIZE,
    now_factory: Callable[[], datetime] | None = None,
) -> UserRuleService:
    """Explicit factory; importing this module never creates files or a database."""

    return UserRuleService.with_sqlite(
        database_path,
        master_key=master_key,
        key_id=key_id,
        max_rules_per_user=max_rules_per_user,
        max_matcher_chars=max_matcher_chars,
        allow_advanced_regex=allow_advanced_regex,
        detector_cache_size=detector_cache_size,
        now_factory=now_factory,
    )


__all__ = [
    "InMemoryUserRuleRepository",
    "SQLiteUserRuleRepository",
    "UserRuleEffect",
    "UserRuleError",
    "UserRuleKind",
    "UserRuleOverlay",
    "UserRuleRepository",
    "UserRuleService",
    "UserRuleView",
    "build_user_rule_service",
]
