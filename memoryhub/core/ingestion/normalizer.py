"""Normalize cleaned source dictionaries into complete Schema 1.1 events."""

from __future__ import annotations

import json

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
    ToolCallResult,
    ToolCallStatus,
    canonical_sha256,
)


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
        normalized = str(value or "").strip().lower()
        if normalized not in cls._TYPE_MAP:
            raise ValueError(f"unsupported source_type: {value!r}")
        return cls._TYPE_MAP[normalized]

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

    @classmethod
    def _hash_material(cls, cleaned: dict) -> dict:
        """Exclude caller-controlled IDs, hashes and provisional quality from idempotency."""
        return {
            "source_type": cls._source_type(cleaned.get("source_type")).value,
            "event_type": str(cleaned.get("event_type", "")),
            "user_id": str(cleaned.get("user_id", "default")),
            "session_id": str(cleaned.get("session_id", "")),
            "turn_id": str(cleaned.get("turn_id", "")),
            "scene": str(cleaned.get("scene", "")),
            "task_type": str(cleaned.get("task_type", "")),
            "occurred_at": str(cleaned.get("occurred_at", "")),
            "text": str(cleaned.get("text", "")),
            "payload": cleaned.get("payload", {}),
            "tool_calls": cleaned.get("tool_calls", []),
            "schema_version": str(cleaned.get("schema_version", "1.1")),
            "redactions": cleaned.get("redactions", []),
        }

    def normalize(self, cleaned: dict) -> MemoryEvent:
        """Normalize one cleaned dictionary and compute missing hash/quality fields."""
        # An absent occurred_at is semantically unknown, not "happened now".
        occurred_at = str(cleaned.get("occurred_at") or "")
        source_hash = canonical_sha256(self._hash_material(cleaned))
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
        # EventIngestionService is the sole authoritative quality gate.  Keep only
        # a provisional quality here so normalization is deterministic and replayable.
        return event

    def normalize_batch(self, cleaned_list: list[dict]) -> list[MemoryEvent]:
        return [self.normalize(entry) for entry in cleaned_list]

    def normalize_tool_result(self, tool_name: str, result: dict) -> MemoryEvent:
        """Construct a deterministic Schema 1.1 event from one tool response."""
        if not isinstance(result, dict):
            raise ValueError("tool result must be an object")
        raw_status = str(result.get("status", "success")).lower()
        status = (
            ToolCallStatus(raw_status)
            if raw_status in ToolCallStatus._value2member_map_
            else ToolCallStatus.ERROR
        )
        stable_call = (
            result.get("call_id") or result.get("request_id") or result.get("trace_id")
        )
        stable_material = {
            "tool_name": tool_name,
            "call_id": stable_call or "",
            "user_id": result.get("user_id", "default"),
            "session_id": result.get("session_id", ""),
            "occurred_at": result.get("occurred_at", ""),
            "arguments": result.get("arguments", {}),
            "result": result.get("result", result.get("output")),
            "status": status.value,
        }
        digest = canonical_sha256(stable_material)
        call_id = str(stable_call or f"call_{digest[:16]}")
        output = result.get("output", result.get("result", ""))
        text = (
            output
            if isinstance(output, str)
            else json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
        )
        raw = {
            "event_id": str(result.get("event_id") or f"tool_{digest[:24]}"),
            "source_type": SourceType.TOOL_RESULT,
            "event_type": str(result.get("event_type") or tool_name),
            "user_id": str(result.get("user_id") or "default"),
            "session_id": str(result.get("session_id") or ""),
            "turn_id": str(result.get("turn_id") or ""),
            "scene": str(result.get("scene") or ""),
            "task_type": str(result.get("task_type") or ""),
            "occurred_at": str(result.get("occurred_at") or ""),
            "text": text,
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
