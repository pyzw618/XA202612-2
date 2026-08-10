"""Normalize cleaned source dictionaries into complete Schema 1.1 events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
    ToolCallResult,
    ToolCallStatus,
    canonical_sha256,
)
from memoryhub.core.ingestion.quality import QualityScorer


class EventNormalizer:
    """Map legacy/source-specific dictionaries to the strict MemoryEvent contract."""

    _TYPE_MAP = {
        "tool": SourceType.TOOL_RESULT,
        "tool_result": SourceType.TOOL_RESULT,
        "chat": SourceType.USER_BEHAVIOR,
        "feedback": SourceType.USER_BEHAVIOR,
        "user_behavior": SourceType.USER_BEHAVIOR,
        "manual_config": SourceType.MANUAL_CONFIG,
        "system": SourceType.TOOL_RESULT,
    }

    @classmethod
    def _source_type(cls, value) -> SourceType:
        if isinstance(value, SourceType):
            return value
        return cls._TYPE_MAP.get(str(value or "").lower(), SourceType.TOOL_RESULT)

    @staticmethod
    def _provisional_quality(value) -> EventQuality:
        if isinstance(value, EventQuality):
            return value
        if isinstance(value, dict):
            return EventQuality.model_validate(value)
        return EventQuality(
            score=0.0,
            status=QualityStatus.REVIEW,
            completeness=0.0,
            validity=0.0,
            consistency=0.0,
            freshness=0.0,
        )

    def normalize(self, cleaned: dict) -> MemoryEvent:
        """Normalize one cleaned dictionary and compute missing hash/quality fields."""
        occurred_at = cleaned.get("occurred_at") or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        source_hash = cleaned.get("source_hash") or canonical_sha256(cleaned)
        provisional = self._provisional_quality(cleaned.get("quality"))
        event = MemoryEvent(
            event_id=cleaned.get("event_id", ""),
            source_type=self._source_type(cleaned.get("source_type")),
            event_type=cleaned.get("event_type", ""),
            user_id=cleaned.get("user_id", "default"),
            session_id=cleaned.get("session_id", ""),
            turn_id=cleaned.get("turn_id", ""),
            scene=cleaned.get("scene", ""),
            task_type=cleaned.get("task_type", ""),
            occurred_at=occurred_at,
            text=cleaned.get("text", ""),
            payload=cleaned.get("payload", {}),
            tool_calls=cleaned.get("tool_calls", []),
            schema_version=cleaned.get("schema_version", "1.1"),
            source_hash=source_hash,
            redactions=cleaned.get("redactions", []),
            quality=provisional,
        )
        if cleaned.get("quality") is not None:
            return event
        quality = QualityScorer().score(event)
        return MemoryEvent.model_validate(
            {**event.model_dump(mode="json"), "quality": quality.model_dump(mode="json")}
        )

    def normalize_batch(self, cleaned_list: list[dict]) -> list[MemoryEvent]:
        return [self.normalize(entry) for entry in cleaned_list]

    def normalize_tool_result(self, tool_name: str, result: dict) -> MemoryEvent:
        """Construct a valid Schema 1.1 tool-result event from one tool response."""
        call_id = str(result.get("call_id") or f"call_{uuid.uuid4().hex[:12]}")
        raw_status = str(result.get("status", "success")).lower()
        status = ToolCallStatus(raw_status) if raw_status in ToolCallStatus._value2member_map_ else ToolCallStatus.ERROR
        raw = {
            "event_id": f"tool_{uuid.uuid4().hex[:12]}",
            "source_type": SourceType.TOOL_RESULT,
            "event_type": str(result.get("event_type") or tool_name),
            "user_id": str(result.get("user_id") or "default"),
            "session_id": str(result.get("session_id") or ""),
            "turn_id": str(result.get("turn_id") or ""),
            "scene": str(result.get("scene") or ""),
            "task_type": str(result.get("task_type") or ""),
            "occurred_at": str(result.get("occurred_at") or ""),
            "text": str(result.get("output", result.get("result", ""))),
            "payload": result,
            "tool_calls": [
                ToolCallResult(
                    call_id=call_id,
                    sequence=1,
                    tool_name=tool_name,
                    arguments=result.get("arguments", {}),
                    result=result.get("result", result.get("output")),
                    status=status,
                    error=str(result.get("error") or ""),
                ).model_dump(mode="json")
            ],
            "schema_version": "1.1",
            "redactions": result.get("redactions", []),
        }
        return self.normalize(raw)
