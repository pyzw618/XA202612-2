from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.working_reducer import WorkingStateReducer
from memoryhub.application.working_service import WorkingService
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository

ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db() -> Database:
    db_path = ROOT / "evaluation" / "results" / "vnext_working_reducer_test.db"
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    database = Database(str(db_path))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def _event(
    event_id: str,
    *,
    event_type: str = "agent_response",
    payload: dict | None = None,
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-reducer",
        user_id="user-reducer",
        event_id=event_id,
        event_type=event_type,
        source_type="tool_result",
        task_id="task-reducer",
        session_id="session-reducer",
        occurred_at=datetime.now(timezone.utc),
        payload=payload or {},
        policy_action="ALLOW",
        source_hash=(event_id + "0" * 64)[:64],
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def _tool(name: str, status: str, *, arguments: dict | None = None, **extra) -> dict:
    return {
        "tool_name": name,
        "status": status,
        "arguments": arguments or {},
        **extra,
    }


def _service(db: Database) -> CanonicalWriteService:
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
    )


def _operation_value(operations, path: str):
    return next(operation.value for operation in operations if operation.path == path)


def test_reducer_generates_deterministic_tool_failure_and_terminal_patches() -> None:
    reducer = WorkingStateReducer()
    current = {
        "current_goal": "repair SSE reconnect",
        "current_step": "inspect handler",
        "pending_steps": [],
        "completed_steps": [],
        "constraints": [],
        "active_entities": [],
        "blockers": [],
        "recent_findings": [],
        "recent_failures": [],
        "next_action": "",
    }
    failed = _event(
        "tool-failed",
        payload={
            "tool_calls": [
                _tool(
                    "bash",
                    "error",
                    arguments={"command": "pytest tests/test_sse.py"},
                    error="AssertionError: reconnect timeout",
                )
            ]
        },
    )

    patch = reducer.patch(failed, current, base_version=1)

    assert patch is not None
    assert "/completed_steps" not in {operation.path for operation in patch.operations}
    assert _operation_value(patch.operations, "/recent_failures") == [
        "Test failed: pytest tests/test_sse.py: AssertionError: reconnect timeout"
    ]
    assert _operation_value(patch.operations, "/blockers") == ["bash: pytest tests/test_sse.py"]
    assert _operation_value(patch.operations, "/next_action") == (
        "Investigate test failed: pytest tests/test_sse.py"
    )

    completed = reducer.patch(
        _event("task-complete", event_type="task_completed"), current, base_version=1
    )

    assert completed is not None
    assert _operation_value(completed.operations, "/completed_steps") == ["Task completed"]
    assert _operation_value(completed.operations, "/blockers") == []


def test_canonical_write_persists_project_on_working_and_episode(db: Database) -> None:
    service = _service(db)
    service.write(
        _event(
            "project-bound-event",
            event_type="user_instruction",
            payload={"text": "Repair project B", "project_id": "project-b"},
        )
    )

    working = service.working_service.repository.get(
        tenant_id="tenant-reducer",
        user_id="user-reducer",
        task_id="task-reducer",
    )
    episode = service.episode_service.repository.get_by_task_id(
        tenant_id="tenant-reducer",
        user_id="user-reducer",
        task_id="task-reducer",
    )
    assert working is not None and working.project_id == "project-b"
    assert episode is not None and episode.project_id == "project-b"


def test_canonical_tool_trace_evolves_working_state_and_is_idempotent(db: Database) -> None:
    service = _service(db)
    service.write(
        _event(
            "goal",
            event_type="user_instruction",
            payload={"text": "Repair SSE reconnect"},
        )
    )
    events = [
        _event(
            "read-config",
            payload={
                "tool_calls": [
                    _tool("read_file", "success", arguments={"path": "application.yaml"})
                ]
            },
        ),
        _event(
            "read-handler",
            payload={
                "tool_calls": [
                    _tool("read_file", "success", arguments={"path": "sse_handler.py"})
                ]
            },
        ),
        _event(
            "test-failed",
            payload={
                "tool_calls": [
                    _tool(
                        "bash",
                        "error",
                        arguments={"command": "pytest tests/test_sse.py"},
                        error="AssertionError: reconnect timeout",
                    )
                ]
            },
        ),
        _event(
            "update-timeout",
            payload={
                "tool_calls": [
                    _tool("apply_patch", "success", arguments={"path": "application.yaml"})
                ]
            },
        ),
        _event(
            "test-passed",
            payload={
                "tool_calls": [
                    _tool(
                        "bash",
                        "success",
                        arguments={"command": "pytest tests/test_sse.py"},
                    )
                ]
            },
        ),
    ]
    for event in events:
        service.write(event)

    working = service.working_service.repository.get(
        tenant_id="tenant-reducer", user_id="user-reducer", task_id="task-reducer"
    )
    assert working is not None
    state = working.state
    assert state["current_goal"] == "Repair SSE reconnect"
    assert state["completed_steps"] == [
        "Read application.yaml",
        "Read sse_handler.py",
        "Updated application.yaml",
        "Test passed: pytest tests/test_sse.py",
    ]
    assert state["recent_failures"] == [
        "Test failed: pytest tests/test_sse.py: AssertionError: reconnect timeout"
    ]
    assert state["active_entities"] == ["application.yaml", "sse_handler.py"]
    assert state["blockers"] == []
    assert state["current_step"] == "Test passed: pytest tests/test_sse.py"
    assert state["next_action"] == "Verify remaining task steps"
    assert "tool_calls" not in state

    replay = service.write(events[-1])
    unchanged = service.working_service.repository.get(
        tenant_id="tenant-reducer", user_id="user-reducer", task_id="task-reducer"
    )
    assert replay.status.value == "IDEMPOTENT"
    assert unchanged is not None and unchanged.version == working.version
