"""Single explainable confidence formula shared by core memory domains."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ConfidenceFactors:
    source: float
    quality: float
    support: float
    freshness: float

    def normalized(self) -> "ConfidenceFactors":
        return ConfidenceFactors(
            *(
                _clamp(v)
                for v in (self.source, self.quality, self.support, self.freshness)
            )
        )


class UnifiedConfidenceCalculator:
    """O(n) confidence calculation with bounded evidence support and a weak-link guard."""

    DEFAULT_WEIGHTS = (0.35, 0.30, 0.20, 0.15)
    TYPE_WEIGHTS: dict[str, tuple[float, float, float, float]] = {
        "fact": DEFAULT_WEIGHTS,
        "preference": (0.40, 0.25, 0.20, 0.15),
        "knowledge": (0.30, 0.30, 0.25, 0.15),
    }
    reject_threshold = 0.35
    review_threshold = 0.55

    def calculate(
        self,
        factors: ConfidenceFactors,
        *,
        memory_type: Literal["fact", "preference", "knowledge"] = "fact",
    ) -> float:
        values = factors.normalized()
        weights = self.TYPE_WEIGHTS.get(memory_type, self.DEFAULT_WEIGHTS)
        base = sum(
            value * weight
            for value, weight in zip(
                (values.source, values.quality, values.support, values.freshness),
                weights,
            )
        )
        protected = base * (0.85 + 0.15 * min(values.source, values.quality))
        return round(_clamp(protected, upper=0.95), 4)

    @staticmethod
    def support_from_evidence_count(count: int) -> float:
        # 1/2/3+ buckets prevent retries or long histories from dominating the score.
        return (
            0.0
            if count <= 0
            else (0.55 if count == 1 else (0.75 if count == 2 else 0.90))
        )


def _clamp(value: float, *, upper: float = 1.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(upper, value if math.isfinite(value) else 0.0))
