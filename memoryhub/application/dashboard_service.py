"""Management-only, redacted projections for the four vNext dashboard views."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

DashboardView = Literal["explorer", "evolution", "retrieval_debugger", "benchmark"]


class DashboardService:
    """Expose safe dashboard projections without becoming a read/write authority."""

    def __init__(
        self,
        *,
        trace_store=None,
        metrics=None,
        results_root: str | Path = "evaluation/results",
    ):
        self.trace_store = trace_store
        self.metrics = metrics
        self.results_root = Path(results_root)
        self.audit_log: list[dict[str, str]] = []

    def view(
        self, view: DashboardView, *, tenant_id: str, user_id: str, actor_id: str
    ) -> dict[str, Any]:
        self.audit_log.append(
            {
                "view": view,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "actor_id": actor_id,
                "redacted": "true",
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )
        spans = self._spans(tenant_id, user_id)
        if view == "explorer":
            return self._explorer(spans)
        if view == "evolution":
            return self._evolution(spans)
        if view == "retrieval_debugger":
            return self._retrieval_debugger(spans)
        if view == "benchmark":
            return self._benchmark()
        raise ValueError(f"unknown_dashboard_view:{view}")

    def _spans(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        records = self.trace_store.records if self.trace_store is not None else []
        return [
            span.model_dump(mode="json")
            for span in records
            if span.tenant_id == tenant_id and span.user_id == user_id
        ]

    @staticmethod
    def _summary(spans: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for span in spans:
            category = str(span["category"])
            counts[category] = counts.get(category, 0) + 1
        return counts

    def _explorer(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "redacted": True,
            "trace_summary": self._summary(spans),
            "items": [
                {"trace_id": span["trace_id"], "ids": span["ids"], "category": span["category"]}
                for span in spans
            ],
        }

    def _evolution(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "redacted": True,
            "items": [
                {
                    "trace_id": span["trace_id"], "parent_id": span["parent_id"],
                    "ids": span["ids"], "classification": span["classification"],
                }
                for span in spans
                if span["category"] in {"FORMATION", "EVOLUTION", "FORGET"}
            ],
        }

    def _retrieval_debugger(self, spans: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "redacted": True,
            "items": [
                {
                    "trace_id": span["trace_id"], "ids": span["ids"],
                    "classification": span["classification"], "scores": span["scores"],
                }
                for span in spans
                if span["category"] == "RETRIEVAL"
            ],
        }

    def _benchmark(self) -> dict[str, Any]:
        path = self.results_root / "vnext_benchmark.json"
        benchmark = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        layers = benchmark.get("layers", {})
        aggregate_layers = {
            name: {key: value for key, value in data.items() if key != "sample_results"}
            for name, data in layers.items()
            if isinstance(data, dict)
        }
        return {
            "redacted": True,
            "runner_version": benchmark.get("runner_version", "unavailable"),
            "reproducibility": benchmark.get("reproducibility", {}),
            "layers": aggregate_layers,
            "infrastructure_metrics": self.metrics.snapshot() if self.metrics is not None else {},
        }


__all__ = ["DashboardService", "DashboardView"]
