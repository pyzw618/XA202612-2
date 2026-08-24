from __future__ import annotations

from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
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
