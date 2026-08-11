from __future__ import annotations

import base64
import json
import os
import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from memoryhub.config import AppConfig, SafetyConfig, StorageConfig
from memoryhub.core.safety.key_store import (
    SafetyKeyStoreError,
    provision_safety_keys,
)

_ENV_NAMES = (
    "MEMORYHUB_AUDIT_HMAC_KEY",
    "MEMORYHUB_QUARANTINE_KEY",
    "MEMORYHUB_USER_RULE_KEY",
    "MEMORYHUB_SAFETY_KEY_FILE",
)


@pytest.fixture(autouse=True)
def isolated_key_environment():
    previous = {name: os.environ.get(name) for name in _ENV_NAMES}
    for name in _ENV_NAMES:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name in _ENV_NAMES:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def _config(tmp_path, **key_store_updates: object) -> AppConfig:
    data = tmp_path / "data"
    key_store = {"legacy_env_file": "", **key_store_updates}
    return AppConfig(
        storage=StorageConfig(
            db_path=str(data / "memoryhub.db"),
            vector_index_path=str(data / "vector-index"),
            evidence_path=str(data / "evidence"),
        ),
        safety=SafetyConfig(
            key_store=key_store,
            audit={"directory": str(data / "safety-audit")},
            quarantine={"directory": str(data / "review-quarantine")},
            user_rules={"enabled": False},
        ),
    )


def _clear_runtime_keys() -> None:
    for name in _ENV_NAMES[:3]:
        os.environ.pop(name, None)


def _resolved_keys(resolution) -> tuple[bytes, ...]:
    return tuple(
        resolution.key(name) for name in ("audit_hmac", "quarantine", "user_rule")
    )


def test_first_start_generates_three_distinct_persistent_keys(tmp_path) -> None:
    resolution = provision_safety_keys(_config(tmp_path))

    expected = tmp_path / "data" / "security" / "safety-keys.json"
    assert resolution.key_file == expected
    assert resolution.created is True
    assert expected.is_file()
    assert len(set(_resolved_keys(resolution))) == 3
    assert all(len(value) == 32 for value in _resolved_keys(resolution))
    payload = json.loads(expected.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert set(payload["keys"]) == {"audit_hmac", "quarantine", "user_rule"}
    assert not any(value in expected.as_posix() for value in payload["keys"].values())
    if os.name != "nt":
        assert stat.S_IMODE(expected.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(expected.stat().st_mode) == 0o600


def test_restart_reuses_exact_local_keys(tmp_path) -> None:
    config = _config(tmp_path)
    first = provision_safety_keys(config)
    first_values = _resolved_keys(first)

    _clear_runtime_keys()
    second = provision_safety_keys(config)

    assert second.key_file == first.key_file
    assert second.created is False
    assert _resolved_keys(second) == first_values
    assert dict(second.sources) == {
        "audit_hmac": "local",
        "quarantine": "local",
        "user_rule": "local",
    }


def test_external_keys_are_imported_for_standalone_migration(tmp_path) -> None:
    external = {
        _ENV_NAMES[0]: base64.b64encode(b"a" * 32).decode("ascii"),
        _ENV_NAMES[1]: base64.b64encode(b"q" * 32).decode("ascii"),
        _ENV_NAMES[2]: base64.b64encode(b"u" * 32).decode("ascii"),
    }
    os.environ.update(external)
    config = _config(tmp_path)

    first = provision_safety_keys(config)
    assert dict(first.sources) == {
        "audit_hmac": "environment",
        "quarantine": "environment",
        "user_rule": "environment",
    }

    _clear_runtime_keys()
    second = provision_safety_keys(config)
    assert _resolved_keys(second) == tuple(
        base64.b64decode(external[name]) for name in _ENV_NAMES[:3]
    )
    assert set(dict(second.sources).values()) == {"local"}


def test_external_keys_can_remain_environment_only(tmp_path) -> None:
    for index, name in enumerate(_ENV_NAMES[:3], start=1):
        os.environ[name] = base64.b64encode(bytes([index]) * 32).decode("ascii")

    resolution = provision_safety_keys(
        _config(tmp_path, persist_external=False)
    )

    assert resolution.created is False
    assert not resolution.key_file.exists()
    assert set(dict(resolution.sources).values()) == {"environment"}


def test_legacy_safety_env_is_safely_imported_for_upgrade(tmp_path) -> None:
    legacy = tmp_path / "legacy" / "safety.env"
    legacy.parent.mkdir()
    expected = {
        _ENV_NAMES[0]: base64.b64encode(b"a" * 32).decode("ascii"),
        _ENV_NAMES[1]: base64.b64encode(b"q" * 32).decode("ascii"),
        _ENV_NAMES[2]: base64.b64encode(b"u" * 32).decode("ascii"),
    }
    legacy.write_text(
        "# former standalone deployment\n"
        + "\n".join(f"export {name}='{value}'" for name, value in expected.items())
        + "\n",
        encoding="utf-8",
    )
    if os.name != "nt":
        legacy.chmod(0o600)
    config = _config(tmp_path, legacy_env_file=str(legacy))
    audit_directory = tmp_path / "data" / "safety-audit"
    audit_directory.mkdir(parents=True)
    (audit_directory / ".safety-audit-head.json").write_text("{}\n", encoding="utf-8")

    resolution = provision_safety_keys(config)

    assert set(dict(resolution.sources).values()) == {"legacy_env"}
    assert _resolved_keys(resolution) == tuple(
        base64.b64decode(expected[name]) for name in _ENV_NAMES[:3]
    )
    assert resolution.key_file.is_file()

    config.safety.key_store = type(config.safety.key_store)(
        legacy_env_file="",
    )
    second = provision_safety_keys(config)
    assert set(dict(second.sources).values()) == {"local"}


def test_invalid_external_key_fails_without_fallback(tmp_path) -> None:
    os.environ[_ENV_NAMES[0]] = "not-a-valid-key"

    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.invalid_audit_hmac_key$",
    ):
        provision_safety_keys(_config(tmp_path))

    assert not (tmp_path / "data" / "security" / "safety-keys.json").exists()


def test_missing_audit_key_is_not_regenerated_over_existing_chain(tmp_path) -> None:
    config = _config(tmp_path)
    audit_directory = tmp_path / "data" / "safety-audit"
    audit_directory.mkdir(parents=True)
    (audit_directory / ".safety-audit-head.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.audit_hmac_key_missing_for_existing_data$",
    ):
        provision_safety_keys(config)

    assert not (tmp_path / "data" / "security" / "safety-keys.json").exists()


def test_missing_quarantine_key_is_not_regenerated_over_existing_records(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    directory = tmp_path / "data" / "review-quarantine"
    directory.mkdir(parents=True)
    (directory / ("review_" + "a" * 32 + ".json")).write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.quarantine_key_missing_for_existing_data$",
    ):
        provision_safety_keys(config)


def test_missing_user_rule_key_is_not_regenerated_over_encrypted_rows(
    tmp_path,
) -> None:
    config = _config(tmp_path)
    database = tmp_path / "data" / "memoryhub.db"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE user_sensitive_rules (value TEXT)")
        connection.execute("INSERT INTO user_sensitive_rules VALUES ('encrypted')")

    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.user_rule_key_missing_for_existing_data$",
    ):
        provision_safety_keys(config)


def test_reused_key_material_is_rejected(tmp_path) -> None:
    reused = base64.b64encode(b"x" * 32).decode("ascii")
    os.environ[_ENV_NAMES[0]] = reused
    os.environ[_ENV_NAMES[1]] = reused
    os.environ[_ENV_NAMES[2]] = base64.b64encode(b"u" * 32).decode("ascii")

    with pytest.raises(SafetyKeyStoreError, match=r"^key_store\.key_reuse$"):
        provision_safety_keys(_config(tmp_path))


def test_corrupt_key_file_is_never_overwritten(tmp_path) -> None:
    config = _config(tmp_path)
    key_file = tmp_path / "data" / "security" / "safety-keys.json"
    key_file.parent.mkdir(parents=True)
    key_file.write_text("corrupt-canary", encoding="utf-8")

    with pytest.raises(SafetyKeyStoreError, match=r"^key_store\.invalid_file$"):
        provision_safety_keys(config)

    assert key_file.read_text(encoding="utf-8") == "corrupt-canary"


def test_relative_configured_path_is_based_on_database_directory(tmp_path) -> None:
    resolution = provision_safety_keys(
        _config(tmp_path, path="private/keys.json")
    )

    assert resolution.key_file == tmp_path / "data" / "private" / "keys.json"


def test_default_relative_safety_directories_follow_database_directory(tmp_path) -> None:
    database = tmp_path / "custom-data" / "memoryhub.db"
    config = AppConfig(storage=StorageConfig(db_path=str(database)))

    provision_safety_keys(config)

    assert Path(config.safety.audit.directory) == database.parent / "safety-audit"
    assert Path(config.safety.quarantine.directory) == (
        database.parent / "review-quarantine"
    )


def test_environment_path_override_must_be_absolute(tmp_path) -> None:
    os.environ["MEMORYHUB_SAFETY_KEY_FILE"] = "relative/keys.json"

    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.path_must_be_absolute$",
    ):
        provision_safety_keys(_config(tmp_path))


def test_concurrent_first_start_resolves_one_key_set(tmp_path) -> None:
    config = _config(tmp_path)

    def provision() -> tuple[bytes, ...]:
        return _resolved_keys(provision_safety_keys(config))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: provision(), range(4)))

    assert all(result == results[0] for result in results)
    assert (tmp_path / "data" / "security" / "safety-keys.json").is_file()


def test_auto_generation_can_be_disabled_for_managed_deployments(tmp_path) -> None:
    with pytest.raises(
        SafetyKeyStoreError,
        match=r"^key_store\.audit_hmac_key_unavailable$",
    ):
        provision_safety_keys(_config(tmp_path, auto_generate=False))


def test_rest_startup_uses_generated_keys_and_restart_uses_local_keys(tmp_path) -> None:
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from memoryhub.app import create_app
    from memoryhub.config import EmbeddingConfig

    config = _config(tmp_path)
    config.embedding = EmbeddingConfig(provider="mock", dimension=64)

    first_app = create_app(config)
    with TestClient(first_app):
        assert first_app.state.safety_gate is not None
        assert dict(first_app.state.safety_key_sources) == {
            "audit_hmac": "generated",
            "quarantine": "generated",
            "user_rule": "generated",
        }

    second_app = create_app(config)
    with TestClient(second_app):
        assert second_app.state.safety_gate is not None
        assert dict(second_app.state.safety_key_sources) == {
            "audit_hmac": "local",
            "quarantine": "local",
            "user_rule": "local",
        }
