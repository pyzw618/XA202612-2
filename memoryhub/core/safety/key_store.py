"""Local lifecycle management for MemoryHub safety keys.

The safety gate needs stable device-local keys, but a standalone deployment may
not have a KMS or secret-management platform.  This module provides a secure
local default: on first startup it creates one owner-only key file next to the
MemoryHub database and reuses it for every subsequent startup.  Explicit
environment variables remain the highest-priority source.

The module never rotates, replaces, or repairs keys implicitly.  If protected
data already exists and the corresponding key is unavailable, startup fails
closed with a stable error code instead of generating incompatible material.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import secrets
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from memoryhub.config import AppConfig

_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 8 * 1024
_KEY_NAMES = ("audit_hmac", "quarantine", "user_rule")


class SafetyKeyStoreError(RuntimeError):
    """Fail-closed key-store error containing only a stable, non-secret code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SafetyKeyResolution:
    """Resolved key material plus a safe, non-secret startup projection."""

    key_file: Path
    created: bool
    sources: tuple[tuple[str, str], ...]
    _keys: tuple[tuple[str, bytes], ...] = field(repr=False)

    def key(self, name: str) -> bytes:
        """Return one in-process key without copying it into the environment."""
        for candidate, value in self._keys:
            if candidate == name:
                return value
        raise SafetyKeyStoreError("key_store.key_unavailable")


def _decode_key(encoded: str) -> bytes:
    try:
        value = base64.b64decode(
            encoded.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
    except (UnicodeError, ValueError, binascii.Error):
        raise SafetyKeyStoreError("key_store.invalid_key") from None
    if len(value) != 32:
        raise SafetyKeyStoreError("key_store.invalid_key")
    return value


def _encode_new_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _reject_symlink(path: Path) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError:
        raise SafetyKeyStoreError("key_store.path_unavailable") from None
    is_junction = getattr(path, "is_junction", None)
    if stat.S_ISLNK(info.st_mode) or (callable(is_junction) and is_junction()):
        raise SafetyKeyStoreError("key_store.unsafe_path")


def _reject_symlink_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if os.path.lexists(current):
            _reject_symlink(current)


def _ensure_private_directory(directory: Path) -> None:
    _reject_symlink_ancestors(directory.parent)
    try:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    except OSError:
        raise SafetyKeyStoreError("key_store.directory_unavailable") from None
    _reject_symlink_ancestors(directory)
    try:
        info = os.lstat(directory)
        if not stat.S_ISDIR(info.st_mode):
            raise SafetyKeyStoreError("key_store.unsafe_path")
        if os.name != "nt":
            os.chmod(directory, 0o700)
            if stat.S_IMODE(os.stat(directory).st_mode) & 0o077:
                raise SafetyKeyStoreError("key_store.permission_failed")
    except SafetyKeyStoreError:
        raise
    except OSError:
        raise SafetyKeyStoreError("key_store.permission_failed") from None


def _secure_regular_file(path: Path) -> None:
    _reject_symlink(path)
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        raise SafetyKeyStoreError("key_store.file_unavailable") from None
    if not stat.S_ISREG(info.st_mode):
        raise SafetyKeyStoreError("key_store.unsafe_path")
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
            if stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode) & 0o077:
                raise SafetyKeyStoreError("key_store.permission_failed")
        except SafetyKeyStoreError:
            raise
        except OSError:
            raise SafetyKeyStoreError("key_store.permission_failed") from None


@contextmanager
def _exclusive_file_lock(directory: Path) -> Iterator[None]:
    """Serialize first-use creation across processes on POSIX and Windows."""

    lock_path = directory / ".safety-keys.lock"
    _reject_symlink(lock_path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError:
        raise SafetyKeyStoreError("key_store.lock_unavailable") from None
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
                os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        yield
    except SafetyKeyStoreError:
        raise
    except OSError:
        raise SafetyKeyStoreError("key_store.lock_unavailable") from None
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _read_key_file(path: Path) -> dict[str, str]:
    _secure_regular_file(path)
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_FILE_BYTES + 1)
    except OSError:
        raise SafetyKeyStoreError("key_store.file_unavailable") from None
    if len(raw) > _MAX_FILE_BYTES:
        raise SafetyKeyStoreError("key_store.invalid_file")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise SafetyKeyStoreError("key_store.invalid_file") from None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "keys"}
        or payload.get("schema_version") != _SCHEMA_VERSION
        or not isinstance(payload.get("keys"), dict)
    ):
        raise SafetyKeyStoreError("key_store.invalid_file")
    keys = payload["keys"]
    if not keys or not set(keys).issubset(_KEY_NAMES):
        raise SafetyKeyStoreError("key_store.invalid_file")
    normalized: dict[str, str] = {}
    for name, encoded in keys.items():
        if not isinstance(encoded, str):
            raise SafetyKeyStoreError("key_store.invalid_file")
        try:
            _decode_key(encoded)
        except SafetyKeyStoreError:
            raise SafetyKeyStoreError("key_store.invalid_file") from None
        normalized[name] = encoded
    return normalized


def _read_legacy_env_file(
    config: "AppConfig",
    env_names: dict[str, str],
) -> dict[str, str]:
    """Read the former standalone ``safety.env`` format without shell evaluation."""

    settings = config.safety.key_store
    if not settings.import_legacy_env or not settings.legacy_env_file.strip():
        return {}
    path = Path(settings.legacy_env_file).expanduser().absolute()
    if not os.path.lexists(path):
        return {}
    _reject_symlink_ancestors(path)
    try:
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise SafetyKeyStoreError("key_store.legacy_env_unsafe")
        if os.name != "nt":
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise SafetyKeyStoreError("key_store.legacy_env_unsafe")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_FILE_BYTES + 1)
    except SafetyKeyStoreError:
        raise
    except OSError:
        raise SafetyKeyStoreError("key_store.legacy_env_unavailable") from None
    if len(raw) > _MAX_FILE_BYTES:
        raise SafetyKeyStoreError("key_store.legacy_env_invalid")
    allowed = {value: name for name, value in env_names.items()}
    parsed: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        raise SafetyKeyStoreError("key_store.legacy_env_invalid") from None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            raise SafetyKeyStoreError("key_store.legacy_env_invalid")
        env_name, encoded = stripped.split("=", 1)
        env_name = env_name.strip()
        encoded = encoded.strip()
        if len(encoded) >= 2 and encoded[0] == encoded[-1] and encoded[0] in "'\"":
            encoded = encoded[1:-1]
        name = allowed.get(env_name)
        if name is None or name in parsed:
            raise SafetyKeyStoreError("key_store.legacy_env_invalid")
        try:
            _decode_key(encoded)
        except SafetyKeyStoreError:
            raise SafetyKeyStoreError("key_store.legacy_env_invalid") from None
        parsed[name] = encoded
    return parsed


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise SafetyKeyStoreError("key_store.write_failed") from None


def _write_key_file(path: Path, keys: dict[str, str], *, replace: bool) -> None:
    raw = (
        json.dumps(
            {"schema_version": _SCHEMA_VERSION, "keys": keys},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_BINARY", 0)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    fd: int | None = None
    try:
        fd = os.open(temporary, flags, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise OSError
            offset += written
        os.fsync(fd)
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        os.close(fd)
        fd = None
        if replace:
            _reject_symlink(path)
            os.replace(temporary, path)
        else:
            _reject_symlink(path)
            os.link(temporary, path, follow_symlinks=False)
            temporary.unlink()
        _secure_regular_file(path)
        _fsync_directory(path.parent)
    except Exception as exc:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(exc, SafetyKeyStoreError):
            raise
        raise SafetyKeyStoreError("key_store.write_failed") from None


def _configured_key_file(config: "AppConfig") -> Path:
    override = os.environ.get("MEMORYHUB_SAFETY_KEY_FILE", "").strip()
    configured = override or config.safety.key_store.path.strip()
    db_path = os.fspath(config.storage.db_path)
    if configured:
        candidate = Path(configured).expanduser()
        if override and not candidate.is_absolute():
            raise SafetyKeyStoreError("key_store.path_must_be_absolute")
        if not candidate.is_absolute():
            if db_path == ":memory:":
                raise SafetyKeyStoreError("key_store.path_must_be_absolute")
            candidate = Path(db_path).expanduser().absolute().parent / candidate
        return candidate.absolute()
    if db_path == ":memory:":
        raise SafetyKeyStoreError("key_store.path_unavailable")
    return Path(db_path).expanduser().absolute().parent / "security" / "safety-keys.json"


def _resolve_safety_directory(
    configured: str,
    *,
    database_directory: Path,
    default_leaf: str,
) -> str:
    candidate = Path(configured).expanduser()
    if candidate.is_absolute():
        return str(candidate.absolute())
    # Historical defaults included a leading ``data`` component.  The database
    # directory is now the stable data root, so avoid producing ``data/data``.
    if candidate.as_posix() == f"data/{default_leaf}":
        candidate = Path(default_leaf)
    return str((database_directory / candidate).absolute())


def resolve_safety_storage_paths(config: "AppConfig") -> None:
    """Resolve relative audit/quarantine paths against the database data root."""

    database_path = os.fspath(config.storage.db_path)
    if database_path == ":memory:":
        return
    database_directory = Path(database_path).expanduser().absolute().parent
    audit_directory = _resolve_safety_directory(
        config.safety.audit.directory,
        database_directory=database_directory,
        default_leaf="safety-audit",
    )
    quarantine_directory = _resolve_safety_directory(
        config.safety.quarantine.directory,
        database_directory=database_directory,
        default_leaf="review-quarantine",
    )
    config.safety.audit = replace(config.safety.audit, directory=audit_directory)
    config.safety.quarantine = replace(
        config.safety.quarantine,
        directory=quarantine_directory,
    )


def _audit_data_exists(config: "AppConfig") -> bool:
    directory = Path(config.safety.audit.directory).expanduser().absolute()
    if not directory.is_dir():
        return False
    try:
        return any(
            path.name in {".safety-audit-head.json", ".safety-audit-anchor.json"}
            or (path.name.startswith("safety-audit-") and path.suffix == ".jsonl")
            for path in directory.iterdir()
            if path.is_file()
        )
    except OSError:
        raise SafetyKeyStoreError("key_store.protected_data_unavailable") from None


def _quarantine_data_exists(config: "AppConfig") -> bool:
    directory = Path(config.safety.quarantine.directory).expanduser().absolute()
    if not directory.is_dir():
        return False
    try:
        return any(
            path.is_file()
            and path.name.startswith("review_")
            and path.suffix == ".json"
            for path in directory.iterdir()
        )
    except OSError:
        raise SafetyKeyStoreError("key_store.protected_data_unavailable") from None


def _user_rule_data_exists(config: "AppConfig") -> bool:
    db_text = os.fspath(config.storage.db_path)
    if db_text == ":memory:":
        return False
    database = Path(db_text).expanduser().absolute()
    if not database.is_file():
        return False
    try:
        uri = database.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
            row = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='user_sensitive_rules'"
            ).fetchone()
            if row is None:
                return False
            return connection.execute(
                "SELECT 1 FROM user_sensitive_rules LIMIT 1"
            ).fetchone() is not None
    except (OSError, sqlite3.Error):
        raise SafetyKeyStoreError("key_store.protected_data_unavailable") from None


def _protected_data_exists(name: str, config: "AppConfig") -> bool:
    if name == "audit_hmac":
        return _audit_data_exists(config)
    if name == "quarantine":
        return _quarantine_data_exists(config)
    return _user_rule_data_exists(config)


def provision_safety_keys(config: "AppConfig") -> SafetyKeyResolution:
    """Resolve and persist all safety keys required by ``config``.

    Environment variables have runtime precedence.  With the default
    ``persist_external=True``, valid externally supplied values are imported
    into the owner-only local file to make an existing standalone deployment
    self-sufficient on later restarts.
    """

    resolve_safety_storage_paths(config)
    key_file = _configured_key_file(config)
    _ensure_private_directory(key_file.parent)
    env_names = {
        "audit_hmac": config.safety.audit.hmac_key_env,
        "quarantine": config.safety.quarantine.encryption_key_env,
        "user_rule": config.safety.user_rules.encryption_key_env,
    }
    if len(set(env_names.values())) != len(env_names):
        raise SafetyKeyStoreError("key_store.environment_reuse")

    with _exclusive_file_lock(key_file.parent):
        existed = key_file.exists()
        local_keys = _read_key_file(key_file) if existed else {}
        needs_legacy = any(
            not os.environ.get(env_names[name], "").strip() and name not in local_keys
            for name in _KEY_NAMES
        )
        legacy_keys = _read_legacy_env_file(config, env_names) if needs_legacy else {}
        effective: dict[str, str] = {}
        sources: dict[str, str] = {}
        changed = False

        for name in _KEY_NAMES:
            env_name = env_names[name]
            external = os.environ.get(env_name, "").strip()
            if external:
                try:
                    _decode_key(external)
                except SafetyKeyStoreError:
                    raise SafetyKeyStoreError(
                        f"key_store.invalid_{name}_key"
                    ) from None
                effective[name] = external
                sources[name] = "environment"
                if config.safety.key_store.persist_external and name not in local_keys:
                    local_keys[name] = external
                    changed = True
                continue

            local = local_keys.get(name)
            if local:
                effective[name] = local
                sources[name] = "local"
                continue

            legacy = legacy_keys.get(name)
            if legacy:
                effective[name] = legacy
                sources[name] = "legacy_env"
                if config.safety.key_store.persist_external:
                    local_keys[name] = legacy
                    changed = True
                continue

            if not config.safety.key_store.auto_generate:
                raise SafetyKeyStoreError(f"key_store.{name}_key_unavailable")
            if _protected_data_exists(name, config):
                raise SafetyKeyStoreError(
                    f"key_store.{name}_key_missing_for_existing_data"
                )
            generated = _encode_new_key()
            local_keys[name] = generated
            effective[name] = generated
            sources[name] = "generated"
            changed = True

        decoded = [_decode_key(effective[name]) for name in _KEY_NAMES]
        if len({value for value in decoded}) != len(decoded):
            raise SafetyKeyStoreError("key_store.key_reuse")

        if changed:
            _write_key_file(key_file, local_keys, replace=existed)
        elif existed:
            _secure_regular_file(key_file)

    return SafetyKeyResolution(
        key_file=key_file,
        created=not existed and key_file.exists(),
        sources=tuple((name, sources[name]) for name in _KEY_NAMES),
        _keys=tuple((name, _decode_key(effective[name])) for name in _KEY_NAMES),
    )


__all__ = [
    "SafetyKeyResolution",
    "SafetyKeyStoreError",
    "provision_safety_keys",
    "resolve_safety_storage_paths",
]
