from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect

from memoryhub.application.dashboard_service import DashboardService
from memoryhub.observability import (
    AuditStore,
    InfrastructureMetrics,
    TraceSamplingPolicy,
    TraceSpan,
    TraceStore,
)
from memoryhub.storage.database import Database
from memoryhub.storage.models import ObservabilityTraceRow

DB_PATH = Path(__file__).parents[1] / "data" / ".s6_03_observability_test.db"


def _clean_db() -> None:
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def isolated_database():
    _clean_db()
    yield
    _clean_db()


def _db() -> Database:
    db = Database(str(DB_PATH))
    db.init_schema()
    return db


def test_trace_metric_audit_survive_restart_and_are_indexed() -> None:
    db = _db()
    trace = TraceStore(db=db, sampling_policy=TraceSamplingPolicy(normal_sample_rate=1.0))
    trace.record(
        TraceSpan(
            span_id="span-s6-03",
            trace_id="trace-s6-03",
            kind="RETRIEVAL",
            category="RETRIEVAL",
            tenant_id="tenant-a",
            user_id="user-a",
            ids={
                "task_id": "task-a", "event_id": "event-a", "memory_id": "memory-a",
                "query_id": "query-a",
            },
            classification={"outcome": "SUCCEEDED"},
        )
    )
    metrics = InfrastructureMetrics(db=db)
    metrics.record_projection(success=True, lag_ms=3)
    metrics.record_projection(success=False, lag_ms=5)
    audits = AuditStore(db)
    audits.record(
        action="DASHBOARD_VIEW", tenant_id="tenant-a", user_id="user-a", actor_id="admin",
        target_type="dashboard", target_id="retrieval_debugger",
        details={"redacted": True},
    )
    db.close()

    restarted = _db()
    restored_trace = TraceStore(
        db=restarted, sampling_policy=TraceSamplingPolicy(normal_sample_rate=1.0)
    )
    assert restored_trace.list_by_task("task-a")[0].query_id == "query-a"
    assert restored_trace.list_by_event("event-a")[0].memory_id == "memory-a"
    restored_metrics = InfrastructureMetrics(db=restarted)
    assert restored_metrics.snapshot()["projection"]["attempts"] == 2
    assert restored_metrics.snapshot()["projection"]["success_rate"] == 0.5
    assert AuditStore(restarted).list_for_tenant("tenant-a")[0]["actor_id"] == "admin"
    dashboard = DashboardService(db=restarted)
    projection = dashboard.view(
        "retrieval_debugger", tenant_id="tenant-a", user_id="user-a", actor_id="admin"
    )
    assert projection["items"][0]["links"]["memory_id"] == "memory-a"
    assert any(
        item["action"] == "DASHBOARD_VIEW"
        for item in AuditStore(restarted).list_for_tenant("tenant-a")
    )

    indexes = {
        item["name"]
        for item in inspect(restarted.engine).get_indexes("observability_traces")
    }
    assert "ix_observability_traces_trace_created" in indexes
    assert "ix_observability_traces_category_status" in indexes
    restarted.close()


def test_recursive_redaction_sampling_and_purge_preserve_aggregate_metrics() -> None:
    with pytest.raises(ValueError, match="trace_raw_field_forbidden:query"):
        TraceSpan(
            span_id="bad", trace_id="bad", kind="EVENT", category="FORMATION",
            tenant_id="tenant-a", user_id="user-a",
            classification={"nested": {"query": "must not persist"}},
        )

    policy = TraceSamplingPolicy(normal_sample_rate=0.0)
    db = _db()
    traces = TraceStore(db=db, sampling_policy=policy)
    evaluation = traces.record(
        TraceSpan(
            span_id="evaluation-span", trace_id="evaluation-trace", kind="RETRIEVAL",
            category="RETRIEVAL", tenant_id="tenant-a", user_id="user-a",
            classification={"traffic_class": "EVALUATION"},
        )
    )
    assert evaluation.sampled is True and evaluation.retention_class == "ELEVATED"
    metrics = InfrastructureMetrics(db=db)
    metrics.record_projection(success=True)
    with db.session() as session:
        row = session.get(ObservabilityTraceRow, "evaluation-span")
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert traces.purge_expired() == 1
    assert InfrastructureMetrics(db=db).snapshot()["projection"]["attempts"] == 1
    db.close()


def test_observability_schema_migration_is_additive() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        "CREATE TABLE observability_traces ("
        "span_id VARCHAR(128) PRIMARY KEY, trace_id VARCHAR(128))"
    )
    connection.commit()
    connection.close()
    db = _db()
    columns = {item["name"] for item in inspect(db.engine).get_columns("observability_traces")}
    assert {"tenant_id", "task_id", "event_id", "memory_id", "query_id", "expires_at"} <= columns
    assert "ix_observability_traces_query_id" in {
        item["name"] for item in inspect(db.engine).get_indexes("observability_traces")
    }
    db.close()
