"""Persistent, redacted infrastructure metrics for vNext."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from memoryhub.storage.models import ObservabilityMetricRow


@dataclass
class _Series:
    values: list[float] = field(default_factory=list)
    total_count: int = 0

    def add(self, value: float) -> None:
        self.values.append(max(0.0, float(value)))
        self.total_count += 1

    def summary(self) -> dict[str, float | int]:
        if not self.values:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(self.values)

        def percentile(percent: float) -> float:
            index = min(len(ordered) - 1, int(round((percent / 100) * (len(ordered) - 1))))
            return round(ordered[index], 3)

        return {
            "count": self.total_count,
            "p50_ms": percentile(50),
            "p95_ms": percentile(95),
            "max_ms": round(max(ordered), 3),
        }


@dataclass
class InfrastructureMetrics:
    """Counters and timings whose aggregate counts are never sampled away."""

    latency: dict[str, _Series] = field(default_factory=dict)
    projection_attempts: int = 0
    projection_succeeded: int = 0
    projection_failed: int = 0
    repair_attempts: int = 0
    repair_succeeded: int = 0
    forget_attempts: int = 0
    forget_succeeded: int = 0
    residual_checks: int = 0
    residual_total: int = 0
    projection_lag_ms: _Series = field(default_factory=_Series)
    recovery_time_ms: _Series = field(default_factory=_Series)
    db: Any | None = field(default=None, repr=False)
    tenant_id: str = field(default="system", repr=False)
    user_id: str = field(default="system", repr=False)

    def __post_init__(self) -> None:
        if self.db is None:
            return
        with self.db.session() as session:
            rows = session.query(ObservabilityMetricRow).filter_by(
                tenant_id=self.tenant_id, user_id=self.user_id
            ).all()
            for row in rows:
                self._load_row(row)

    def _load_row(self, row: ObservabilityMetricRow) -> None:
        name = row.metric_name
        if name.startswith("latency_ms:"):
            series = self.latency.setdefault(name.split(":", 1)[1], _Series())
            series.values = [max(0.0, float(value)) for value in (row.samples or [])]
            series.total_count = int(row.count)
            return
        if name == "projection.attempts":
            self.projection_attempts = int(row.count)
        elif name == "projection.succeeded":
            self.projection_succeeded = int(row.count)
        elif name == "projection.failed":
            self.projection_failed = int(row.count)
        elif name == "repair.attempts":
            self.repair_attempts = int(row.count)
        elif name == "repair.succeeded":
            self.repair_succeeded = int(row.count)
        elif name == "forget.attempts":
            self.forget_attempts = int(row.count)
        elif name == "forget.succeeded":
            self.forget_succeeded = int(row.count)
        elif name == "forget.residual_checks":
            self.residual_checks = int(row.count)
        elif name == "forget.residual_total":
            self.residual_total = int(row.total_value)
        elif name == "projection.lag_ms":
            self.projection_lag_ms.values = [float(value) for value in (row.samples or [])]
            self.projection_lag_ms.total_count = int(row.count)
        elif name == "recovery.time_ms":
            self.recovery_time_ms.values = [float(value) for value in (row.samples or [])]
            self.recovery_time_ms.total_count = int(row.count)

    def _persist(
        self,
        name: str,
        value: float = 1.0,
        *,
        category: str = "INFRASTRUCTURE",
        status: str = "SUCCEEDED",
        trace_id: str | None = None,
        task_id: str | None = None,
        event_id: str | None = None,
        memory_id: str | None = None,
        query_id: str | None = None,
        retain_samples: bool = False,
    ) -> None:
        if self.db is None:
            return
        dimension = "|".join((self.tenant_id, self.user_id, name, category, status))
        metric_id = "metric_" + hashlib.sha256(dimension.encode("utf-8")).hexdigest()
        with self.db.session() as session:
            row = session.get(ObservabilityMetricRow, metric_id)
            if row is None:
                row = ObservabilityMetricRow(
                    metric_id=metric_id,
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    metric_name=name,
                    category=category,
                    status=status,
                    trace_id=trace_id,
                    task_id=task_id,
                    event_id=event_id,
                    memory_id=memory_id,
                    query_id=query_id,
                    count=0,
                    total_value=0.0,
                    min_value=float(value),
                    max_value=float(value),
                    samples=[],
                    retention_class="AGGREGATE",
                )
                session.add(row)
            row.count += 1
            row.total_value += float(value)
            row.min_value = min(float(row.min_value), float(value))
            row.max_value = max(float(row.max_value), float(value))
            if retain_samples:
                row.samples = list(row.samples or [])[-255:] + [float(value)]

    def observe_latency(self, operation: str, duration_ms: float) -> None:
        value = max(0.0, float(duration_ms))
        self.latency.setdefault(operation, _Series()).add(value)
        self._persist(f"latency_ms:{operation}", value, retain_samples=True)

    def timed(self, operation: str):
        return _Timer(self, operation)

    def record_projection(self, *, success: bool, lag_ms: float = 0.0) -> None:
        self.projection_attempts += 1
        self.projection_succeeded += int(success)
        self.projection_failed += int(not success)
        self.projection_lag_ms.add(lag_ms)
        self._persist("projection.attempts")
        self._persist("projection.succeeded" if success else "projection.failed")
        self._persist("projection.lag_ms", lag_ms, retain_samples=True)

    def record_repair(self, *, success: bool, recovery_ms: float | None = None) -> None:
        self.repair_attempts += 1
        self.repair_succeeded += int(success)
        self._persist("repair.attempts")
        if success:
            self._persist("repair.succeeded")
        if recovery_ms is not None:
            self.recovery_time_ms.add(recovery_ms)
            self._persist("recovery.time_ms", recovery_ms, retain_samples=True)

    def record_forget(self, *, success: bool, residual_count: int) -> None:
        self.forget_attempts += 1
        self.forget_succeeded += int(success)
        self._persist("forget.attempts", category="FORGET")
        if success:
            self._persist("forget.succeeded", category="FORGET")
        self.record_residual(residual_count)

    def record_residual(self, residual_count: int) -> None:
        count = max(0, int(residual_count))
        self.residual_checks += 1
        self.residual_total += count
        self._persist("forget.residual_checks", category="FORGET")
        self._persist("forget.residual_total", count, category="FORGET")

    def snapshot(self) -> dict[str, Any]:
        def rate(good: int, total: int) -> float:
            return round(good / total, 4) if total else 0.0

        return {
            "latency_ms": {name: series.summary() for name, series in sorted(self.latency.items())},
            "projection": {
                "attempts": self.projection_attempts,
                "success_rate": rate(self.projection_succeeded, self.projection_attempts),
                "lag_ms": self.projection_lag_ms.summary(),
            },
            "recovery": {
                "attempts": self.repair_attempts,
                "repair_rate": rate(self.repair_succeeded, self.repair_attempts),
                "time_ms": self.recovery_time_ms.summary(),
            },
            "forget": {
                "attempts": self.forget_attempts,
                "success_rate": rate(self.forget_succeeded, self.forget_attempts),
                "residual_retrieval_count": self.residual_total,
                "residual_checks": self.residual_checks,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.snapshot(), sort_keys=True)


class _Timer:
    def __init__(self, metrics: InfrastructureMetrics, operation: str) -> None:
        self.metrics, self.operation = metrics, operation
        self.started = 0.0

    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.metrics.observe_latency(self.operation, (time.perf_counter() - self.started) * 1000)
        return False


__all__ = ["InfrastructureMetrics"]
