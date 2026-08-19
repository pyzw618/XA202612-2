"""Preference handler preserving PreferenceExtractor and PreferenceUpdater contracts."""

from __future__ import annotations

from typing import Any

from memoryhub.core.memory.base import (
    BaseMemoryHandler,
    MemoryCandidate,
    MemoryDecision,
)
from memoryhub.core.memory.confidence import ConfidenceFactors
from memoryhub.core.memory.freshness import candidate_freshness


class PreferenceMemoryHandler(BaseMemoryHandler):
    memory_type = "preference"

    def __init__(self, extractor: Any, updater: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.extractor = extractor
        self.updater = updater

    def extract_candidates(
        self, source: Any, *, context: Any = None
    ) -> list[MemoryCandidate]:
        event_id = str(getattr(source, "event_id", ""))
        occurred_at = str(getattr(source, "occurred_at", ""))
        quality = float(getattr(getattr(source, "quality", None), "score", 1.0) or 1.0)
        safety_meta = dict(getattr(source, "payload", {}).get("_safety", {}) or {})
        memories = self.extractor.extract(source)
        for memory in memories:
            if safety_meta:
                memory.extra_payload = {**memory.extra_payload, "safety": safety_meta}
        return [
            MemoryCandidate(
                "preference",
                memory,
                memory.user_id,
                event_id,
                event_id,
                occurred_at,
                list(getattr(memory, "evidences", []) or []),
                quality,
                float(getattr(memory, "confidence", 0.5) or 0.5),
                {},
            )
            for memory in memories
        ]

    def find_similar(self, candidate: MemoryCandidate) -> Any:
        return (
            self.updater._find_existing(candidate.payload)
            if self.updater is not None and hasattr(self.updater, "_find_existing")
            else None
        )

    def classify_relation(self, candidate: MemoryCandidate, existing: Any) -> str:
        """Distinguish duplicate / supersede / update once a comparable target exists."""
        new_payload = getattr(candidate.payload, "payload", {}) or {}
        old_payload = getattr(existing, "payload", {}) or {}
        new_target = str(new_payload.get("target", "")).strip()
        old_target = str(old_payload.get("target", "")).strip()
        if new_target and new_target == old_target:
            new_value = new_payload.get("value")
            old_value = old_payload.get("value")
            if new_value is not None and old_value is not None:
                return "duplicate" if new_value == old_value else "supersede"
            if str(candidate.payload.text).strip().lower() == str(
                existing.text
            ).strip().lower():
                return "duplicate"
        return "update"

    def build_confidence_factors(
        self, candidate: MemoryCandidate, existing: Any
    ) -> ConfidenceFactors:
        source = (
            0.95
            if getattr(candidate.payload, "extract_source", "") == "explicit_feedback"
            else 0.60
        )
        quality = min(candidate.quality_score, candidate.extraction_score)
        return ConfidenceFactors(
            source,
            quality,
            self.confidence_calculator.support_from_evidence_count(
                len(candidate.evidences)
            ),
            self._freshness(candidate.occurred_at),
        )

    def apply(self, decision: MemoryDecision) -> Any:
        if (
            self.updater is None
            or decision.action in {"reject", "review"}
            or decision.candidate is None
        ):
            return None
        memory = decision.candidate.payload
        memory.evidences = decision.candidate.evidences
        memory.confidence = decision.confidence
        # Extraction-derived write: the source event already passed the
        # event-level safety gate, so skip the redundant memory-level re-gate
        # (I-14 double-gate fix).
        return self.updater.add(memory, skip_write_gate=True)

    def _freshness(self, value: str) -> float:
        return candidate_freshness(value, memory_type=self.memory_type)
