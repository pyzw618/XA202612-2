"""Small, dependency-free reliability metrics collector for vNext infrastructure."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Series:
    values: list[float] = field(default_factory=list)

    def add(self, value: float) -> None:
        self.values.append(max(0.0, float(value)))

    def summary(self) -> dict[str, float | int]:
        if not self.values:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
        ordered = sorted(self.values)
        def percentile(percent: float) -> float:
            index = min(len(ordered) - 1, int(round((percent / 100) * (len(ordered) - 1))))
            return round(ordered[index], 3)
        return {
            "count": len(ordered),
            "p50_ms": percentile(50),
            "p95_ms": percentile(95),
            "max_ms": round(max(ordered), 3),
        }


@dataclass
class InfrastructureMetrics:
    """In-process counters with stable JSON output for tests and diagnostics.

    The collector deliberately accepts only IDs, statuses and timings. Callers
    must never pass memory content, raw queries or embedding vectors.
    """

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

    def observe_latency(self, operation: str, duration_ms: float) -> None:
        self.latency.setdefault(operation, _Series()).add(duration_ms)

    def timed(self, operation: str):
        return _Timer(self, operation)

    def record_projection(self, *, success: bool, lag_ms: float = 0.0) -> None:
        self.projection_attempts += 1
        self.projection_succeeded += int(success)
        self.projection_failed += int(not success)
        self.projection_lag_ms.add(lag_ms)

    def record_repair(self, *, success: bool, recovery_ms: float | None = None) -> None:
        self.repair_attempts += 1
        self.repair_succeeded += int(success)
        if recovery_ms is not None:
            self.recovery_time_ms.add(recovery_ms)

    def record_forget(self, *, success: bool, residual_count: int) -> None:
        self.forget_attempts += 1
        self.forget_succeeded += int(success)
        self.record_residual(residual_count)

    def record_residual(self, residual_count: int) -> None:
        self.residual_checks += 1
        self.residual_total += max(0, int(residual_count))

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
