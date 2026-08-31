"""Stage 2 Batch 1 tests: Working / Episode channel executors.

These tests prove that CURRENT_STATE and TASK_HISTORY retrieval really read
the structured Working State and Task Episode repositories instead of
degrading to the legacy vector search:

* exact task matching, session fallback, and bounded results;
* tenant / user isolation on every structured lookup;
* deterministic episode relevance ranking over goal text;
* end-to-end presence of both channels in the RetrievalService pipeline.
"""

from __future__ import annotations

from types import SimpleNamespace

from memoryhub.adapter.retrieval_executor import (
    EPISODE_FALLBACK_LIMIT,
    WORKING_FALLBACK_LIMIT,
    build_channel_executors,
    build_episode_executor,
    build_working_executor,
)
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import (
    EpisodeRepository,
    WorkingStateRepository,
)

TENANT = "tenant-re"
USER = "user-re"


def _db() -> Database:
    database = Database(":memory:")
    database.init_schema()
    return database


def _request(
    *,
    query: str = "",
    task_id: str = "",
    session_id: str = "",
    intent: RetrievalIntent,
    tenant_id: str = TENANT,
    user_id: str = USER,
) -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id=f"req-{task_id or 'recent'}-{intent.value.lower()}",
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        task_id=task_id,
        session_id=session_id,
        intent_hint=intent,
    )


def _create_working_state(
    repo: WorkingStateRepository,
    *,
    task_id: str,
    session_id: str = "sess-1",
    goal: str = "Fix SSE reconnect bug",
    step: str = "verify reconnect",
    pending: list[str] | None = None,
    blockers: list[str] | None = None,
    tenant_id: str = TENANT,
    user_id: str = USER,
    working_state_id: str | None = None,
):
    state = {
        "current_goal": goal,
        "current_step": step,
        "pending_steps": pending or ["verify reconnect", "update docs"],
        "completed_steps": ["locate timeout config"],
        "constraints": ["do not restart server"],
        "active_entities": ["sse_handler.py"],
        "blockers": blockers or [],
        "recent_findings": ["timeout was 3000ms"],
        "recent_failures": [],
        "next_action": "run integration test",
    }
    return repo.create(
        working_state_id=working_state_id or f"ws-{tenant_id}-{user_id}-{task_id}",
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=task_id,
        session_id=session_id,
        state=state,
    )


def _create_episode(
    repo: EpisodeRepository,
    *,
    episode_id: str,
    task_id: str,
    session_id: str = "sess-1",
    goal: str = "Fix SSE reconnect issue",
    status: str | None = None,
    events: list[dict] | None = None,
    tenant_id: str = TENANT,
    user_id: str = USER,
):
    view = repo.create(
        episode_id=episode_id,
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=task_id,
        session_id=session_id,
        goal=goal,
    )
    if status is not None:
        repo.save_snapshot(
            tenant_id=tenant_id,
            user_id=user_id,
            episode_id=episode_id,
            task_id=task_id,
            session_id=session_id,
            status=status,
            current_phase="closed",
            goal=goal,
            snapshot={"goal": goal},
            last_event_seq=0,
            expected_snapshot_version=view.snapshot_version,
            resume_token="test-resume-token",
        )
    for index, event in enumerate(events or [], start=1):
        repo.append_event(
            episode_event_id=f"evt-{episode_id}-{index}",
            tenant_id=tenant_id,
            user_id=user_id,
            episode_id=episode_id,
            task_id=task_id,
            event_type=event["event_type"],
            payload=event.get("payload", {}),
            source_event_id=f"src-{episode_id}-{index}",
        )
    return view


# ---------------------------------------------------------------------------
# Working channel unit behaviour
# ---------------------------------------------------------------------------


def test_current_state_returns_exact_task_working_state() -> None:
    db = _db()
    repo = WorkingStateRepository(db)
    _create_working_state(repo, task_id="task-1", goal="Fix SSE reconnect bug")
    _create_working_state(
        repo, task_id="task-2", goal="Write migration guide", working_state_id="ws-other"
    )

    executor = build_working_executor(repo)
    results = executor(
        _request(task_id="task-1", intent=RetrievalIntent.CURRENT_STATE),
        plan=None,
        channel="working",
    )

    assert len(results) == 1
    memory = results[0]
    assert memory.memory_id.startswith("ws:")
    assert memory.layer is LifecycleLayer.WORKING
    assert memory.memory_type is MemoryType.SEMANTIC
    assert memory.scope_level is MemoryScope.TASK
    assert memory.scope == "task-1"
    assert memory.score == 1.0
    assert memory.score_breakdown["channel"] == "working"
    assert memory.score_breakdown["match"] == "task"
    # The result restores the real task progress fields.
    assert memory.content["current_goal"] == "Fix SSE reconnect bug"
    assert memory.content["current_step"] == "verify reconnect"
    assert memory.content["pending_steps"] == ["verify reconnect", "update docs"]
    assert memory.content["next_action"] == "run integration test"
    assert memory.source_ids
    db.close()


def test_current_state_isolates_users_and_tenants() -> None:
    db = _db()
    repo = WorkingStateRepository(db)
    _create_working_state(repo, task_id="task-1", goal="User A private goal")

    executor = build_working_executor(repo)
    other_user = executor(
        _request(
            task_id="task-1",
            intent=RetrievalIntent.CURRENT_STATE,
            user_id="user-other",
        ),
        plan=None,
        channel="working",
    )
    assert other_user == []

    other_tenant = executor(
        _request(
            task_id="task-1",
            intent=RetrievalIntent.CURRENT_STATE,
            tenant_id="tenant-other",
        ),
        plan=None,
        channel="working",
    )
    assert other_tenant == []
    db.close()


def test_current_state_falls_back_to_session_states_without_task() -> None:
    db = _db()
    repo = WorkingStateRepository(db)
    _create_working_state(repo, task_id="task-1", session_id="sess-1")
    _create_working_state(
        repo, task_id="task-2", session_id="sess-1", working_state_id="ws-t2"
    )
    _create_working_state(
        repo,
        task_id="task-9",
        session_id="sess-2",
        working_state_id="ws-t9",
    )

    executor = build_working_executor(repo)
    results = executor(
        _request(session_id="sess-1", intent=RetrievalIntent.CURRENT_STATE),
        plan=None,
        channel="working",
    )

    assert {memory.scope for memory in results} == {"task-1", "task-2"}
    assert all(memory.score_breakdown["match"] == "recent" for memory in results)
    assert all(memory.layer is LifecycleLayer.WORKING for memory in results)
    db.close()


def test_working_fallback_is_bounded() -> None:
    db = _db()
    repo = WorkingStateRepository(db)
    for index in range(WORKING_FALLBACK_LIMIT + 3):
        _create_working_state(
            repo,
            task_id=f"task-{index}",
            working_state_id=f"ws-bounded-{index}",
        )

    executor = build_working_executor(repo)
    results = executor(
        _request(intent=RetrievalIntent.CURRENT_STATE),
        plan=None,
        channel="working",
    )

    assert len(results) == WORKING_FALLBACK_LIMIT
    # Newest states first: the recency decay keeps scores ordered.
    scores = [memory.score for memory in results]
    assert scores == sorted(scores, reverse=True)
    db.close()


# ---------------------------------------------------------------------------
# Episode channel unit behaviour
# ---------------------------------------------------------------------------


def test_task_history_returns_episode_with_key_events() -> None:
    db = _db()
    repo = EpisodeRepository(db)
    _create_episode(
        repo,
        episode_id="ep-1",
        task_id="task-1",
        goal="Fix SSE reconnect issue",
        events=[
            {
                "event_type": "tool_call",
                "payload": {"summary": "located spring.mvc.async.request-timeout"},
            },
            {
                "event_type": "task_completed",
                "payload": {"summary": "reconnect verified"},
            },
        ],
    )
    _create_episode(
        repo,
        episode_id="ep-2",
        task_id="task-2",
        goal="Write release notes",
        events=None,
    )

    executor = build_episode_executor(repo)
    results = executor(
        _request(task_id="task-1", intent=RetrievalIntent.TASK_HISTORY),
        plan=None,
        channel="episode",
    )

    assert len(results) == 1
    memory = results[0]
    assert memory.memory_id == "ep:ep-1"
    assert memory.layer is LifecycleLayer.EPISODE
    assert memory.memory_type is MemoryType.EPISODIC
    assert memory.scope_level is MemoryScope.TASK
    assert memory.scope == "task-1"
    assert memory.score == 1.0
    assert memory.score_breakdown["match"] == "task"
    assert memory.content["goal"] == "Fix SSE reconnect issue"
    assert memory.content["status"] == "ACTIVE"
    key_events = memory.content["key_events"]
    assert any("located spring.mvc.async.request-timeout" in item for item in key_events)
    assert any("reconnect verified" in item for item in key_events)
    db.close()


def test_task_history_fallback_ranks_by_query_relevance() -> None:
    db = _db()
    repo = EpisodeRepository(db)
    _create_episode(
        repo,
        episode_id="ep-rel-2",
        task_id="task-unrelated",
        goal="数据库索引设计讨论",
    )
    _create_episode(
        repo,
        episode_id="ep-rel-1",
        task_id="task-sse",
        goal="修复 SSE 重连问题",
    )

    executor = build_episode_executor(repo)
    results = executor(
        _request(
            query="SSE 重连问题之前怎么处理",
            intent=RetrievalIntent.TASK_HISTORY,
        ),
        plan=None,
        channel="episode",
    )

    assert [memory.memory_id for memory in results][0] == "ep:ep-rel-1"
    assert len(results) == 2
    assert results[0].score > results[1].score
    assert results[0].score_breakdown["relevance"] > results[1].score_breakdown["relevance"]
    db.close()


def test_task_history_fallback_excludes_archived_and_is_bounded() -> None:
    db = _db()
    repo = EpisodeRepository(db)
    _create_episode(
        repo,
        episode_id="ep-arch",
        task_id="task-arch",
        goal="Old archived effort",
        status="ARCHIVED",
    )
    for index in range(EPISODE_FALLBACK_LIMIT + 2):
        _create_episode(
            repo,
            episode_id=f"ep-live-{index}",
            task_id=f"task-live-{index}",
            goal=f"Live effort {index}",
        )

    executor = build_episode_executor(repo)
    results = executor(
        _request(query="Live effort", intent=RetrievalIntent.TASK_HISTORY),
        plan=None,
        channel="episode",
    )

    assert len(results) == EPISODE_FALLBACK_LIMIT
    assert all(memory.memory_id != "ep:ep-arch" for memory in results)
    db.close()


def test_episode_channel_isolates_users() -> None:
    db = _db()
    repo = EpisodeRepository(db)
    _create_episode(
        repo,
        episode_id="ep-private",
        task_id="task-1",
        goal="User A private history",
    )

    executor = build_episode_executor(repo)
    results = executor(
        _request(
            task_id="task-1",
            intent=RetrievalIntent.TASK_HISTORY,
            user_id="user-other",
        ),
        plan=None,
        channel="episode",
    )
    assert results == []
    db.close()


# ---------------------------------------------------------------------------
# Registration and RetrievalService integration
# ---------------------------------------------------------------------------


def test_channel_executors_register_structured_channels() -> None:
    db = _db()
    state = SimpleNamespace(
        working_state_repository=WorkingStateRepository(db),
        episode_repository=EpisodeRepository(db),
    )
    executors = build_channel_executors(state)
    assert set(executors) == {"working", "episode"}
    db.close()


def test_retrieval_service_current_state_uses_working_channel() -> None:
    db = _db()
    working_repo = WorkingStateRepository(db)
    episode_repo = EpisodeRepository(db)
    _create_working_state(working_repo, task_id="task-1", goal="Fix SSE reconnect bug")

    service = RetrievalService(
        channel_executors=build_channel_executors(
            SimpleNamespace(
                working_state_repository=working_repo, episode_repository=episode_repo
            )
        )
    )
    response = service.search(
        _request(task_id="task-1", intent=RetrievalIntent.CURRENT_STATE)
    )

    assert "working" in response.retrieval_plan["enabled_channels"]
    assert response.intent is RetrievalIntent.CURRENT_STATE
    assert response.completeness == "FULL"
    selected_ids = [memory.memory_id for memory in response.selected_memories]
    assert any(memory_id.startswith("ws:") for memory_id in selected_ids)
    working = next(
        memory
        for memory in response.selected_memories
        if memory.memory_id.startswith("ws:")
    )
    assert working.score_breakdown["channel"] == "working"
    assert working.content["current_goal"] == "Fix SSE reconnect bug"
    assert working.memory_id in response.context.relevant_memory_ids
    db.close()


def test_retrieval_service_task_history_uses_episode_channel() -> None:
    db = _db()
    working_repo = WorkingStateRepository(db)
    episode_repo = EpisodeRepository(db)
    _create_episode(
        episode_repo,
        episode_id="ep-hist",
        task_id="task-1",
        goal="Fix SSE reconnect issue",
    )

    service = RetrievalService(
        channel_executors=build_channel_executors(
            SimpleNamespace(
                working_state_repository=working_repo, episode_repository=episode_repo
            )
        )
    )
    response = service.search(
        _request(task_id="task-1", intent=RetrievalIntent.TASK_HISTORY)
    )

    assert "episode" in response.retrieval_plan["enabled_channels"]
    assert response.intent is RetrievalIntent.TASK_HISTORY
    assert response.completeness == "FULL"
    selected_ids = [memory.memory_id for memory in response.selected_memories]
    assert "ep:ep-hist" in selected_ids
    episode = next(
        memory for memory in response.selected_memories if memory.memory_id == "ep:ep-hist"
    )
    assert episode.score_breakdown["channel"] == "episode"
    assert episode.memory_id in response.context.relevant_memory_ids
    db.close()
