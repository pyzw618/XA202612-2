from __future__ import annotations

from datetime import timedelta

import pytest

from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
from memoryhub.observability.trace_policy import TraceCategory, TraceSamplingPolicy
from memoryhub.observability.trace_store import TraceStore


def test_trace_span_has_no_raw_text_field() -> None:
    span = TraceSpan(
        span_id="span-1",
        trace_id="trace-1",
        kind=TraceSpanKind.EVENT,
        tenant_id="tenant-a",
        user_id="user-a",
        ids={"event_id": "event-1"},
        hashes={"source_hash": "deadbeef"},
    )
    assert "text" not in span.model_dump()
    assert span.redacted is True


def test_trace_store_indexes_by_event_and_candidate() -> None:
    store = TraceStore()
    event = TraceSpan(
        span_id="span-event-1",
        trace_id="trace-1",
        kind=TraceSpanKind.EVENT,
        tenant_id="tenant-a",
        user_id="user-a",
        ids={"event_id": "event-1"},
        hashes={"source_hash": "deadbeef"},
    )
    candidate = TraceSpan(
        span_id="span-candidate-1",
        trace_id="trace-1",
        parent_id="span-event-1",
        kind=TraceSpanKind.CANDIDATE,
        tenant_id="tenant-a",
        user_id="user-a",
        ids={"event_id": "event-1", "candidate_id": "candidate-1"},
        hashes={"claim_hash": "cafebabe"},
    )
    store.record(event)
    store.record(candidate)

    assert store.get("span-event-1") is event
    assert store.list_by_trace("trace-1") == [event, candidate]
    assert store.list_by_event("event-1") == [event, candidate]
    assert store.list_by_candidate("candidate-1") == [candidate]


def test_formation_chain_is_ordered_by_time() -> None:
    store = TraceStore()
    event = store.record_event(
        trace_id="trace-1",
        tenant_id="tenant-a",
        user_id="user-a",
        event_id="event-1",
        event_type="user_instruction",
        source_type="user_behavior",
        policy_action="ALLOW",
        source_hash="deadbeef",
    )
    store.record_candidate(
        trace_id="trace-1",
        tenant_id="tenant-a",
        user_id="user-a",
        event_id="event-1",
        candidate_id="candidate-1",
        memory_type="PREFERENCE",
        normalized_key="format:docx",
        scope_level="PROJECT",
        scope="PROJECT:reporting",
        confidence=0.7,
        utility=0.6,
        stability=0.5,
        frequency=1,
        claim={"format": "DOCX"},
        parent_id=event.span_id,
    )

    chain = store.formation_chain("event-1")
    assert [span.kind for span in chain] == ["EVENT", "CANDIDATE"]
    for span in chain:
        assert span.redacted is True
        assert "text" not in span.hashes


def test_trace_dump_and_load_preserves_redaction() -> None:
    import tempfile

    store = TraceStore()
    store.record_event(
        trace_id="trace-1",
        tenant_id="tenant-a",
        user_id="user-a",
        event_id="event-1",
        event_type="user_instruction",
        source_type="user_behavior",
        policy_action="ALLOW",
        source_hash="deadbeef",
    )

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False) as f:
        path = f.name
    store.dump(path)

    loaded = TraceStore()
    loaded.load(path)
    assert len(loaded.records) == 1
    assert loaded.records[0].event_id == "event-1"
    assert loaded.records[0].redacted is True

    import os

    os.unlink(path)


def test_five_trace_chains_are_associated_by_safe_ids() -> None:
    store = TraceStore(sampling_policy=TraceSamplingPolicy(normal_sample_rate=1.0))
    formation = store.record_event(
        trace_id="chain-1", tenant_id="tenant-a", user_id="user-a", event_id="event-1",
        event_type="instruction", source_type="user", policy_action="ALLOW", source_hash="hash",
    )
    evolution = store.record_evolution(
        trace_id="chain-1", tenant_id="tenant-a", user_id="user-a", event_id="event-1",
        candidate_id="candidate-1", memory_id="memory-1", action="PROMOTE",
        previous_memory_id=None, parent_id=formation.span_id,
    )
    retrieval = store.record(
        TraceSpan(
            span_id="retrieval-1", trace_id="chain-1", kind=TraceSpanKind.RETRIEVAL,
            category=TraceCategory.RETRIEVAL, tenant_id="tenant-a", user_id="user-a",
            ids={"query_id": "query-1", "task_id": "task-1", "memory_id": "memory-1"},
        )
    )
    forget = store.record_forget(
        trace_id="chain-1", tenant_id="tenant-a", user_id="user-a", request_id="forget-1",
        memory_ids=["memory-1"], outcome="SUCCEEDED", high_risk=True,
    )
    infrastructure = store.record_infrastructure(
        trace_id="chain-1", tenant_id="tenant-a", user_id="user-a", operation="projection",
        outcome="succeeded", ids={"memory_id": "memory-1"}, parent_id=evolution.span_id,
    )

    assert {span.category for span in store.list_by_trace("chain-1")} == {
        TraceCategory.FORMATION, TraceCategory.EVOLUTION, TraceCategory.RETRIEVAL,
        TraceCategory.FORGET, TraceCategory.INFRASTRUCTURE,
    }
    assert store.list_by_task("task-1") == [retrieval]
    assert store.list_by_query("query-1") == [retrieval]
    assert formation.event_id == "event-1"
    assert evolution.memory_id == infrastructure.memory_id == "memory-1"
    assert forget.retention_class == "ELEVATED"


def test_sampling_is_deterministic_and_critical_paths_are_mandatory() -> None:
    policy = TraceSamplingPolicy(normal_sample_rate=0.0)
    store = TraceStore(sampling_policy=policy)
    normal = store.record(
        TraceSpan(
            span_id="normal", trace_id="normal-1", kind=TraceSpanKind.RETRIEVAL,
            category=TraceCategory.RETRIEVAL, tenant_id="tenant-a", user_id="user-a",
        )
    )
    failed = store.record(
        TraceSpan(
            span_id="failed", trace_id="failed-1", kind=TraceSpanKind.INFRASTRUCTURE,
            category=TraceCategory.INFRASTRUCTURE, tenant_id="tenant-a", user_id="user-a",
            classification={"outcome": "FAILED"},
        )
    )
    assert normal.sampled is False
    assert store.list_by_trace("normal-1") == []
    assert failed.sampled is True
    assert failed.retention_class == "ELEVATED"
    assert failed.expires_at is not None


def test_trace_rejects_raw_content_and_purges_only_expired() -> None:
    with pytest.raises(ValueError, match="trace_raw_field_forbidden:query"):
        TraceSpan(
            span_id="unsafe", trace_id="unsafe", kind=TraceSpanKind.RETRIEVAL,
            tenant_id="tenant-a", user_id="user-a", classification={"query": "secret"},
        )
    store = TraceStore(sampling_policy=TraceSamplingPolicy(normal_sample_rate=1.0))
    recorded = store.record(
        TraceSpan(
            span_id="old", trace_id="old", kind=TraceSpanKind.EVENT,
            tenant_id="tenant-a", user_id="user-a",
        )
    )
    assert recorded.expires_at is not None
    assert store.purge_expired(now=recorded.expires_at + timedelta(seconds=1)) == 1
    assert store.records == []
