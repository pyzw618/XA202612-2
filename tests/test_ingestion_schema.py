import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    ToolCallStatus,
)


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
        "response_status": "success",
    }
    if source_type == "user_behavior":
        payload = {"action": "message", "role": "user"}
    elif source_type == "manual_config":
        payload = {"key": "report.format", "value": "Markdown"}
    tool_calls = []
    if source_type == "tool_result":
        tool_calls = [
            {
                "call_id": "call-001",
                "tool_name": "file_search",
                "arguments": {"query": "weekly report"},
                "result": {"files": ["weekly-report.docx"]},
                "status": "success",
                "sequence": 1,
            }
        ]
    return {
        "event_id": "evt_schema_001",
        "source_type": source_type,
        "event_type": "tool_result" if source_type == "tool_result" else "user_action",
        "user_id": "u-001",
        "session_id": "session-001",
        "turn_id": "turn-001",
        "scene": "office",
        "task_type": "weekly_report",
        "occurred_at": "2026-07-20T00:00:00Z",
        "text": "found 3 files",
        "payload": payload,
        "tool_calls": tool_calls,
        "schema_version": "1.1",
        "source_hash": "a" * 64,
        "redactions": [],
        "quality": quality(),
    }


@pytest.mark.parametrize(
    "source_type", ["tool_result", "user_behavior", "manual_config"]
)
def test_canonical_event_supports_all_ingestion_sources(source_type: str) -> None:
    event = MemoryEvent.model_validate(canonical_event(source_type))

    assert event.source_type.value == source_type
    assert event.quality.status is QualityStatus.ACCEPTED
    assert event.model_dump(mode="json")["schema_version"] == "1.1"


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


def test_multiple_tool_results_keep_name_arguments_result_and_order() -> None:
    event_data = canonical_event()
    event_data["text"] = "已根据检索结果生成最终回答"
    event_data["payload"] = {"response_status": "success"}
    event_data["tool_calls"] = [
        {
            "call_id": "call-001",
            "tool_name": "file_search",
            "arguments": {"query": "项目周报"},
            "result": {"files": ["weekly-report.docx"]},
            "status": "success",
            "sequence": 1,
        },
        {
            "call_id": "call-002",
            "tool_name": "calendar_read",
            "arguments": {"range": "2026-07-20/2026-07-26"},
            "result": {"events": [{"title": "周会"}]},
            "status": "success",
            "sequence": 2,
        },
    ]

    event = MemoryEvent.model_validate(event_data)

    assert [call.tool_name for call in event.tool_calls] == [
        "file_search",
        "calendar_read",
    ]
    assert event.tool_calls[0].result == {"files": ["weekly-report.docx"]}
    assert event.tool_calls[1].arguments["range"] == "2026-07-20/2026-07-26"
    assert event.tool_calls[0].status is ToolCallStatus.SUCCESS
    assert [call.sequence for call in event.tool_calls] == [1, 2]


def test_legacy_schema_1_0_tool_result_without_tool_calls_remains_readable() -> None:
    event_data = canonical_event()
    event_data["schema_version"] = "1.0"
    event_data["tool_calls"] = []
    event_data["payload"] = {
        "tool_name": "file_search",
        "status": "success",
        "output": "found 3 files",
    }

    event = MemoryEvent.model_validate(event_data)

    assert event.schema_version == "1.0"


def test_schema_1_1_tool_result_requires_tool_calls() -> None:
    event_data = canonical_event()
    event_data["tool_calls"] = []

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


@pytest.mark.parametrize(
    ("second_call_id", "second_sequence"),
    [("call-001", 2), ("call-002", 1)],
)
def test_tool_call_ids_and_sequences_must_be_unique(
    second_call_id: str, second_sequence: int
) -> None:
    event_data = canonical_event()
    event_data["tool_calls"] = [
        {
            "call_id": "call-001",
            "tool_name": "file_search",
            "result": "first",
            "status": "success",
            "sequence": 1,
        },
        {
            "call_id": second_call_id,
            "tool_name": "calendar_read",
            "result": "second",
            "status": "success",
            "sequence": second_sequence,
        },
    ]

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_tool_calls_must_be_in_sequence_order() -> None:
    event_data = canonical_event()
    event_data["tool_calls"] = [
        {
            "call_id": "call-002",
            "tool_name": "calendar_read",
            "result": "second",
            "status": "success",
            "sequence": 2,
        },
        {
            "call_id": "call-001",
            "tool_name": "file_search",
            "result": "first",
            "status": "success",
            "sequence": 1,
        },
    ]

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_agent_response_cannot_only_contain_a_coarse_final_answer() -> None:
    event_data = canonical_event()
    event_data["event_type"] = "agent_response"
    event_data["text"] = "只有最终回答，没有工具调用明细"
    event_data["tool_calls"] = []

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


def test_tool_calls_are_restricted_to_tool_result_events() -> None:
    event_data = canonical_event("user_behavior")
    event_data["tool_calls"] = [
        {
            "call_id": "call-001",
            "tool_name": "file_search",
            "result": "not allowed here",
            "status": "success",
            "sequence": 1,
        }
    ]

    with pytest.raises(ValidationError):
        MemoryEvent.model_validate(event_data)


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


def test_normalizer_rejects_unknown_source_type_and_ignores_supplied_hash():
    from memoryhub.core.ingestion.normalizer import EventNormalizer

    raw = canonical_event("user_behavior")
    raw["source_hash"] = "b" * 64
    normalized = EventNormalizer().normalize(raw)
    assert normalized.source_hash != "b" * 64

    raw["source_type"] = "untrusted_external"
    with pytest.raises(ValueError, match="unsupported source_type"):
        EventNormalizer().normalize(raw)


def test_tool_normalization_is_deterministic_and_preserves_missing_event_time():
    from memoryhub.core.ingestion.normalizer import EventNormalizer

    result = {
        "request_id": "request-1",
        "user_id": "u-1",
        "arguments": {"query": "report"},
        "result": {"files": ["weekly.md"]},
        "status": "success",
    }
    normalizer = EventNormalizer()
    first = normalizer.normalize_tool_result("file_search", result)
    second = normalizer.normalize_tool_result("file_search", result)
    assert first.event_id == second.event_id
    assert first.tool_calls[0].call_id == second.tool_calls[0].call_id
    assert first.source_hash == second.source_hash
    assert first.occurred_at == ""
    assert first.text == '{"files": ["weekly.md"]}'


def test_quality_scorer_caps_partial_and_rejects_failed_tool_calls():
    from memoryhub.core.ingestion.quality import QualityScorer

    partial = canonical_event()
    partial["tool_calls"][0]["status"] = "partial"
    partial_event = MemoryEvent.model_validate(partial)
    partial_quality = QualityScorer().score(partial_event)
    assert partial_quality.status is QualityStatus.REVIEW
    assert partial_quality.score <= 0.60

    failed = canonical_event()
    failed["tool_calls"][0]["status"] = "timeout"
    failed_event = MemoryEvent.model_validate(failed)
    failed_quality = QualityScorer().score(failed_event)
    assert failed_quality.status is QualityStatus.REJECTED
    assert failed_quality.score <= QualityScorer.MIN_QUALITY_SCORE
