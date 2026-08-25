"""Fixed replayable vNext demo runner.

This script reads the demo fixtures in ``examples/vnext_demo/`` and replays the
core vNext scenarios through an in-memory FastAPI test client.  It produces
redacted output JSON files in ``examples/vnext_demo/output/``.

Usage::

    .\\.venv\\Scripts\\python.exe examples/vnext_demo/run_demo.py --scenario all
"""

from __future__ import annotations

import argparse
import json
import sys
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

ROOT = Path(__file__).parents[2]
DEMO_DIR = Path(__file__).parent
OUTPUT_DIR = DEMO_DIR / "output"


def _load_fixture(name: str) -> list[dict[str, Any]]:
    with (DEMO_DIR / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _db() -> Database:
    db_path = OUTPUT_DIR / "demo.db"
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


def _demo_event(raw: dict[str, Any]) -> dict[str, Any]:
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
    if response.status_code >= 400:
        raise SystemExit(f"write failed: {response.status_code} {response.text}")
    return response.json()


def _redacted_summary(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": body.get("request_id"),
        "trace_id": body.get("trace_id"),
        "event_count": len(body.get("event_ids", [])),
        "working_state_version": body.get("working_state_version"),
        "episode_id": body.get("episode_id"),
        "checkpoint_created": body.get("checkpoint_created"),
        "memory_count": len(body.get("memory_ids", [])),
        "candidate_count": len(body.get("candidate_ids", [])),
        "degraded": body.get("degraded"),
    }


def scenario_formation(client: TestClient) -> dict[str, Any]:
    """E2E-P0-01: user starts a report with constraints."""
    raw = _load_fixture("event_start_report.json")[0]
    body = _write_events(client, "req-demo-formation", [_demo_event(raw)])
    return _redacted_summary(body)


def scenario_docx_once(client: TestClient) -> dict[str, Any]:
    """E2E-P1-01: a single DOCX instruction does not immediately promote."""
    raw = _load_fixture("event_use_docx.json")[0]
    body = _write_events(client, "req-demo-docx-once", [_demo_event(raw)])
    return _redacted_summary(body)


def scenario_idempotency(client: TestClient) -> dict[str, Any]:
    """E2E-P0-07: repeated event keeps the same durable IDs."""
    raw = _load_fixture("event_start_report.json")[0]
    event = _demo_event(raw)
    body1 = _write_events(client, "req-demo-idem", [event])
    body2 = _write_events(client, "req-demo-idem", [event])
    return {
        "first": _redacted_summary(body1),
        "second": _redacted_summary(body2),
        "same_event_ids": body1["event_ids"] == body2["event_ids"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the vNext demo scenarios.")
    parser.add_argument(
        "--scenario",
        choices=["formation", "docx", "idempotency", "all"],
        default="all",
    )
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = _db()
    service = _canonical_service(db)
    client = TestClient(_test_app(service))

    scenarios: dict[str, dict[str, Any]] = {}
    if args.scenario in {"formation", "all"}:
        scenarios["formation"] = scenario_formation(client)
    if args.scenario in {"docx", "all"}:
        scenarios["docx_once"] = scenario_docx_once(client)
    if args.scenario in {"idempotency", "all"}:
        scenarios["idempotency"] = scenario_idempotency(client)

    report = {
        "schema_version": "vnext-demo/1.0",
        "scenario": args.scenario,
        "redacted": True,
        "scenarios": scenarios,
    }
    out_path = output_dir / "demo_report.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"demo report written to {out_path}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
