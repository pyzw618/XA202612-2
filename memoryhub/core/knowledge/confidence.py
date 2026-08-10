"""Deterministic confidence scoring for extracted and evolved knowledge."""

from __future__ import annotations

import math
from dataclasses import dataclass


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
            *(_clamp(value) for value in (
                self.event_quality,
                self.completion,
                self.structure,
                self.evidence,
                self.outcome,
                self.consistency,
            ))
        )


class KnowledgeConfidenceCalculator:
    """Score quality without allowing one strong factor to hide a weak chain."""

    _WEIGHTS = (0.28, 0.20, 0.20, 0.14, 0.10, 0.08)

    def score(self, factors: KnowledgeConfidenceFactors, *, ceiling: float = 0.97) -> float:
        values = factors.normalized()
        parts = (
            values.event_quality,
            values.completion,
            values.structure,
            values.evidence,
            values.outcome,
            values.consistency,
        )
        weighted = sum(value * weight for value, weight in zip(parts, self._WEIGHTS))
        weakest = min(parts)
        weakest_factor_penalty = 0.82 + 0.18 * weakest
        return round(_clamp(weighted * weakest_factor_penalty, upper=ceiling), 4)

    def merge_score(
        self,
        *,
        existing_confidence: float,
        incoming_confidence: float,
        success_count: int,
        total_count: int,
        evidence_count: int,
    ) -> float:
        """Combine extraction quality, observed success and independent evidence."""
        total = max(0, int(total_count))
        successes = min(max(0, int(success_count)), total)
        base = 0.65 * _clamp(existing_confidence) + 0.35 * _clamp(incoming_confidence)
        reliability = (successes + 1.0) / (total + 2.0)
        support = 1.0 - math.exp(-max(total, evidence_count) / 4.0)
        blend = min(0.35, 0.10 + 0.04 * total)
        score = base * (1.0 - blend) + reliability * blend + 0.05 * support
        return round(_clamp(score, upper=0.99), 4)

    def template_score(
        self, case_confidence: float, *, step_count: int, evidence_count: int
    ) -> float:
        generalization = min(1.0, 0.45 + 0.08 * max(0, step_count))
        evidence = min(1.0, max(0, evidence_count) / 3.0)
        score = 0.78 * _clamp(case_confidence) + 0.14 * generalization + 0.08 * evidence
        return round(_clamp(score, lower=0.35, upper=0.95), 4)


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return lower
    if not math.isfinite(numeric):
        return lower
    return max(lower, min(upper, numeric))
