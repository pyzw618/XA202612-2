"""In-memory trace store with optional file persistence.

The store is designed for observability, not as a second memory database.
All records remain redacted by construction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind


class TraceStore:
    """Redacted span store with event/candidate/memory indexes.

    The store keeps spans in memory and can persist them to a JSON file.
    It does not keep raw event or memory content.
    """

    def __init__(self, records: list[TraceSpan] | None = None) -> None:
        self._records: list[TraceSpan] = list(records or [])

    @property
    def records(self) -> list[TraceSpan]:
        return list(self._records)

    def record(self, span: TraceSpan) -> TraceSpan:
        if not isinstance(span, TraceSpan):
            raise TypeError("trace store requires TraceSpan")
        self._records.append(span)
        return span

    def get(self, span_id: str) -> TraceSpan | None:
        for span in self._records:
            if span.span_id == span_id:
                return span
        return None

    def list_by_trace(self, trace_id: str) -> list[TraceSpan]:
        return [span for span in self._records if span.trace_id == trace_id]

    def list_by_event(self, event_id: str) -> list[TraceSpan]:
        return [span for span in self._records if span.ids.get("event_id") == event_id]

    def list_by_candidate(self, candidate_id: str) -> list[TraceSpan]:
        return [
            span for span in self._records if span.ids.get("candidate_id") == candidate_id
        ]

    def list_by_memory(self, memory_id: str) -> list[TraceSpan]:
        return [span for span in self._records if span.ids.get("memory_id") == memory_id]

    def formation_chain(self, event_id: str) -> list[TraceSpan]:
        """Return all spans for one event in chronological order."""
        spans = self.list_by_event(event_id)
        return sorted(spans, key=lambda s: s.created_at)

    def clear(self) -> None:
        self._records.clear()

    def dump(self, path: str | Path) -> None:
        data = [span.model_dump(mode="json") for span in self._records]
        Path(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def load(self, path: str | Path) -> None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self._records = [TraceSpan.model_validate(item) for item in raw]

    # ------------------------------------------------------------------
    # Convenience helpers for the formation pipeline.
    # ------------------------------------------------------------------

    def _content_hash(self, value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record_event(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        event_type: str,
        source_type: str,
        policy_action: str,
        source_hash: str,
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-event-{event_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.EVENT,
            layer="RAW_EVENT",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={"event_id": event_id},
            hashes={"source_hash": source_hash},
            classification={
                "event_type": event_type,
                "source_type": source_type,
                "policy_action": policy_action,
            },
        )
        return self.record(span)

    def record_working(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        working_state_id: str,
        version: int,
        state: dict[str, Any],
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-working-{event_id}-{working_state_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.WORKING,
            layer="WORKING_STATE",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={"event_id": event_id, "working_state_id": working_state_id},
            hashes={"state_hash": self._content_hash(state)},
            classification={"version": version},
            scores={},
        )
        return self.record(span)

    def record_episode(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        episode_id: str,
        episode_event_id: str | None,
        seq_no: int,
        event_type: str,
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-episode-{event_id}-{episode_id}-{seq_no}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.EPISODE,
            layer="EPISODE_CHECKPOINT",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={
                "event_id": event_id,
                "episode_id": episode_id,
                "episode_event_id": episode_event_id or "",
            },
            hashes={},
            classification={"event_type": event_type, "seq_no": seq_no},
        )
        return self.record(span)

    def record_candidate(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        candidate_id: str,
        memory_type: str,
        normalized_key: str,
        scope_level: str,
        scope: str,
        confidence: float,
        utility: float,
        stability: float,
        frequency: int,
        claim: dict[str, Any],
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-candidate-{candidate_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.CANDIDATE,
            layer="CANDIDATE",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={"event_id": event_id, "candidate_id": candidate_id},
            hashes={"claim_hash": self._content_hash(claim)},
            classification={
                "memory_type": memory_type,
                "normalized_key": normalized_key,
                "scope_level": scope_level,
                "scope": scope,
            },
            scores={
                "confidence": confidence,
                "utility": utility,
                "stability": stability,
                "frequency": frequency,
            },
        )
        return self.record(span)

    def record_consolidation(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        candidate_id: str,
        decision: str,
        score: float,
        reasons: list[str],
        fast_path: bool,
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-consolidation-{candidate_id}-{event_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.CONSOLIDATION,
            layer="CONSOLIDATED_MEMORY",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={"event_id": event_id, "candidate_id": candidate_id},
            classification={
                "decision": decision,
                "fast_path": fast_path,
            },
            scores={"promotion_score": score},
            reason_codes=list(reasons),
        )
        return self.record(span)

    def record_evolution(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        candidate_id: str,
        memory_id: str,
        action: str,
        previous_memory_id: str | None,
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-evolution-{memory_id}-{event_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.EVOLUTION,
            layer="LONG_TERM",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={
                "event_id": event_id,
                "candidate_id": candidate_id,
                "memory_id": memory_id,
            },
            classification={
                "action": action,
                "previous_memory_id": previous_memory_id or "",
            },
        )
        return self.record(span)

    def record_legacy(
        self,
        *,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        event_id: str,
        memory_type: str,
        scope_level: str,
        scope: str,
        normalized_key: str,
        memory_id: str,
        parent_id: str | None = None,
    ) -> TraceSpan:
        span = TraceSpan(
            span_id=f"span-legacy-{memory_id}-{event_id}",
            trace_id=trace_id,
            parent_id=parent_id,
            kind=TraceSpanKind.LEGACY,
            layer="LONG_TERM",
            tenant_id=tenant_id,
            user_id=user_id,
            ids={"event_id": event_id, "memory_id": memory_id},
            classification={
                "memory_type": memory_type,
                "scope_level": scope_level,
                "scope": scope,
                "normalized_key": normalized_key,
            },
        )
        return self.record(span)


__all__ = ["TraceStore"]
