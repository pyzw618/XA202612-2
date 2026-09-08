from __future__ import annotations

import random
from collections.abc import Callable, Sequence


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[list[float]], float] | None = None,
    *,
    confidence: float = 0.95,
    samples: int = 2000,
    seed: int = 20260906,
) -> tuple[float, float]:
    """Deterministic percentile bootstrap interval for a per-case metric."""
    if not values:
        return 0.0, 0.0
    if not 0 < confidence < 1 or samples < 1:
        raise ValueError("confidence must be in (0, 1) and samples must be positive")
    fn = statistic or (lambda xs: sum(xs) / len(xs))
    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(fn([values[rng.randrange(n)] for _ in range(n)]) for _ in range(samples))
    tail = (1.0 - confidence) / 2.0
    lo = estimates[max(0, int(tail * samples))]
    hi = estimates[min(samples - 1, int((1.0 - tail) * samples))]
    return round(lo, 6), round(hi, 6)
