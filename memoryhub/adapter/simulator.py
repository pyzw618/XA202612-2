"""OS Agent simulator used for demonstrations and data-flow smoke tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SearchResponse,
    SourceType,
    ToolCallResult,
)


class OSAgentSimulator:
    """Generate gate-compatible events and optionally drive a client adapter."""

    def __init__(self, client=None, *, user_id: str = "test_user") -> None:
        self.client = client
        self.user_id = user_id

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _event_contract(seed: str) -> dict:
        return {
            "source_hash": hashlib.sha256(seed.encode("utf-8")).hexdigest(),
            "quality": EventQuality(
                score=1.0,
                status=QualityStatus.ACCEPTED,
                completeness=1.0,
                validity=1.0,
                consistency=1.0,
                freshness=1.0,
            ),
        }

    def simulate_task(
        self,
        task: str,
        scene: str = "general",
        task_type: str = "general",
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> list[MemoryEvent]:
        owner = user_id or self.user_id
        session = session_id or f"sim_session_{uuid.uuid4().hex[:10]}"
        ts = self._now()
        input_id = f"sim_input_{uuid.uuid4().hex[:8]}"
        tool_id = f"sim_tool_{uuid.uuid4().hex[:8]}"
        complete_id = f"sim_complete_{uuid.uuid4().hex[:8]}"
        events = [
            MemoryEvent(
                event_id=input_id,
                source_type=SourceType.USER_BEHAVIOR,
                event_type="user_input",
                user_id=owner,
                session_id=session,
                turn_id="1",
                scene=scene,
                task_type=task_type,
                text=task,
                payload={"task": task},
                occurred_at=ts,
                **self._event_contract(input_id),
            ),
            MemoryEvent(
                event_id=tool_id,
                source_type=SourceType.TOOL_RESULT,
                event_type="file_search",
                user_id=owner,
                session_id=session,
                turn_id="2",
                scene=scene,
                task_type=task_type,
                text=f"Found files for task: {task}",
                tool_calls=[ToolCallResult(
                    call_id=f"sim_call_{uuid.uuid4().hex[:8]}",
                    tool_name="file_search",
                    arguments={"query": task},
                    result={"files_found": ["report_week_27.md", "report_week_28.md"]},
                    status="success",
                    sequence=1,
                )],
                occurred_at=ts,
                **self._event_contract(tool_id),
            ),
            MemoryEvent(
                event_id=complete_id,
                source_type=SourceType.TOOL_RESULT,
                event_type="task_completed",
                user_id=owner,
                session_id=session,
                turn_id="3",
                scene=scene,
                task_type=task_type,
                text=f"Completed: {task}",
                payload={"success": True},
                tool_calls=[ToolCallResult(
                    call_id=f"sim_complete_call_{uuid.uuid4().hex[:8]}",
                    tool_name="task_runner",
                    arguments={"task": task},
                    result={"success": True},
                    status="success",
                    sequence=1,
                )],
                occurred_at=ts,
                **self._event_contract(complete_id),
            ),
        ]
        if self.client is not None:
            writer = getattr(self.client, "write_events", None) or getattr(self.client, "write_event", None)
            if callable(writer):
                writer(events)
        return events

    def simulate_conversation(
        self,
        turns: list[str],
        scene: str = "chat",
        task_type: str = "conversation",
    ) -> list[MemoryEvent]:
        session = f"sim_session_{uuid.uuid4().hex[:10]}"
        events: list[MemoryEvent] = []
        for turn_text in turns:
            events.extend(self.simulate_task(
                turn_text,
                scene=scene,
                task_type=task_type,
                session_id=session,
            ))
        return events

    def simulate_search(self, query: str, scene: str = "general") -> SearchResponse:
        if self.client is not None:
            search = getattr(self.client, "search", None)
            if callable(search):
                return search(query=query, scene=scene, user_id=self.user_id)
        return SearchResponse(preferences=[], knowledge=[], facts=[], latency_ms=0.0)

    def simulate_error(self, error_message: str = "Simulated error") -> MemoryEvent:
        event_id = f"sim_error_{uuid.uuid4().hex[:8]}"
        return MemoryEvent(
            event_id=event_id,
            source_type=SourceType.TOOL_RESULT,
            event_type="error",
            user_id=self.user_id,
            text=error_message,
            payload={"success": False, "error_code": "simulated.error"},
            occurred_at=self._now(),
            **self._event_contract(event_id),
        )

    def simulate_feedback(
        self,
        memory_id: str,
        feedback_text: str,
        action: str = "update",
        user_id: str | None = None,
    ) -> dict:
        payload = {
            "user_id": user_id or self.user_id,
            "memory_id": memory_id,
            "feedback_text": feedback_text,
            "action": action,
        }
        if self.client is not None:
            feedback = getattr(self.client, "feedback", None)
            if callable(feedback):
                feedback(**payload)
        return payload
