from __future__ import annotations

import base64

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi import Request
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, StorageConfig
from memoryhub.core.safety.user_rules import (
    InMemoryUserRuleRepository,
    UserRuleService,
)

_USER_HEADER = {"X-MemoryHub-User": "user-a"}
_MATCHER_CANARY = "C++20-private-matcher-canary"


def _service() -> UserRuleService:
    return UserRuleService(
        InMemoryUserRuleRepository(),
        master_key=b"u" * 32,
        allow_advanced_regex=True,
    )


def _identity_from_test_header(request: Request) -> str:
    return request.headers.get("X-MemoryHub-User", "")


def _app(
    *,
    service: UserRuleService | None = None,
    config: AppConfig | None = None,
):
    return create_app(
        config,
        user_rule_service=service,
        user_rule_identity_resolver=_identity_from_test_header,
    )


def _create_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "label": "C++ version",
        "kind": "literal",
        "effect": "mask_match",
        "matcher": _MATCHER_CANARY,
        "case_sensitive": False,
        "enabled": True,
    }
    payload.update(updates)
    return payload


def test_user_rule_crud_is_scoped_versioned_and_write_only() -> None:
    service = _service()
    with TestClient(_app(service=service)) as client:
        created_response = client.post(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
            json=_create_payload(),
        )
        assert created_response.status_code == 201
        created = created_response.json()
        rule_id = created["rule_id"]
        assert created["label"] == "C++ version"
        assert created["case_sensitive"] is False
        assert created["effect"] == "mask_match"
        assert created["revision"] == 1
        assert "matcher" not in created
        assert "matcher_fingerprint" not in created
        assert _MATCHER_CANARY not in created_response.text

        listed = client.get(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
        )
        assert listed.status_code == 200
        assert [item["rule_id"] for item in listed.json()] == [rule_id]
        assert "matcher_fingerprint" not in listed.json()[0]
        assert _MATCHER_CANARY not in listed.text

        other_user = client.get(
            "/api/memory/safety/user-rules",
            headers={"X-MemoryHub-User": "user-b"},
        )
        assert other_user.status_code == 200
        assert other_user.json() == []
        not_owned = client.get(
            f"/api/memory/safety/user-rules/{rule_id}",
            headers={"X-MemoryHub-User": "user-b"},
        )
        assert not_owned.status_code == 404

        updated_response = client.patch(
            f"/api/memory/safety/user-rules/{rule_id}",
            headers=_USER_HEADER,
            json={
                "expected_revision": 1,
                "label": "All C++ versions",
                "effect": "drop_event",
            },
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["label"] == "All C++ versions"
        assert updated["effect"] == "drop_event"
        assert updated["revision"] == 2

        stale = client.patch(
            f"/api/memory/safety/user-rules/{rule_id}",
            headers=_USER_HEADER,
            json={"expected_revision": 1, "enabled": False},
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": {"code": "user_rule.conflict"}}

        deleted = client.delete(
            f"/api/memory/safety/user-rules/{rule_id}",
            headers=_USER_HEADER,
            params={"expected_revision": 2},
        )
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert (
            client.get(
                "/api/memory/safety/user-rules",
                headers=_USER_HEADER,
            ).json()
            == []
        )
        tombstones = client.get(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
            params={"include_deleted": "true"},
        ).json()
        assert tombstones[0]["deleted"] is True
        assert tombstones[0]["revision"] == 3


def test_user_rule_errors_and_validation_never_echo_matcher(caplog) -> None:
    service = _service()
    with TestClient(_app(service=service)) as client:
        invalid_request = client.post(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
            json={
                "kind": "literal",
                "effect": "mask_match",
                "matcher": _MATCHER_CANARY,
            },
        )
        assert invalid_request.status_code == 422
        assert invalid_request.json() == {
            "detail": {"code": "user_rule.invalid_request"}
        }
        assert _MATCHER_CANARY not in invalid_request.text

        unsafe_matcher = f"({_MATCHER_CANARY}+)+"
        unsafe = client.post(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
            json=_create_payload(
                kind="advanced_regex",
                matcher=unsafe_matcher,
            ),
        )
        assert unsafe.status_code == 422
        assert unsafe.json() == {"detail": {"code": "user_rule.unsafe_regex"}}
        assert _MATCHER_CANARY not in unsafe.text
        assert _MATCHER_CANARY not in caplog.text


def test_user_rule_endpoint_requires_caller_identity() -> None:
    with TestClient(_app(service=_service())) as client:
        response = client.get("/api/memory/safety/user-rules")

    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "user_rule.invalid_request"}}


def test_user_rule_endpoint_fails_closed_without_authenticated_identity() -> None:
    with TestClient(create_app(user_rule_service=_service())) as client:
        response = client.get(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "user_rule.identity_unavailable"}}


def test_user_rule_header_must_match_authenticated_identity() -> None:
    app = create_app(
        user_rule_service=_service(),
        user_rule_identity_resolver=lambda _request: "authenticated-user",
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
        )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "user_rule.identity_mismatch"}}


def test_default_app_reports_missing_rule_key_without_creating_database(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MEMORYHUB_USER_RULE_KEY", raising=False)
    database_path = tmp_path / "memoryhub.db"
    config = AppConfig(storage=StorageConfig(db_path=str(database_path)))

    with TestClient(_app(config=config)) as client:
        response = client.get(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
        )

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "user_rule.key_unavailable"}}
    assert not database_path.exists()


def test_default_app_builds_encrypted_sqlite_service_from_base64_key(
    tmp_path,
    monkeypatch,
) -> None:
    key = b"k" * 32
    monkeypatch.setenv(
        "MEMORYHUB_USER_RULE_KEY",
        base64.b64encode(key).decode("ascii"),
    )
    database_path = tmp_path / "memoryhub.db"
    config = AppConfig(storage=StorageConfig(db_path=str(database_path)))

    with TestClient(_app(config=config)) as client:
        response = client.post(
            "/api/memory/safety/user-rules",
            headers=_USER_HEADER,
            json=_create_payload(),
        )

    assert response.status_code == 201
    assert _MATCHER_CANARY not in response.text
    assert database_path.is_file()
    assert _MATCHER_CANARY.encode() not in database_path.read_bytes()
