"""Deterministic confidence scoring for extracted and evolved knowledge."""

from __future__ import annotations

import math
from dataclasses import dataclass

from memoryhub.core.memory.confidence import (
    ConfidenceFactors,
    UnifiedConfidenceCalculator,
)


@dataclass(frozen=True, slots=True)
class KnowledgeConfidenceFactors:
    event_quality: float
    completion: float
    structure: float
    evidence: float
    outcome: float
    consistency: float

    def normalized(self) -> "KnowledgeConfidenceFactors":
        return KnowledgeConfidenceFactors(
            *(
                _clamp(value)
                for value in (
                    self.event_quality,
                    self.completion,
                    self.structure,
                    self.evidence,
                    self.outcome,
                    self.consistency,
                )
            )
        )


class KnowledgeConfidenceCalculator:
    """Score quality without allowing one strong factor to hide a weak chain."""

    _WEIGHTS = (0.28, 0.20, 0.20, 0.14, 0.10, 0.08)

    def score(
        self, factors: KnowledgeConfidenceFactors, *, ceiling: float = 0.97
    ) -> float:
        """Compatibility facade over the shared four-factor confidence formula."""
        values = factors.normalized()
        shared = ConfidenceFactors(
            source=min(1.0, 0.60 + 0.25 * values.completion + 0.15 * values.outcome),
            quality=(values.event_quality + values.structure + values.consistency)
            / 3.0,
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                1 if values.evidence < 0.55 else (2 if values.evidence < 0.80 else 3)
            ),
            freshness=values.outcome,
        )
        return min(
            ceiling,
            UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge"),
        )

    def merge_score(
        self,
        *,
        existing_confidence: float,
        incoming_confidence: float,
        success_count: int,
        total_count: int,
        evidence_count: int,
    ) -> float:
        total = max(0, int(total_count))
        successes = min(max(0, int(success_count)), total)
        reliability = (successes + 1.0) / (total + 2.0)
        shared = ConfidenceFactors(
            source=max(_clamp(existing_confidence), _clamp(incoming_confidence)),
            quality=0.65 * _clamp(existing_confidence)
            + 0.35 * _clamp(incoming_confidence),
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                max(total, int(evidence_count))
            ),
            freshness=reliability,
        )
        return UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge")

    def template_score(
        self, case_confidence: float, *, step_count: int, evidence_count: int
    ) -> float:
        shared = ConfidenceFactors(
            source=_clamp(case_confidence),
            quality=min(1.0, 0.45 + 0.08 * max(0, step_count)),
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                evidence_count
            ),
            freshness=1.0,
        )
        return max(
            0.35,
            UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge"),
        )


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return lower
    if not math.isfinite(numeric):
        return lower
    return max(lower, min(upper, numeric))
