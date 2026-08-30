"""Stage 1 Scenario Tests for MemoryHub vNext Formation.

These six scenarios exercise the end-to-end formation path with real
continuous Agent events:

  Event -> Working State -> Episode -> Boundary -> Reflection -> Candidate

All scenarios run against an in-memory SQLite database and a deterministic
reflection model so they do not require external LLM credentials.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import ReflectionModel, ReflectionService
from memoryhub.application.working_service import WorkingService
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.reflection.schema import ReflectionInput
from memoryhub.domain.contracts import MemoryEventContract, MemoryScope
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

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _event(
    event_id: str,
    payload: dict,
    *,
    event_type: str = "agent_response",
    task_id: str,
    user_id: str,
    tenant_id: str,
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


# ---------------------------------------------------------------------------
# Reflection models
# ---------------------------------------------------------------------------


class _DeterministicReflectionModel:
    """A deterministic reflection model that always produces a stable candidate."""

    model_id = "deterministic-reflection/v1"

    def generate(
        self,
        _prompt: str,
        *,
        input_hash: str,
        input_data: ReflectionInput | None = None,
    ) -> dict:
        payload = input_data.payload_summary if input_data is not None else {}
        text = str(payload.get("text", "")).lower()
        memory_type = "PREFERENCE"
        normalized_key = "preference:unknown"
        claim: dict = {"value": text}
        scope_level = "TASK"
        scope = "TASK:default"

        if "docx" in text or "markdown" in text or "maven" in text or "dark" in text:
            normalized_key = "format:preference"
            claim = {"value": text}
            scope_level = "PROJECT"
            scope = "PROJECT:default"

        event_id = input_data.event_id if input_data is not None else ""
        episode_id = input_data.episode_id if input_data is not None else ""

        return {
            "candidate_id": f"candidate-{input_hash[:16]}",
            "memory_type": memory_type,
            "normalized_key": normalized_key,
            "claim": claim,
            "scope_level": scope_level,
            "scope": scope,
            "confidence": 0.8,
            "utility": 0.7,
            "stability": 0.6,
            "model_id": self.model_id,
            "prompt_version": "reflection/v1",
            "input_hash": input_hash,
            "reason": "scenario deterministic reflection",
            "evidence_refs": [event_id],
            "supporting_episode_ids": [episode_id],
            "status": "ACCUMULATING",
        }


class _InvalidReflectionModel(ReflectionModel):
    """A reflection model that returns an invalid schema result."""

    model_id = "invalid-reflection/v1"

    def generate(
        self,
        _prompt: str,
        *,
        input_hash: str,
        input_data: ReflectionInput | None = None,
    ) -> dict:
        return {"candidate_id": "candidate-invalid"}


# ---------------------------------------------------------------------------
# Service stack
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.init_schema()
    yield database
    database.close()


def _candidate_only_stack(
    db: Database,
    reflection_service: ReflectionService | None = None,
) -> tuple[
    CanonicalWriteService,
    FormationWorker,
    ExtractionRetryService,
    ExtractionTaskRepository,
]:
    pref = PreferenceRepository(db)
    know = KnowledgeRepository(db)
    authority = LongTermAuthorityFacade(
        AuthorityRepository(
            db,
            preference_repository=pref,
            knowledge_repository=know,
        )
    )
    writer = MemoryWriteService(
        pref_repo=pref,
        know_repo=know,
        project_immediately=False,
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
        reflection_service=reflection_service
        or ReflectionService(
            model=_DeterministicReflectionModel(),
            max_retries=0,
        ),
    )
    retry = ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )
    return canonical, worker, retry, tasks


def _working_state(
    service: CanonicalWriteService,
    tenant_id: str,
    user_id: str,
    task_id: str,
) -> dict:
    row = service.working_service.repository.get(
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=task_id,
    )
    return dict(row.state) if row is not None else {}


def _episode_history(
    service: CanonicalWriteService,
    tenant_id: str,
    user_id: str,
    task_id: str,
) -> list:
    episode = service.episode_service.repository.get_by_task_id(
        tenant_id=tenant_id,
        user_id=user_id,
        task_id=task_id,
        status=None,
    )
    if episode is None:
        return []
    return service.episode_service.repository.list_events(
        tenant_id=tenant_id,
        user_id=user_id,
        episode_id=episode.episode_id,
    )


# ---------------------------------------------------------------------------
# Scenario A — 正常 Coding Task
# ---------------------------------------------------------------------------


def test_scenario_a_normal_coding_task(db: Database) -> None:
    """正常 Coding Task：目标 -> 读文件 -> 修改 -> 测试通过 -> Task Complete。"""

    tenant_id = "tenant-scenario-a"
    user_id = "user-scenario-a"
    task_id = "task-scenario-a"
    canonical, _worker, retry, tasks = _candidate_only_stack(db)

    events = [
        _event(
            "a-goal",
            {"text": "Fix SSE reconnect issue"},
            event_type="user_instruction",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-read-config",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "application.yaml"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-read-handler",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "sse_handler.py"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-test-failed",
            {
                "tool_calls": [
                    _tool(
                        "bash",
                        "error",
                        arguments={"command": "pytest tests/test_sse.py"},
                        error="AssertionError: reconnect timeout",
                    )
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-patch-timeout",
            {
                "tool_calls": [
                    _tool("apply_patch", "success", arguments={"path": "application.yaml"})
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-test-passed",
            {
                "tool_calls": [
                    _tool("bash", "success", arguments={"command": "pytest tests/test_sse.py"})
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "a-complete",
            {"text": "SSE reconnect issue fixed"},
            event_type="task_completed",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
    ]
    for event in events:
        canonical.write(event)

    run = retry.run_due(user_id=user_id)
    state = _working_state(canonical, tenant_id, user_id, task_id)
    history = _episode_history(canonical, tenant_id, user_id, task_id)
    reflection_tasks = tasks.list(user_id=user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=tenant_id, user_id=user_id
    )

    # Working State 表达了任务进展，而不是 Event Log。
    assert state.get("current_goal") == "Fix SSE reconnect issue"
    assert "Read application.yaml" in state.get("completed_steps", [])
    assert "Read sse_handler.py" in state.get("completed_steps", [])
    assert "Updated application.yaml" in state.get("completed_steps", [])
    assert "Test passed: pytest tests/test_sse.py" in state.get("completed_steps", [])
    assert any(
        "reconnect timeout" in failure for failure in state.get("recent_failures", [])
    )
    assert state.get("blockers") == []
    assert "tool_calls" not in state

    # Episode 保留关键过程、成功/失败与修改对象。
    assert len(history) == len(events)
    history_summaries = [item.payload.get("summary", "") for item in history]
    assert any("Fix SSE reconnect issue" in summary for summary in history_summaries)
    assert any("AssertionError" in str(item.payload) for item in history)
    assert all("tool_calls" not in item.payload for item in history)

    # Boundary 触发 Reflection，candidate-only 只产生 Candidate 不写 Authority。
    assert run.succeeded >= 1
    assert len(reflection_tasks) >= 1
    assert len(candidates) >= 1
    assert PreferenceRepository(db).list_all(user_id=user_id) == []
    assert KnowledgeRepository(db).list_all(user_id=user_id) == []


# ---------------------------------------------------------------------------
# Scenario B — 失败后恢复
# ---------------------------------------------------------------------------


def test_scenario_b_recovery_from_failure(db: Database) -> None:
    """失败后恢复：Command Failed -> 分析 -> 修改配置 -> Command Success。"""

    tenant_id = "tenant-scenario-b"
    user_id = "user-scenario-b"
    task_id = "task-scenario-b"
    canonical, _worker, retry, tasks = _candidate_only_stack(db)

    events = [
        _event(
            "b-goal",
            {"text": "Fix export failure"},
            event_type="user_instruction",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "b-command-failed",
            {
                "tool_calls": [
                    _tool(
                        "bash",
                        "error",
                        arguments={"command": "curl -f http://exporter/health"},
                        error="exporter returned 500",
                    )
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "b-read-log",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "exporter.log"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "b-patch-config",
            {
                "tool_calls": [
                    _tool("apply_patch", "success", arguments={"path": "config.yaml"})
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "b-command-success",
            {
                "tool_calls": [
                    _tool(
                        "bash",
                        "success",
                        arguments={"command": "curl -f http://exporter/health"},
                        summary="exporter health check passed",
                    )
                ]
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "b-complete",
            {"text": "Export failure resolved"},
            event_type="task_completed",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
    ]
    for event in events:
        canonical.write(event)

    run = retry.run_due(user_id=user_id)
    state = _working_state(canonical, tenant_id, user_id, task_id)
    history = _episode_history(canonical, tenant_id, user_id, task_id)

    # Failure 不被标记为完成，Working State 体现失败与恢复。
    assert state.get("current_goal") == "Fix export failure"
    assert any(
        "exporter returned 500" in failure for failure in state.get("recent_failures", [])
    )
    assert state.get("blockers") == []
    assert any(
        "Command succeeded: curl -f http://exporter/health" in step
        for step in state.get("completed_steps", [])
    )

    # Episode 保留关键转折。
    assert len(history) == len(events)
    assert any("exporter returned 500" in str(item.payload) for item in history)
    assert any("exporter health check passed" in str(item.payload) for item in history)

    # Task Complete 边界触发 Reflection。
    assert run.succeeded >= 1
    assert len(tasks.list(user_id=user_id)) >= 1


# ---------------------------------------------------------------------------
# Scenario C — 低价值事件
# ---------------------------------------------------------------------------


def test_scenario_c_low_value_events_do_not_trigger_reflection(db: Database) -> None:
    """低价值事件：read file -> git status -> search -> read another file。"""

    tenant_id = "tenant-scenario-c"
    user_id = "user-scenario-c"
    task_id = "task-scenario-c"
    canonical, _worker, retry, tasks = _candidate_only_stack(db)

    events = [
        _event(
            "c-read-main",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "main.py"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "c-git-status",
            {"tool_calls": [_tool("bash", "success", arguments={"command": "git status"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "c-search",
            {"tool_calls": [_tool("search", "success", arguments={"query": "TODO"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        _event(
            "c-read-readme",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "README.md"})]},
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
    ]
    for event in events:
        canonical.write(event)

    run = retry.run_due(user_id=user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=tenant_id, user_id=user_id
    )

    # 普通低价值事件不逐条触发 Reflection，也不形成 Candidate。
    assert run.succeeded == 0
    assert tasks.list(user_id=user_id) == []
    assert candidates == []


# ---------------------------------------------------------------------------
# Scenario D — Explicit Remember
# ---------------------------------------------------------------------------


def test_scenario_d_explicit_remember_triggers_formation(db: Database) -> None:
    """Explicit Remember：用户明确要求记住 "这个项目以后使用 Maven"。"""

    tenant_id = "tenant-scenario-d"
    user_id = "user-scenario-d"
    task_id = "task-scenario-d"
    canonical, _worker, retry, tasks = _candidate_only_stack(db)

    canonical.write(
        _event(
            "d-goal",
            {"text": "Set up project build"},
            event_type="user_instruction",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )
    result = canonical.write(
        _event(
            "d-remember",
            {
                "boundary": "explicit",
                "text": "This project uses Maven",
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )

    assert result.reflection_task is not None

    run = retry.run_due(user_id=user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=tenant_id, user_id=user_id
    )

    # 显式 remember 触发 Formation，产生 Candidate。
    assert run.succeeded >= 1
    assert len(candidates) >= 1
    # Scope 不应无条件扩成 global。
    assert all(
        candidate.scope_level != MemoryScope.GLOBAL.value for candidate in candidates
    )


# ---------------------------------------------------------------------------
# Scenario E — candidate-only
# ---------------------------------------------------------------------------


def test_scenario_e_candidate_only_does_not_write_authority(db: Database) -> None:
    """candidate-only：Candidate 被创建，但 Long-Term Authority 未被写入。"""

    tenant_id = "tenant-scenario-e"
    user_id = "user-scenario-e"
    task_id = "task-scenario-e"
    canonical, _worker, retry, tasks = _candidate_only_stack(db)

    canonical.write(
        _event(
            "e-goal",
            {"text": "Set up project build"},
            event_type="user_instruction",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )
    result = canonical.write(
        _event(
            "e-remember",
            {
                "boundary": "explicit",
                "text": "This project uses Maven",
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )

    assert result.reflection_task is not None

    run = retry.run_due(user_id=user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=tenant_id, user_id=user_id
    )

    # candidate-only 模式下 Reflection 产生 Candidate，但不写 Long-Term Authority。
    assert run.succeeded >= 1
    assert len(candidates) >= 1
    assert PreferenceRepository(db).list_all(user_id=user_id) == []
    assert KnowledgeRepository(db).list_all(user_id=user_id) == []


# ---------------------------------------------------------------------------
# Scenario F — LLM Invalid Output
# ---------------------------------------------------------------------------


def test_scenario_f_invalid_reflection_does_not_create_dirty_candidate(
    db: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LLM Invalid Output：schema 验证失败，不产生脏 Candidate，存在可观测记录。"""

    tenant_id = "tenant-scenario-f"
    user_id = "user-scenario-f"
    task_id = "task-scenario-f"
    invalid_service = ReflectionService(
        model=_InvalidReflectionModel(),
        max_retries=0,
    )
    canonical, _worker, retry, tasks = _candidate_only_stack(
        db, reflection_service=invalid_service
    )

    canonical.write(
        _event(
            "f-goal",
            {"text": "Remember my preference"},
            event_type="user_instruction",
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )
    result = canonical.write(
        _event(
            "f-remember",
            {
                "boundary": "explicit",
                "text": "Always use dark mode",
            },
            task_id=task_id,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    )

    assert result.reflection_task is not None

    with caplog.at_level(logging.WARNING, logger="memoryhub.application.reflection_service"):
        run = retry.run_due(user_id=user_id)

    candidates = CandidateRepository(db).list_for_review(
        tenant_id=tenant_id, user_id=user_id
    )

    # 非法 Reflection 不产生 Candidate，任务进入 retry，并有可观测日志。
    assert run.retried >= 1
    assert candidates == []
    assert any(
        "structured_reflection_failed" in record.message
        for record in caplog.records
    )
