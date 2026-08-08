from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from integrations.agents.trace_adapter import build_agent_event, build_user_event
from memoryhub.adapter.schemas import MemoryEvent


@dataclass
class FakeMessage:
    type: str
    content: Any
    tool_calls: list[dict] = field(default_factory=list)
    tool_call_id: str = ""
    status: str = "success"


def test_langgraph_trace_becomes_canonical_memory_event() -> None:
    messages = [
        FakeMessage(
            type="ai",
            content="",
            tool_calls=[
                {"id": "call-001", "name": "file_search", "args": {"query": "周报"}}
            ],
        ),
        FakeMessage(
            type="tool",
            content='{"matches": [{"path": "project_notes.md"}]}',
            tool_call_id="call-001",
        ),
        FakeMessage(type="ai", content="报告已写入 outputs/weekly_report.md"),
    ]

    raw_event = build_agent_event(
        messages,
        user_id="u-001",
        session_id="session-001",
        turn_id="turn-001",
        scene="office",
        task_type="office.weekly_report",
        model="qwen-plus",
    )

    event = MemoryEvent.model_validate(raw_event)
    assert event.event_type == "agent_response"
    assert event.tool_calls[0].tool_name == "file_search"
    assert event.tool_calls[0].arguments == {"query": "周报"}
    assert event.tool_calls[0].result["matches"][0]["path"] == "project_notes.md"
    assert "weekly_report.md" in event.text


def test_user_input_becomes_user_behavior_event() -> None:
    raw_event = build_user_event(
        "以后周报都使用 Markdown",
        user_id="u-001",
        session_id="session-001",
        turn_id="turn-001",
        scene="office",
        task_type="office.weekly_report",
    )

    event = MemoryEvent.model_validate(raw_event)
    assert event.source_type.value == "user_behavior"
    assert event.payload["role"] == "user"
