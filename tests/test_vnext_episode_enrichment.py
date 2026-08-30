from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_enricher import EpisodeEventEnricher
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import ReflectionService
from memoryhub.application.working_service import WorkingService
from memoryhub.core.reflection.prompts import PROMPT_VERSION
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository


def _event(
    event_id: str,
    payload: dict,
    *,
    event_type: str = "agent_response",
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-episode",
        user_id="user-episode",
        event_id=event_id,
        event_type=event_type,
        source_type="tool_result",
        task_id="task-episode",
        session_id="session-episode",
        occurred_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        payload=payload,
        policy_action="ALLOW",
        source_hash="e" * 64,
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def test_enricher_compacts_tool_success_failure_and_large_output() -> None:
    enriched = EpisodeEventEnricher().enrich(
        _event(
            "event-enricher",
            {
                "phase": "verification",
                "tool_calls": [
                    {
                        "tool_name": "read_file",
                        "status": "success",
                        "arguments": {"path": "application.yaml"},
                        "output": "x" * 500,
                    },
                    {
                        "tool_name": "bash",
                        "status": "error",
                        "arguments": {"command": "pytest tests/test_sse.py"},
                        "error": "AssertionError: reconnect timeout",
                    },
                ],
            }
        )
    )

    assert enriched["source_event_type"] == "agent_response"
    assert enriched["phase"] == "verification"
    assert enriched["state_transition"] == {"phase": "verification"}
    assert enriched["actions"] == [
        {
            "tool_name": "read_file",
            "target": "application.yaml",
            "action": "Read application.yaml",
            "result": "SUCCESS",
            "success": True,
            "output_summary": "x" * 160,
        },
        {
            "tool_name": "bash",
            "target": "pytest tests/test_sse.py",
            "action": "Test failed: pytest tests/test_sse.py",
            "result": "FAILURE",
            "success": False,
            "error_summary": "AssertionError: reconnect timeout",
        },
    ]
    assert "tool_calls" not in enriched
    assert len(enriched["summary"]) <= 160


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.init_schema()
    yield database
    database.close()


def _service(db: Database) -> CanonicalWriteService:
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
    )


def _tool(name: str, status: str, *, arguments: dict | None = None, **extra: object) -> dict:
    return {
        "tool_name": name,
        "status": status,
        "arguments": arguments or {},
        **extra,
    }


def test_canonical_write_persists_compact_episode_history_for_tool_trace(db: Database) -> None:
    service = _service(db)
    events = [
        _event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction"),
        _event(
            "read-config",
            {"tool_calls": [_tool("read_file", "success", arguments={"path": "application.yaml"})]},
        ),
        _event(
            "test-failed",
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
        ),
        _event(
            "update-timeout",
            {
                "tool_calls": [
                    _tool("apply_patch", "success", arguments={"path": "application.yaml"})
                ]
            },
        ),
        _event(
            "test-passed",
            {
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

    episode = service.episode_service.repository.get_by_task_id(
        tenant_id="tenant-episode", user_id="user-episode", task_id="task-episode"
    )
    assert episode is not None
    history = service.episode_service.repository.list_events(
        tenant_id="tenant-episode", user_id="user-episode", episode_id=episode.episode_id
    )
    assert [item.source_event_id for item in history] == [event.event_id for event in events]
    assert history[0].payload["summary"] == "Repair SSE reconnect"
    assert history[1].payload["actions"][0]["action"] == "Read application.yaml"
    assert history[2].payload["actions"][0]["error_summary"] == "AssertionError: reconnect timeout"
    assert history[3].payload["actions"][0]["action"] == "Updated application.yaml"
    assert history[4].payload["actions"][0]["action"] == "Test passed: pytest tests/test_sse.py"
    assert all("tool_calls" not in item.payload for item in history)


def test_formation_receives_enriched_episode_history(db: Database) -> None:
    class CapturingModel:
        model_id = "capturing-reflection/v1"

        def __init__(self) -> None:
            self.inputs = []

        def generate(self, _prompt, *, input_hash, input_data=None):
            self.inputs.append(input_data)
            return {
                "candidate_id": "candidate-episode-history",
                "memory_type": "PROCEDURAL",
                "normalized_key": "procedure:episode-history",
                "claim": {"steps": ["inspect", "repair"]},
                "scope_level": "TASK",
                "scope": "TASK:task-episode",
                "confidence": 0.8,
                "utility": 0.7,
                "stability": 0.6,
                "model_id": self.model_id,
                "prompt_version": PROMPT_VERSION,
                "input_hash": input_hash,
                "reason": "captured enriched episode history",
            }

    service = _service(db)
    service.write(_event("goal", {"text": "Repair SSE reconnect"}, event_type="user_instruction"))
    failure_event = _event(
        "test-failed",
        {
            "boundary": "explicit",
            "tool_calls": [
                _tool(
                    "bash",
                    "error",
                    arguments={"command": "pytest tests/test_sse.py"},
                    error="AssertionError: reconnect timeout",
                )
            ],
        },
    )
    result = service.write(failure_event)
    model = CapturingModel()
    worker = FormationWorker(
        db,
        canonical_write_service=service,
        reflection_service=ReflectionService(model=model, max_retries=0),
    )

    assert result.reflection_task is not None
    worker.execute(result.reflection_task, [failure_event])

    assert len(model.inputs) == 1
    history = model.inputs[0].episode_history_summary
    assert history[1]["payload"]["actions"][0]["action"] == "Test failed: pytest tests/test_sse.py"
    assert "tool_calls" not in history[1]["payload"]
