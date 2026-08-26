"""Management-only, redacted projections for the four vNext dashboard views."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from memoryhub.observability.audit_store import AuditStore
from memoryhub.observability.metrics import InfrastructureMetrics
from memoryhub.observability.trace_store import TraceStore

DashboardView = Literal["explorer", "evolution", "retrieval_debugger", "benchmark"]


class DashboardService:
    """Expose safe dashboard projections without becoming a read/write authority."""

    def __init__(
        self,
        *,
        trace_store=None,
        metrics=None,
        results_root: str | Path = "evaluation/results",
        db=None,
        audit_store: AuditStore | None = None,
    ):
        self.trace_store = trace_store or (TraceStore(db=db) if db is not None else None)
        self.metrics = metrics or (InfrastructureMetrics(db=db) if db is not None else None)
        self.db = db
        self.audit_store = audit_store or (AuditStore(db) if db is not None else None)
        self.results_root = Path(results_root)
        self.audit_log: list[dict[str, str]] = []

    def view(
        self,
        view: DashboardView,
        *,
        tenant_id: str,
        user_id: str,
        actor_id: str,
        audit_actor_id: str | None = None,
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
        if self.audit_store is not None:
            self.audit_store.record(
                action="DASHBOARD_VIEW",
                tenant_id=tenant_id,
                user_id=user_id,
                actor_id=audit_actor_id or actor_id,
                target_type="dashboard",
                target_id=view,
                details={"view": view, "redacted": True},
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
                {
                    "trace_id": span["trace_id"],
                    "ids": span["ids"],
                    "links": self._links(span),
                    "category": span["category"],
                }
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
                    "links": self._links(span),
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
                    "links": self._links(span),
                }
                for span in spans
                if span["category"] == "RETRIEVAL"
            ],
        }

    def _benchmark(self) -> dict[str, Any]:
        path = self.results_root / "vnext_benchmark.json"
        benchmark = (
            self._redact(json.loads(path.read_text(encoding="utf-8")))
            if path.exists()
            else {}
        )
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

    @staticmethod
    def _links(span: dict[str, Any]) -> dict[str, Any]:
        ids = span.get("ids", {})
        classification = span.get("classification", {})
        links = {
            "memory_id": ids.get("memory_id"),
            "episode_id": ids.get("episode_id"),
            "retrieval_trace_id": span.get("trace_id")
            if span.get("category") == "RETRIEVAL"
            else None,
            "projection_version": classification.get("projection_version")
            or ids.get("projection_version"),
        }
        return {key: value for key, value in links.items() if value not in (None, "")}

    @staticmethod
    def _redact(value: Any) -> Any:
        forbidden = {
            "content", "text", "payload", "raw_payload", "original_payload", "claim",
            "excerpt", "evidence", "evidence_text", "raw_query", "original_query",
            "query", "body", "memory_body", "embedding",
        }
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if str(key).lower() in forbidden
                    else DashboardService._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [DashboardService._redact(item) for item in value]
        return value


__all__ = ["DashboardService", "DashboardView"]
