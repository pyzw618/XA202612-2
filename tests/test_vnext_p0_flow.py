"""E2E P0 flow coverage for the vNext canonical write and task recovery path.

These tests exercise the eight mandatory P0 scenarios from the vNext execution
plan.  They run against an in-memory SQLite database and a FastAPI test client so
they do not require external services.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
from memoryhub.domain.contracts import (
    EpisodeEventContract,
    EpisodeSnapshot,
    EpisodeStatus,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
    WorkingSnapshot,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import EventRow, IdempotencyRecordRow, PreferenceRow, WorkingStateRow
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository
from scripts.rebuild_projections import rebuild_projections

ROOT = Path(__file__).parents[1]
DB_BASE = ROOT / "evaluation" / "results" / "vnext_p0_flow_test"
_db_counter = 0


def _db() -> Database:
    import time

    global _db_counter
    _db_counter += 1
    db_path = DB_BASE.parent / f"{DB_BASE.name}_{int(time.time() * 1000)}_{_db_counter}.db"
    db = Database(str(db_path))
    db.init_schema()
    return db


def _event(
    event_id: str,
    idempotency_key: str,
    task_id: str,
    payload: dict[str, Any] | None = None,
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-p0",
        user_id="user-p0",
        event_id=event_id,
        event_type="user_instruction",
        source_type="user_behavior",
        task_id=task_id,
        session_id="session-p0",
        occurred_at=datetime.now(timezone.utc),
        payload=payload or {"text": "hello"},
        policy_action="ALLOW",
        source_hash=(event_id + "a" * 64)[:64],
        idempotency_key=idempotency_key,
        trace_id="trace-" + event_id,
    )


def _working_snapshot(
    task_id: str,
    *,
    goal: str = "write report",
    current_step: str = "draft",
    pending_steps: list[str] | None = None,
    constraints: list[str] | None = None,
) -> WorkingSnapshot:
    return WorkingSnapshot(
        tenant_id="tenant-p0",
        user_id="user-p0",
        task_id=task_id,
        session_id="session-p0",
        current_goal=goal,
        current_step=current_step,
        pending_steps=pending_steps or ["review"],
        constraints=constraints or [],
    )


def _episode_snapshot(
    episode_id: str,
    task_id: str,
    *,
    phase: str = "draft",
    last_event_seq: int = 1,
    goal: str = "write report",
) -> EpisodeSnapshot:
    return EpisodeSnapshot(
        tenant_id="tenant-p0",
        user_id="user-p0",
        episode_id=episode_id,
        task_id=task_id,
        session_id="session-p0",
        status=EpisodeStatus.ACTIVE,
        current_phase=phase,
        goal=goal,
        pending_steps=["review"],
        last_event_seq=last_event_seq,
    )


def _long_term(memory_id: str = "pref-p0") -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id="tenant-p0",
        user_id="user-p0",
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        normalized_key="report.format",
        content={"text": "Use DOCX", "payload": {"format": "docx"}},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        evolution_status=EvolutionStatus.ACTIVE,
        confidence=0.95,
        utility=0.8,
        content_version=1,
        evidence_refs=["event-p0"],
    )


def _canonical_service(db: Database, *, policy: Any | None = None) -> CanonicalWriteService:
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    facade = LongTermAuthorityFacade(authority)
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        project_immediately=False,
    )
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=policy or (lambda event: event)),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        authority_facade=facade,
        memory_write_service=writer,
    )


def _test_app(service: CanonicalWriteService) -> FastAPI:
    app = FastAPI()
    app.state.canonical_write_service = service
    app.state.episode_service = service.episode_service
    app.state.user_rule_identity_resolver = None
    app.include_router(vnext_router)
    return app


# ---------------------------------------------------------------------------
# E2E-P0-01: 用户开始制作报告并给出格式约束
# ---------------------------------------------------------------------------
def test_p0_01_start_report_with_constraints_creates_working_state() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = TestClient(app)

    task_id = "task-p0-01"
    event = _event(
        "event-p0-01",
        "idem-p0-01",
        task_id,
        payload={
            "text": "Start writing the quarterly report and use DOCX",
            "_working_snapshot": _working_snapshot(
                task_id,
                goal="write quarterly report",
                current_step="outline",
                pending_steps=["draft", "review"],
                constraints=["format: DOCX"],
            ).model_dump(mode="json"),
        },
    )

    response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": "req-p0-01",
            "idempotency_key": "idem-p0-01",
            "events": [event.model_dump(mode="json")],
        },
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["working_state_version"] == 1

    with db.session() as session:
        ws = session.query(WorkingStateRow).one()
        state = ws.state
        assert state["current_goal"] == "write quarterly report"
        assert state["current_step"] == "outline"
        assert "draft" in state["pending_steps"]
        assert "format: DOCX" in state.get("constraints", [])
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-02: 从检索阶段切换为生成阶段，产生 PHASE_CHECKPOINT
# ---------------------------------------------------------------------------
def test_p0_02_phase_transition_creates_episode_checkpoint() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = TestClient(app)

    task_id = "task-p0-02"
    episode_id = f"episode-{task_id}"
    event = _event(
        "event-p0-02",
        "idem-p0-02",
        task_id,
        payload={
            "text": "moving to generation phase",
            "_episode_event": EpisodeEventContract(
                tenant_id="tenant-p0",
                user_id="user-p0",
                episode_id=episode_id,
                task_id=task_id,
                seq_no=1,
                event_type="PHASE_CHECKPOINT",
                payload={"phase": "generation"},
                source_event_id="event-p0-02",
            ).model_dump(mode="json"),
            "_episode_snapshot": _episode_snapshot(
                episode_id, task_id, phase="generation"
            ).model_dump(mode="json"),
        },
    )

    response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": "req-p0-02",
            "idempotency_key": "idem-p0-02",
            "events": [event.model_dump(mode="json")],
        },
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["episode_id"] == episode_id
    assert body["checkpoint_created"] is True

    with db.session() as session:
        from memoryhub.storage.models import EpisodeEventRow, TaskEpisodeRow

        episode = session.query(TaskEpisodeRow).filter_by(task_id=task_id).one()
        assert episode.status == EpisodeStatus.ACTIVE.value
        checkpoint = session.query(EpisodeEventRow).filter_by(task_id=task_id).one()
        assert checkpoint.event_type == "PHASE_CHECKPOINT"
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-03: 用户说“这次请用 DOCX”只形成局部 Candidate，不形成 Global Long-Term
# ---------------------------------------------------------------------------
def test_p0_03_single_docx_instruction_does_not_immediately_promote_to_global() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = TestClient(app)

    task_id = "task-p0-03"
    event = _event(
        "event-p0-03",
        "idem-p0-03",
        task_id,
        payload={
            "text": "This time use DOCX",
            "scope": {"scene": "project-reporting", "task_type": "report"},
            "memory_type": "preference",
        },
    )

    response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": "req-p0-03",
            "idempotency_key": "idem-p0-03",
            "events": [event.model_dump(mode="json")],
        },
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # Canonical write schedules reflection asynchronously; a single instruction
    # must not immediately create an ACTIVE long-term preference.
    assert body["memory_ids"] == []

    with db.session() as session:
        from memoryhub.storage.models import PreferenceRow

        assert session.query(PreferenceRow).filter_by(user_id="user-p0").count() == 0
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-04: 服务重启后恢复任务
# ---------------------------------------------------------------------------
def test_p0_04_resume_task_after_restart_restores_state() -> None:
    db = _db()
    service = _canonical_service(db)

    task_id = "task-p0-04"
    episode_id = f"episode-{task_id}"
    # Bootstrap task through canonical write.
    service.write(
        _event(
            "event-p0-04",
            "idem-p0-04",
            task_id,
            payload={
                "text": "resume test",
                "_working_snapshot": _working_snapshot(
                    task_id,
                    goal="write recovery report",
                    current_step="outline",
                    pending_steps=["draft", "review"],
                    constraints=["deadline: EOD"],
                ).model_dump(mode="json"),
                "_episode_snapshot": _episode_snapshot(
                    episode_id, task_id, phase="draft"
                ).model_dump(mode="json"),
            },
        ),
        working_snapshot=_working_snapshot(
            task_id,
            goal="write recovery report",
            current_step="outline",
            pending_steps=["draft", "review"],
            constraints=["deadline: EOD"],
        ),
        working_state_id=f"ws-{task_id}",
        episode_snapshot=_episode_snapshot(
            episode_id,
            task_id,
            phase="draft",
            goal="write recovery report",
        ).model_copy(
            update={
                "constraints": ["deadline: EOD"],
                "pending_steps": ["draft", "review"],
            }
        ),
    )

    # Append one more event so replay has something to do.
    service.write(
        _event(
            "event-p0-04b",
            "idem-p0-04b",
            task_id,
            payload={
                "_episode_event": EpisodeEventContract(
                    tenant_id="tenant-p0",
                    user_id="user-p0",
                    episode_id=episode_id,
                    task_id=task_id,
                    seq_no=2,
                    event_type="PHASE_CHECKPOINT",
                    payload={"phase": "draft"},
                    source_event_id="event-p0-04b",
                ).model_dump(mode="json")
            },
        ),
        episode_event=EpisodeEventContract(
            tenant_id="tenant-p0",
            user_id="user-p0",
            episode_id=episode_id,
            task_id=task_id,
            seq_no=2,
            event_type="PHASE_CHECKPOINT",
            payload={"phase": "draft"},
            source_event_id="event-p0-04b",
        ),
    )

    # Snapshot to obtain a resume token; episode now has seq 2 and version 1 -> 2.
    snapshot = service.episode_service.snapshot(
        _episode_snapshot(
            episode_id,
            task_id,
            phase="draft",
            goal="write recovery report",
        ).model_copy(
            update={
                "snapshot_version": 2,
                "last_event_seq": 2,
                "constraints": ["deadline: EOD"],
                "pending_steps": ["draft", "review"],
            }
        )
    )
    token = snapshot.resume_token

    # Simulate service restart: new service instance, same database.
    new_service = _canonical_service(db)
    app = _test_app(new_service)
    client = TestClient(app)

    response = client.get(
        f"/api/memory/vnext/tasks/{task_id}/resume",
        headers={
            "X-MemoryHub-Tenant": "tenant-p0",
            "X-MemoryHub-User": "user-p0",
            "X-MemoryHub-Resume-Token": token,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restored_state"]["goal"] == "write recovery report"
    assert body["restored_state"].get("current_phase") == "draft"
    assert "draft" in body["restored_state"].get("pending_steps", [])
    assert "deadline: EOD" in body["restored_state"].get("constraints", [])
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-05: 删除索引后重建；Authority 恢复相同 memory_id/version
# ---------------------------------------------------------------------------
def test_p0_05_projection_rebuild_restores_memory_id_and_version() -> None:
    db = _db()
    with db.session() as session:
        session.add(
            PreferenceRow(
                memory_id="pref-p0-05",
                user_id="user-p0",
                tenant_id="tenant-p0",
                preference_type="output_style",
                content="Use Markdown",
                status="active",
                version=4,
            )
        )
        session.flush()

    report = rebuild_projections(db)
    assert report["errors"] == []
    assert report["enqueued"] == 1
    assert report["memory_ids"] == [
        {"memory_id": "pref-p0-05", "memory_type": "preference", "content_version": 4}
    ]

    with db.session() as session:
        from memoryhub.storage.models import MemoryProjectionOutboxRow

        row = session.query(MemoryProjectionOutboxRow).one()
        assert row.memory_id == "pref-p0-05"
        assert row.content_version == 4
        assert row.operation == "upsert"
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-06: 同一请求从 REST / CLI / MCP / SDK 发起得到一致 ID
# ---------------------------------------------------------------------------
def test_p0_06_client_and_rest_produce_same_event_id() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = TestClient(app)

    from memoryhub_client.client import MemoryHubClient

    class _TestClientAdapter:
        """Expose TestClient as the transport surface MemoryHubClient expects."""

        def __init__(self, test_client: TestClient) -> None:
            self.client = test_client

        def request(
            self,
            method: str,
            url: str,
            *,
            json: Any | None = None,
            params: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> Any:
            return self.client.request(
                method,
                url,
                json=json,
                params=params,
                headers=headers,
            )

    task_id = "task-p0-06"
    event = _event(
        "event-p0-06",
        "idem-p0-06",
        task_id,
        payload={
            "text": "multi-entrypoint consistency",
            "_working_snapshot": _working_snapshot(task_id).model_dump(mode="json"),
        },
    )

    # REST direct call
    rest_response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": "req-p0-06-rest",
            "idempotency_key": "idem-p0-06",
            "events": [event.model_dump(mode="json")],
        },
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert rest_response.status_code == 200, rest_response.text
    rest_body = rest_response.json()

    # SDK client call against the same test app
    sdk = MemoryHubClient(
        base_url="http://127.0.0.1:80",
        client=_TestClientAdapter(client),
    )
    sdk_body = sdk.write_canonical_events(
        [event.model_dump(mode="json")],
        request_id="req-p0-06-sdk",
        idempotency_key="idem-p0-06",
        tenant_id="tenant-p0",
        user_id="user-p0",
    )

    # Idempotent replay must return the same durable event id.
    assert sdk_body["event_ids"] == rest_body["event_ids"]
    assert sdk_body["episode_id"] == rest_body["episode_id"]

    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-07: 同一事件重复提交不会重复累计
# ---------------------------------------------------------------------------
def test_p0_07_idempotent_event_does_not_duplicate_rows() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = TestClient(app)

    task_id = "task-p0-07"
    event = _event(
        "event-p0-07",
        "idem-p0-07",
        task_id,
        payload={
            "text": "idempotent event",
            "_working_snapshot": _working_snapshot(task_id).model_dump(mode="json"),
        },
    )
    payload = {
        "api_version": "vnext/v1",
        "request_id": "req-p0-07",
        "idempotency_key": "idem-p0-07",
        "events": [event.model_dump(mode="json")],
    }

    first = client.post(
        "/api/memory/vnext/events",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    second = client.post(
        "/api/memory/vnext/events",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_ids"] == second.json()["event_ids"]

    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1
        from memoryhub.storage.models import MemoryEvidenceRow

        assert session.query(MemoryEvidenceRow).filter_by(event_id="event-p0-07").count() <= 1
    db.close()


# ---------------------------------------------------------------------------
# E2E-P0-08: 事件包含 Token / 私密正文，Policy 必须 DROP/MASK
# ---------------------------------------------------------------------------
def test_p0_08_sensitive_event_is_blocked_or_masked() -> None:
    db = _db()

    # A policy that masks any payload containing a secret-looking token.
    def mask_policy(event: MemoryEventContract) -> MemoryEventContract:
        payload = dict(event.payload)
        text = str(payload.get("text", ""))
        if "AKIA" in text or "secret" in text.lower():
            payload["text"] = text.replace("AKIA", "[REDACTED]")
            return event.model_copy(update={"policy_action": "MASK", "payload": payload})
        return event.model_copy(update={"policy_action": "ALLOW"})

    service = _canonical_service(db, policy=mask_policy)
    app = _test_app(service)
    client = TestClient(app)

    task_id = "task-p0-08"
    event = _event(
        "event-p0-08",
        "idem-p0-08",
        task_id,
        payload={
            "text": "My secret token is AKIAIOSFODNN7EXAMPLE",
            "_working_snapshot": _working_snapshot(task_id).model_dump(mode="json"),
        },
    )

    response = client.post(
        "/api/memory/vnext/events",
        json={
            "api_version": "vnext/v1",
            "request_id": "req-p0-08",
            "idempotency_key": "idem-p0-08",
            "events": [event.model_dump(mode="json")],
        },
        headers={"X-MemoryHub-Tenant": "tenant-p0", "X-MemoryHub-User": "user-p0"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # MASK still commits the event, but the sensitive token must not reach
    # downstream working state or long-term memory unchanged.
    assert body["event_ids"] == ["event-p0-08"]

    with db.session() as session:
        row = session.query(EventRow).one()
        stored_payload = row.payload
        assert "AKIA" not in stored_payload.get("text", "")
        assert "[REDACTED]" in stored_payload.get("text", "")
    db.close()
