from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import ReflectionService
from memoryhub.application.working_service import WorkingService
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import (
    EpisodeStatus,
    MemoryEventContract,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.vnext_repositories import (
    CandidateRepository,
    EpisodeRepository,
    WorkingStateRepository,
)


def _event(
    event_id: str,
    payload: dict,
    *,
    event_type: str = "agent_response",
    task_id: str = "task-boundary",
    user_id: str = "user-boundary",
    tenant_id: str = "tenant-boundary",
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id=tenant_id,
        user_id=user_id,
        event_id=event_id,
        event_type=event_type,
        source_type="tool_result",
        task_id=task_id,
        session_id=f"session-{task_id}",
        occurred_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        payload=payload,
        policy_action="ALLOW",
        source_hash="b" * 64,
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def _tool(
    name: str,
    status: str,
    *,
    arguments: dict | None = None,
    **extra: object,
) -> dict:
    return {
        "tool_name": name,
        "status": status,
        "arguments": arguments or {},
        **extra,
    }


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture()
def service(db: Database) -> CanonicalWriteService:
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
    )


class _DeterministicReflectionModel:
    """A deterministic reflection model that always produces a stable candidate."""

    model_id = "deterministic-reflection/v1"

    def generate(self, _prompt, *, input_hash, input_data=None):
        return {
            "candidate_id": f"candidate-{input_hash[:16]}",
            "memory_type": "PREFERENCE",
            "normalized_key": "boundary:test",
            "claim": {"value": "boundary driven"},
            "scope_level": "TASK",
            "scope": "TASK:boundary-test",
            "confidence": 0.8,
            "utility": 0.7,
            "stability": 0.6,
            "model_id": self.model_id,
            "prompt_version": "prompt/v1",
            "input_hash": input_hash,
            "reason": "boundary driven reflection",
            "evidence_refs": ["event-boundary"],
            "supporting_episode_ids": ["episode-task-boundary"],
            "status": "ACCUMULATING",
        }


def _candidate_only_stack(db: Database):
    pref = PreferenceRepository(db)
    know = KnowledgeRepository(db)
    authority = LongTermAuthorityFacade(
        AuthorityRepository(
            db, preference_repository=pref, knowledge_repository=know
        )
    )
    writer = MemoryWriteService(
        pref_repo=pref, know_repo=know, project_immediately=False
    )
    tasks = ExtractionTaskRepository(db)
    canonical = CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        extraction_tasks=tasks,
        authority_facade=authority,
        memory_write_service=writer,
        formation_mode="candidate-only",
    )
    worker = FormationWorker(
        db,
        task_repository=tasks,
        event_repository=EventRepository(db),
        canonical_write_service=canonical,
        mode="candidate-only",
        reflection_service=ReflectionService(
            model=_DeterministicReflectionModel(), max_retries=0
        ),
    )
    retry = ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )
    return canonical, worker, retry, tasks


def test_low_value_tool_events_do_not_trigger_reflection(
    service: CanonicalWriteService,
) -> None:
    """普通低价值事件（read_file / git_status / search）不应逐条触发 Reflection."""

    low_value_events = [
        _event(
            "read-1",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "main.py"})]},
        ),
        _event(
            "git-1",
            {"tool_calls": [_tool("bash", "success", arguments={"command": "git status"})]},
        ),
        _event(
            "search-1",
            {"tool_calls": [_tool("search", "success", arguments={"query": "TODO"})]},
        ),
    ]
    for event in low_value_events:
        result = service.write(event)
        assert result.reflection_task is None, (
            f"event {event.event_id} should not trigger reflection"
        )


def test_task_complete_triggers_reflection(
    service: CanonicalWriteService,
) -> None:
    """Task Complete 边界应触发 Reflection."""

    service.write(
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction")
    )
    result = service.write(
        _event(
            "complete-1",
            {
                "tool_calls": [
                    _tool("bash", "success", arguments={"command": "pytest"})
                ]
            },
            event_type="task_completed",
        )
    )
    assert result.reflection_task is not None
    assert result.episode_snapshot is not None
    assert result.episode_snapshot.snapshot.status is EpisodeStatus.COMPLETED


def test_task_failed_triggers_reflection(
    service: CanonicalWriteService,
) -> None:
    """Task Failure 边界应触发 Reflection."""

    service.write(
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction")
    )
    result = service.write(
        _event(
            "failed-1",
            {
                "tool_calls": [
                    _tool(
                        "bash",
                        "error",
                        arguments={"command": "pytest tests/test_sse.py"},
                        error="AssertionError",
                    )
                ]
            },
            event_type="task_failed",
        )
    )
    assert result.reflection_task is not None
    assert result.episode_snapshot is not None
    assert result.episode_snapshot.snapshot.status is EpisodeStatus.FAILED


def test_explicit_remember_triggers_reflection(
    service: CanonicalWriteService,
) -> None:
    """用户显式 remember 边界应触发 Reflection."""

    service.write(
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction")
    )
    result = service.write(
        _event(
            "remember-1",
            {
                "boundary": "explicit",
                "text": "This project uses Maven",
            },
        )
    )
    assert result.reflection_task is not None
    assert result.episode_snapshot is not None
    assert result.episode_snapshot.snapshot.status is EpisodeStatus.ACTIVE


def test_boundary_debounce_prevents_duplicate_reflection_tasks(
    service: CanonicalWriteService,
) -> None:
    """同类型 meaningful boundary 在 debounce 窗口内不应重复 enqueue Reflection."""

    service.write(
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction")
    )
    # 超过 context pressure 阈值，触发 CONTEXT_PRESSURE 边界。
    first = service.write(
        _event(
            "pressure-1",
            {
                "pending_steps": [f"step-{i}" for i in range(10)],
                "constraints": ["DOCX", "formal"],
            },
        )
    )
    # 同一任务、同一 debounce key 的第二次压力事件应被抑制。
    second = service.write(
        _event(
            "pressure-2",
            {
                "pending_steps": [f"step-{i}" for i in range(12)],
                "constraints": ["DOCX", "formal", "urgent"],
            },
        )
    )
    assert first.reflection_task is not None
    assert (
        second.reflection_task is None
        or second.reflection_task.task_id == first.reflection_task.task_id
    )


def test_candidate_only_does_not_write_authority(db: Database) -> None:
    """candidate-only 模式下 Boundary 触发 Reflection 产生 Candidate，但不写 Long-Term Authority."""

    canonical, _worker, retry, tasks = _candidate_only_stack(db)
    canonical.write(
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction")
    )
    result = canonical.write(
        _event(
            "remember-1",
            {"boundary": "explicit", "text": "Use Maven for this project"},
        )
    )
    assert result.reflection_task is not None

    run = retry.run_due(user_id=result.reflection_task.user_id)
    remember_task = tasks.get(
        result.reflection_task.task_id, user_id=result.reflection_task.user_id
    )
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=result.reflection_task.tenant_id,
        user_id=result.reflection_task.user_id,
    )

    # user_instruction (START) 与 remember (EXPLICIT) 都会产生 reflection task。
    assert run.succeeded >= 1
    assert remember_task is not None and remember_task.candidate_ids
    assert len(candidates) >= 1
    assert (
        PreferenceRepository(db).list_all(user_id=result.reflection_task.user_id) == []
    )
