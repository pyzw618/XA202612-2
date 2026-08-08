from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from memoryhub.adapter.schemas import MemoryEvent, SafetyAction, SourceType
from memoryhub.core.ingestion import (
    DataCleaner,
    DataNormalizer,
    IngestionPipeline,
    QualityScorer,
)

SAMPLE_PATH = Path(__file__).parents[1] / "examples" / "raw_agent_event.json"


def load_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def fixed_pipeline() -> IngestionPipeline:
    scorer = QualityScorer(
        reference_time=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
    )
    return IngestionPipeline(normalizer=DataNormalizer(scorer))


def test_cleaner_removes_debug_fields_nulls_and_whitespace() -> None:
    cleaned = DataCleaner().clean(load_sample())

    assert "debug" not in cleaned
    assert "_debug_dump" not in cleaned
    assert "unused" not in cleaned["metadata"]
    assert cleaned["user_id"] == "demo-user"
    assert cleaned["content"]["tool_calls"][0]["input"]["query"] == (
        "MemoryHub 项目进展"
    )


def test_normalizer_converts_legacy_agent_shape_to_memory_event_1_1() -> None:
    cleaned = DataCleaner().clean(load_sample())
    event = DataNormalizer(
        QualityScorer(
            reference_time=datetime(2026, 8, 8, 9, 0, tzinfo=timezone.utc)
        )
    ).normalize(cleaned)

    assert event.source_type is SourceType.TOOL_RESULT
    assert event.schema_version == "1.1"
    assert event.session_id == "session-weekly-report-001"
    assert event.scene == "office"
    assert event.task_type == "office.weekly_report"
    assert event.occurred_at == "2026-08-08T08:30:00Z"
    assert [call.tool_name for call in event.tool_calls] == [
        "file_search",
        "calendar_read",
        "report_writer",
    ]
    assert event.quality.status.value == "accepted"
    assert event.quality.score == 1.0


def test_pipeline_masks_sensitive_values_and_returns_valid_event() -> None:
    result = fixed_pipeline().process(load_sample())

    assert result.safety_action is SafetyAction.MASK
    assert result.event is not None
    event = MemoryEvent.model_validate(result.event.model_dump(mode="python"))
    rendered = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)

    assert "13800138000" not in rendered
    assert rendered.count("[REDACTED_PHONE]") == 2
    assert event.redactions == ["phone"]
    assert {finding["field_path"] for finding in result.safety_findings} == {
        "/text",
        "/tool_calls/1/result/events/0/owner_phone",
    }


def test_cleaner_deduplicates_by_event_id_and_source_hash() -> None:
    event = fixed_pipeline().process(load_sample()).event
    assert event is not None

    assert DataCleaner().deduplicate([event, event]) == [event]
