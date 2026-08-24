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
from memoryhub.storage.models import EventRow, IdempotencyRecordRow, WorkingStateRow
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository

ROOT = Path(__file__).parents[1]
DB_BASE = ROOT / "evaluation" / "results" / "vnext_entrypoints_test"
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
    event_id: str = "event-entry",
    idempotency_key: str = "idem-entry",
    task_id: str = "task-entry",
    include_episode: bool = True,
) -> MemoryEventContract:
    episode_id = f"episode-{task_id}"
    payload: dict[str, Any] = {
        "instruction": "Use DOCX",
        "_long_term": _long_term().model_dump(mode="json"),
    }
    if include_episode:
        payload["_episode_snapshot"] = _episode_snapshot(
            episode_id, task_id
        ).model_dump(mode="json")
        payload["_working_snapshot"] = _working_snapshot(task_id).model_dump(mode="json")
    return MemoryEventContract(
        tenant_id="tenant-entry",
        user_id="user-entry",
        event_id=event_id,
        event_type="user_instruction",
        source_type="user_behavior",
        task_id=task_id,
        session_id="session-entry",
        occurred_at=datetime.now(timezone.utc),
        payload=payload,
        policy_action="ALLOW",
        source_hash=(event_id + "a" * 64)[:64],
        idempotency_key=idempotency_key,
        trace_id="trace-" + event_id,
    )


def _working_snapshot(task_id: str = "task-entry") -> WorkingSnapshot:
    return WorkingSnapshot(
        tenant_id="tenant-entry",
        user_id="user-entry",
        task_id=task_id,
        session_id="session-entry",
        current_goal="write report",
        current_step="draft",
        pending_steps=["review"],
    )


def _episode_snapshot(
    episode_id: str | None = None, task_id: str = "task-entry", last_event_seq: int = 1
) -> EpisodeSnapshot:
    episode_id = episode_id or f"episode-{task_id}"
    return EpisodeSnapshot(
        tenant_id="tenant-entry",
        user_id="user-entry",
        episode_id=episode_id,
        task_id=task_id,
        session_id="session-entry",
        status=EpisodeStatus.ACTIVE,
        current_phase="draft",
        goal="write report",
        pending_steps=["review"],
        last_event_seq=last_event_seq,
    )


def _long_term(memory_id: str = "pref-entry") -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id="tenant-entry",
        user_id="user-entry",
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
        evidence_refs=["event-entry"],
    )


def _canonical_service(db: Database) -> CanonicalWriteService:
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
    app.state.user_rule_identity_resolver = None
    app.include_router(vnext_router)
    return app


def _client(app: FastAPI) -> Any:
    return TestClient(app)


def test_canonical_write_endpoint_creates_event_working_episode_and_memory() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = _client(app)

    event = _event()
    payload = {
        "api_version": "vnext/v1",
        "request_id": "req-1",
        "idempotency_key": "idem-1",
        "events": [event.model_dump(mode="json")],
    }
    response = client.post(
        "/api/memory/vnext/events",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"] == "req-1"
    assert len(body["event_ids"]) == 1
    assert body["episode_id"] == "episode-task-entry"
    assert body["working_state_version"] == 1
    assert body["memory_ids"] == ["pref-entry"]

    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1
        ws = session.query(WorkingStateRow).one()
        assert ws.task_id == "task-entry"
        assert ws.version == 1
    db.close()


def test_canonical_write_endpoint_is_idempotent_across_entrypoints() -> None:
    db = _db()
    service = _canonical_service(db)
    app = _test_app(service)
    client = _client(app)

    event = _event()
    base_payload = {
        "api_version": "vnext/v1",
        "request_id": "req-2",
        "idempotency_key": "idem-2",
        "events": [event.model_dump(mode="json")],
    }
    first = client.post(
        "/api/memory/vnext/events",
        json=base_payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    )
    assert first.status_code == 200
    first_body = first.json()

    # Simulate a different entrypoint (MCP/CLI/SDK) replaying the same event.
    second = client.post(
        "/api/memory/vnext/events",
        json=base_payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["event_ids"] == first_body["event_ids"]
    # Idempotent replay returns the same event id; downstream checkpoint details
    # are only present on the original commit because the idempotency record
    # stores the event identity, not the full canonical result.
    assert second_body["degraded"] is False
    assert second_body["event_ids"] == first_body["event_ids"]

    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1
    db.close()


def test_resume_task_endpoint_replays_events_and_surface_stale_resources() -> None:
    db = _db()
    service = _canonical_service(db)

    # Bootstrap an episode and snapshot through canonical write.
    service.write(
        _event(event_id="event-resume", idempotency_key="idem-resume"),
        working_snapshot=_working_snapshot(task_id="task-resume"),
        working_state_id="ws-resume",
        episode_event=EpisodeEventContract(
            tenant_id="tenant-entry",
            user_id="user-entry",
            episode_id="episode-resume",
            task_id="task-resume",
            seq_no=1,
            event_type="PHASE_CHECKPOINT",
            payload={"phase": "draft"},
            source_event_id="event-resume",
        ),
        episode_snapshot=_episode_snapshot("episode-resume", "task-resume"),
    )

    # Snapshot again to obtain a resume token.
    result = service.episode_service.snapshot(
        _episode_snapshot("episode-resume", "task-resume").model_copy(
            update={"snapshot_version": 2, "last_event_seq": 1}
        )
    )
    token = result.resume_token

    app = _test_app(service)
    client = _client(app)

    response = client.get(
        "/api/memory/vnext/tasks/task-resume/resume",
        headers={
            "X-MemoryHub-Tenant": "tenant-entry",
            "X-MemoryHub-User": "user-entry",
            "X-MemoryHub-Resume-Token": token,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restored_state"]["goal"] == "write report"
    assert body["resume_token"] == token
    assert body["request_id"] == "resume:task-resume"
    db.close()


def test_resume_task_endpoint_fails_on_wrong_token() -> None:
    db = _db()
    service = _canonical_service(db)
    service.write(
        _event(event_id="event-token", idempotency_key="idem-token"),
        working_snapshot=_working_snapshot(task_id="task-token"),
        working_state_id="ws-token",
        episode_event=EpisodeEventContract(
            tenant_id="tenant-entry",
            user_id="user-entry",
            episode_id="episode-token",
            task_id="task-token",
            seq_no=1,
            event_type="PHASE_CHECKPOINT",
            payload={"phase": "draft"},
            source_event_id="event-token",
        ),
        episode_snapshot=_episode_snapshot("episode-token", "task-token"),
    )
    service.episode_service.snapshot(
        _episode_snapshot("episode-token", "task-token").model_copy(
            update={"snapshot_version": 2, "last_event_seq": 1}
        )
    )

    app = _test_app(service)
    client = _client(app)
    response = client.get(
        "/api/memory/vnext/tasks/task-token/resume",
        headers={
            "X-MemoryHub-Tenant": "tenant-entry",
            "X-MemoryHub-User": "user-entry",
            "X-MemoryHub-Resume-Token": "wrong-token",
        },
    )
    assert response.status_code == 409
    db.close()


def test_agent_replay_delegates_to_canonical_write_service() -> None:
    db = _db()
    service = _canonical_service(db)

    from memoryhub.adapter.agent_api import _to_memory_event_contract
    from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus, SourceType

    event = MemoryEvent(
        event_id="agent-replay-event",
        source_type=SourceType.USER_BEHAVIOR,
        event_type="chat",
        user_id="user-entry",
        session_id="session-replay",
        occurred_at="2026-08-24T00:00:00Z",
        payload={"text": "hello"},
        source_hash="0" * 64,
        quality=EventQuality(
            score=1.0,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )
    contract = _to_memory_event_contract(event)
    result = service.write(contract)
    assert result.status.value == "COMMITTED"

    with db.session() as session:
        assert session.query(EventRow).filter_by(event_id="agent-replay-event").count() == 1
    db.close()



def _retrieved_memory(memory_id: str, score: float = 0.9) -> Any:
    from memoryhub.adapter.vnext_schemas import RetrievedMemory
    from memoryhub.domain.contracts import (
        LifecycleLayer,
        MemoryScope,
        MemoryType,
    )

    return RetrievedMemory(
        tenant_id="tenant-entry",
        user_id="user-entry",
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        content_version=1,
        evolution_status="ACTIVE",
        content={"text": f"content of {memory_id}"},
        score=score,
        score_breakdown={},
        source_ids=["src:entry"],
    )


def _channel_executor(candidates: list[Any]):
    def executor(request, plan, channel):
        return candidates
    return executor


def _retrieval_service(db: Database) -> Any:
    from memoryhub.application.retrieval_service import RetrievalService
    from memoryhub.storage.vnext_repositories import (
        ActivationRepository,
        RetrievalLogRepository,
    )

    candidates = [_retrieved_memory("m-entry-1"), _retrieved_memory("m-entry-2", score=0.7)]
    return RetrievalService(
        channel_executors={"vector": _channel_executor(candidates)},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
    )


def _test_app_with_retrieval(
    write_service: CanonicalWriteService, retrieval_service: Any
) -> FastAPI:
    app = _test_app(write_service)
    app.state.retrieval_service = retrieval_service
    return app


def test_vnext_search_returns_consistent_ids_and_trace() -> None:
    db = _db()
    write_service = _canonical_service(db)
    retrieval_service = _retrieval_service(db)
    app = _test_app_with_retrieval(write_service, retrieval_service)
    client = _client(app)

    payload = {
        "api_version": "vnext/v1",
        "request_id": "req-search-1",
        "tenant_id": "tenant-entry",
        "user_id": "user-entry",
        "query": "report format",
        "task_id": "task-entry",
        "intent_hint": "PREFERENCE",
        "token_budget": 1000,
    }
    response = client.post(
        "/api/memory/vnext/search",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request_id"] == "req-search-1"
    assert body["trace_id"] == "req-search-1"
    assert body["intent"] == "PREFERENCE"
    assert body["total_count"] == 2
    ids = [m["memory_id"] for m in body["selected_memories"]]
    assert "m-entry-1" in ids
    assert "m-entry-2" in ids
    assert "vector" in body["retrieval_plan"]["enabled_channels"]
    assert len(body["activations"]) == 2
    db.close()


def test_vnext_context_returns_same_memories_as_search() -> None:
    db = _db()
    write_service = _canonical_service(db)
    retrieval_service = _retrieval_service(db)
    app = _test_app_with_retrieval(write_service, retrieval_service)
    client = _client(app)

    payload = {
        "api_version": "vnext/v1",
        "request_id": "req-context-1",
        "tenant_id": "tenant-entry",
        "user_id": "user-entry",
        "query": "report format",
        "task_id": "task-entry",
        "intent_hint": "PREFERENCE",
        "token_budget": 1000,
    }
    search_response = client.post(
        "/api/memory/vnext/search",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    ).json()
    context_response = client.post(
        "/api/memory/vnext/context",
        json=payload,
        headers={"X-MemoryHub-Tenant": "tenant-entry", "X-MemoryHub-User": "user-entry"},
    )
    assert context_response.status_code == 200, context_response.text
    ctx = context_response.json()
    assert ctx["relevant_memory_ids"] == search_response["context"]["relevant_memory_ids"]
    assert ctx["rendered_context"]
    db.close()


def test_legacy_search_delegates_to_vnext_retrieval_service() -> None:
    db = _db()
    write_service = _canonical_service(db)
    retrieval_service = _retrieval_service(db)
    app = _test_app_with_retrieval(write_service, retrieval_service)

    # Also mount the legacy memory router so /search is available.
    from memoryhub.adapter.api import router as memory_router

    app.include_router(memory_router)
    client = _client(app)

    response = client.post(
        "/api/memory/search",
        json={"user_id": "user-entry", "query": "report format", "top_k": 5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # The legacy response is produced by the vNext retrieval service.
    assert body["total_count"] == 2
    legacy_ids = {r["memory_id"] for r in body["results"]}
    assert "m-entry-1" in legacy_ids
    assert "m-entry-2" in legacy_ids
    db.close()
