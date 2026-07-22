import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus, SourceType


def quality(status: str = "accepted") -> dict:
    return {
        "score": 0.94,
        "status": status,
        "completeness": 1.0,
        "validity": 1.0,
        "consistency": 1.0,
        "freshness": 0.4,
        "issues": ["freshness:stale_event"] if status == "accepted" else [],
    }


def canonical_event(source_type: str = "tool_result") -> dict:
    payload = {
        "tool_name": "file_search",
        "status": "success",
        "output": "found 3 files",
    }
    if source_type == "user_behavior":
        payload = {"action": "message", "role": "user"}
    elif source_type == "manual_config":
        payload = {"key": "report.format", "value": "Markdown"}
    return {
        "event_id": "evt_schema_001",
        "source_type": source_type,
        "event_type": "tool_result" if source_type == "tool_result" else "user_action",
        "user_id": "u-001",
        "session_id": "session-001",
        "scene": "office",
        "task_type": "weekly_report",
        "occurred_at": "2026-07-20T00:00:00Z",
        "text": "found 3 files",
        "payload": payload,
        "schema_version": "1.0",
        "source_hash": "a" * 64,
        "redactions": [],
        "quality": quality(),
    }


@pytest.mark.parametrize("source_type", ["tool_result", "user_behavior", "manual_config"])
def test_canonical_event_supports_all_ingestion_sources(source_type: str) -> None:
    event = MemoryEvent.model_validate(canonical_event(source_type))

    assert event.source_type.value == source_type
    assert event.quality.status is QualityStatus.ACCEPTED
    assert event.model_dump(mode="json")["schema_version"] == "1.0"


def test_quality_is_a_nested_contract() -> None:
    report = EventQuality.model_validate(quality())

    assert report.score == pytest.approx(0.94)
    assert report.freshness == pytest.approx(0.4)
    assert report.status is QualityStatus.ACCEPTED


def test_payload_keeps_source_specific_and_unknown_fields() -> None:
    event_data = canonical_event()
    event_data["payload"]["provider_trace_id"] = "trace-001"

    event = MemoryEvent.model_validate(event_data)

    assert event.payload["provider_trace_id"] == "trace-001"


def test_legacy_top_level_fields_are_rejected() -> None:
    event_data = canonical_event()
    event_data.update(
        {
            "source": "os_agent",
            "content": {"tool_name": "file_search"},
            "timestamp": "2026-07-20T00:00:00",
            "quality_score": 0.94,
        }
    )

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_invalid_timestamp_can_be_represented_as_empty_for_review() -> None:
    event_data = canonical_event()
    event_data["occurred_at"] = ""
    event_data["quality"] = quality("review")

    event = MemoryEvent.model_validate(event_data)

    assert event.occurred_at == ""
    assert event.quality.status is QualityStatus.REVIEW


def test_accepted_event_requires_identity_time_and_payload() -> None:
    event_data = canonical_event()
    event_data["occurred_at"] = ""

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_non_utc_or_non_second_timestamp_is_rejected() -> None:
    event_data = canonical_event()
    event_data["occurred_at"] = "2026-07-20T08:00:00+08:00"

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_quality_scores_are_bounded() -> None:
    event_data = canonical_event()
    event_data["quality"]["validity"] = 1.1

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)
