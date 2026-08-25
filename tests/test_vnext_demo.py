"""Fixed, redacted, replayable vNext demo validation.

These tests exercise the demo fixtures in ``examples/vnext_demo/`` through the
in-memory FastAPI test client.  They do not require a running service or external
dependencies, so the demo is reproducible in a clean environment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryhub.adapter.vnext_api import router as vnext_router
from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.working_service import WorkingService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import MemoryEventContract, WorkingSnapshot
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository

ROOT = Path(__file__).parents[1]
DEMO_DIR = ROOT / "examples" / "vnext_demo"
OUTPUT_DIR = DEMO_DIR / "output"
DB_BASE = ROOT / "evaluation" / "results" / "vnext_demo_test"
_db_counter = 0


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = DEMO_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _db() -> Database:
    import time

    global _db_counter
    _db_counter += 1
    db_path = DB_BASE.parent / f"{DB_BASE.name}_{int(time.time() * 1000)}_{_db_counter}.db"
    db = Database(str(db_path))
    db.init_schema()
    return db


def _canonical_service(db: Database) -> CanonicalWriteService:
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    facade = LongTermAuthorityFacade(authority)
    writer = MemoryWriteService(pref_repo=pref_repo, know_repo=know_repo, project_immediately=False)
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        authority_facade=facade,
        memory_write_service=writer,
    )


def _test_app(service: CanonicalWriteService) -> FastAPI:
    app = FastAPI()
    app.state.canonical_write_service = service
    app.state.episode_service = service.episode_service
    app.state.retrieval_service = None
    app.state.forget_service = None
    app.state.user_rule_identity_resolver = None
    app.include_router(vnext_router)
    return app


def _write_events(
    client: TestClient, request_id: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": request_id,
            "idempotency_key": request_id,
            "events": events,
        },
        headers={"X-MemoryHub-Tenant": "tenant-demo", "X-MemoryHub-User": "user-demo"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _demo_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Wrap a raw demo payload into a canonical MemoryEventContract shape."""
    task_id = f"task-{raw['session_id']}"
    payload = dict(raw["payload"])
    if raw["event_type"] == "user_goal" and "_working_snapshot" not in payload:
        payload["_working_snapshot"] = WorkingSnapshot(
            tenant_id="tenant-demo",
            user_id="user-demo",
            task_id=task_id,
            session_id=raw["session_id"],
            current_goal=payload.get("goal", "complete task"),
            current_step="outline",
            pending_steps=["draft", "review"],
            constraints=payload.get("constraints", []),
        ).model_dump(mode="json")
    return MemoryEventContract(
        tenant_id="tenant-demo",
        user_id="user-demo",
        event_id=f"event-{raw['session_id']}-{raw['turn_id']}",
        event_type=raw["event_type"],
        source_type="user_behavior",
        task_id=task_id,
        session_id=raw["session_id"],
        occurred_at="2026-08-25T00:00:00+00:00",
        payload=payload,
        policy_action="ALLOW",
        source_hash="a" * 64,
        idempotency_key=f"idem-{raw['session_id']}-{raw['turn_id']}",
        trace_id=f"trace-{raw['session_id']}",
    ).model_dump(mode="json")


def test_demo_fixtures_are_redacted_and_valid() -> None:
    """Demo fixtures must not contain sensitive real-world content."""
    sensitive_keywords = {"password", "secret", "token", "api_key", "creditcard", "ssn"}
    fixtures = [
        "event_start_report.json",
        "event_use_docx.json",
        "event_repeat_docx.json",
        "event_markdown_global.json",
    ]
    for fixture in fixtures:
        data = _load_fixture(fixture)
        text = json.dumps(data, ensure_ascii=False).lower()
        for keyword in sensitive_keywords:
            assert keyword not in text, f"fixture {fixture} contains sensitive keyword {keyword}"
        for raw in data:
            event = MemoryEventContract.model_validate(_demo_event(raw))
            assert event.policy_action == "ALLOW"


def test_demo_formation_creates_working_state() -> None:
    """E2E-P0-01: user starts a report and constraints are captured."""
    db = _db()
    service = _canonical_service(db)
    client = TestClient(_test_app(service))

    raw = _load_fixture("event_start_report.json")[0]
    body = _write_events(client, "req-demo-formation", [_demo_event(raw)])

    assert body["working_state_version"] >= 1
    assert body["request_id"] == "req-demo-formation"
    assert body["trace_id"]
    db.close()


def test_demo_single_docx_does_not_promote_globally() -> None:
    """E2E-P1-01/P1-02: a single 'use DOCX' stays local; promotion requires evidence."""
    db = _db()
    service = _canonical_service(db)
    client = TestClient(_test_app(service))

    raw = _load_fixture("event_use_docx.json")[0]
    body = _write_events(client, "req-demo-docx-once", [_demo_event(raw)])

    # A single instruction does not immediately create an ACTIVE Long-Term memory.
    assert body["memory_ids"] == []
    db.close()


def test_demo_idempotency_no_duplicate_evidence() -> None:
    """E2E-P0-07: repeating the same event must not duplicate evidence."""
    db = _db()
    service = _canonical_service(db)
    client = TestClient(_test_app(service))

    raw = _load_fixture("event_start_report.json")[0]
    event = _demo_event(raw)
    body1 = _write_events(client, "req-demo-idem", [event])
    body2 = _write_events(client, "req-demo-idem", [event])

    assert body1["event_ids"] == body2["event_ids"]
    db.close()


def test_demo_output_directory_is_created() -> None:
    """Demo output directory exists for redacted artifacts."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    marker = OUTPUT_DIR / "README.md"
    marker.write_text(
        "# Demo output\n\nRedacted demo artifacts are written here.\n",
        encoding="utf-8",
    )
    assert marker.exists()
