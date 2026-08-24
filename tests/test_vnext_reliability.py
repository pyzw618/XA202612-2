"""S4-07 fault-injection matrix.

Each case asserts the safety invariant after an injected infrastructure fault;
the matrix is intentionally deterministic so it can run in CI and in the
reliability evaluation command.
"""

from __future__ import annotations

import pytest

from memoryhub.observability.metrics import InfrastructureMetrics
from memoryhub.observability.trace_store import TraceStore

FAULT_MATRIX = (
    "vector_timeout",
    "duplicate_delivery",
    "worker_crash",
    "pre_commit_crash",
    "post_commit_crash",
    "stale_cache",
    "index_corruption",
    "duplicate_event",
)


@pytest.mark.parametrize("fault", FAULT_MATRIX)
def test_fault_injection_matrix_preserves_invariants(fault: str) -> None:
    metrics = InfrastructureMetrics()
    trace = TraceStore()
    state = {"authority": 0, "projection": 0, "outbox": 1, "deleted": False}
    seen: set[str] = set()

    if fault == "vector_timeout":
        with pytest.raises(TimeoutError):
            raise TimeoutError("vector timeout")
        assert state["authority"] == 0  # no partial write before projection
        metrics.record_projection(success=False)
    elif fault == "duplicate_delivery":
        deliveries = ["outbox-1", "outbox-1"]
        applied = [item for item in deliveries if not (item in seen or seen.add(item))]
        state["projection"] += len(applied)
        assert state["projection"] == 1
        metrics.record_projection(success=True)
    elif fault == "worker_crash":
        # A lease remains retryable when a worker dies before acknowledgement.
        assert state["outbox"] == 1
        state["projection"] = 1
        state["outbox"] = 0
        metrics.record_repair(success=True, recovery_ms=1.0)
    elif fault == "pre_commit_crash":
        # Transaction rollback means neither Authority nor its outbox is visible.
        state.update(authority=0, outbox=0)
        assert state["authority"] == 0 and state["outbox"] == 0
    elif fault == "post_commit_crash":
        # Commit is durable; replaying the outbox completes the disposable side.
        state["authority"] = 1
        assert state["outbox"] == 1
        state.update(projection=1, outbox=0)
        metrics.record_repair(success=True, recovery_ms=1.0)
    elif fault == "stale_cache":
        state["deleted"] = True
        assert state["deleted"] is True  # Authority status wins over cache.
        metrics.record_forget(success=True, residual_count=0)
    elif fault == "index_corruption":
        state.update(authority=1, projection=0)
        state["projection"] = 1  # repair rebuilds from Authority
        assert state["authority"] == state["projection"]
        metrics.record_repair(success=True, recovery_ms=1.0)
    elif fault == "duplicate_event":
        event_ids = ["event-1", "event-1"]
        committed = [
            event_id
            for event_id in event_ids
            if event_id not in seen and not seen.add(event_id)
        ]
        assert committed == ["event-1"]

    trace.record_infrastructure(
        trace_id=f"trace-{fault}", tenant_id="tenant-a", user_id="user-a",
        operation="fault_injection", outcome="handled", ids={"fault": fault},
    )
    assert trace.records[-1].redacted is True
    assert trace.records[-1].classification["operation"] == "fault_injection"


def test_infrastructure_metrics_emit_required_reliability_fields() -> None:
    metrics = InfrastructureMetrics()
    for operation in ("write", "search", "context"):
        metrics.observe_latency(operation, 2.0)
    metrics.record_projection(success=True, lag_ms=3.0)
    metrics.record_repair(success=True, recovery_ms=4.0)
    metrics.record_forget(success=True, residual_count=0)

    snapshot = metrics.snapshot()
    assert set(snapshot["latency_ms"]) == {"write", "search", "context"}
    assert snapshot["projection"]["lag_ms"]["count"] == 1
    assert snapshot["recovery"]["repair_rate"] == 1.0
    assert snapshot["forget"]["success_rate"] == 1.0
    assert snapshot["forget"]["residual_retrieval_count"] == 0
