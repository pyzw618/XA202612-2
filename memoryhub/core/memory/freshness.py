"""Shared timestamp parsing and bounded freshness scoring across memory lifecycle stages."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

# Aligned with REFACTOR_PLAN_V2.md §2.2 R4 / §4.5.3: slower decay for stable
# long-term memory. Fact 90 / Preference 180 / Knowledge 120 days.
_HALF_LIFE_DAYS = {"fact": 90.0, "preference": 180.0, "knowledge": 120.0}


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def freshness_score(
    timestamp: Any, *, memory_type: str = "", now: datetime | None = None
) -> float:
    """Return a stable [0, 1] freshness value using per-domain half lives."""
    parsed = parse_timestamp(timestamp)
    if parsed is None:
        return 0.5
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (current - parsed).total_seconds() / 86400.0)
    half_life = _HALF_LIFE_DAYS.get(memory_type, 60.0)
    return max(0.0, min(1.0, math.exp(-math.log(2.0) * age_days / half_life)))


def memory_timestamp(memory: Any) -> Any:
    """Choose the most semantically meaningful lifecycle timestamp for a memory."""
    return (
        getattr(memory, "observed_at", None)
        or getattr(memory, "updated_at", None)
        or getattr(memory, "created_at", None)
    )


def candidate_freshness(timestamp: Any, *, memory_type: str = "") -> float:
    """Freshness for a brand-new candidate: no/unknown timestamp means 'just arrived'."""
    if parse_timestamp(timestamp) is None:
        return 1.0
    return freshness_score(timestamp, memory_type=memory_type)


def half_life_days(memory_type: str) -> float:
    """Public half-life accessor shared by freshness, health and confidence domains."""
    return _HALF_LIFE_DAYS.get(memory_type, 60.0)
