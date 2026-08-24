"""Safe vNext trace sampling, redaction and retention policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


class TraceCategory(str):
    """The five cross-system trace chains used by S5 evaluation and diagnostics."""

    FORMATION = "FORMATION"
    EVOLUTION = "EVOLUTION"
    RETRIEVAL = "RETRIEVAL"
    FORGET = "FORGET"
    INFRASTRUCTURE = "INFRASTRUCTURE"


_FORBIDDEN_KEYS = frozenset(
    {"content", "text", "payload", "claim", "excerpt", "raw_query", "query", "embedding"}
)


def assert_redacted(value: Any) -> None:
    """Reject raw content-bearing fields recursively, including nested metadata."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"trace_raw_field_forbidden:{key}")
            assert_redacted(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_redacted(item)


@dataclass(frozen=True, slots=True)
class TraceSamplingPolicy:
    """Deterministic sampling with mandatory safety/error/Forget coverage."""

    normal_sample_rate: float = 0.1
    normal_retention_days: int = 7
    elevated_retention_days: int = 30

    def should_sample(
        self,
        *,
        trace_id: str,
        category: str,
        risk_level: str = "NORMAL",
        outcome: str = "SUCCEEDED",
    ) -> bool:
        if category == TraceCategory.FORGET:
            return True
        if outcome.upper() in {"ERROR", "FAILED", "DENIED"}:
            return True
        if risk_level.upper() in {"HIGH", "CRITICAL"}:
            return True
        if self.normal_sample_rate <= 0:
            return False
        if self.normal_sample_rate >= 1:
            return True
        digest = hashlib.sha256(trace_id.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big") / float(1 << 64)
        return bucket < self.normal_sample_rate

    def expires_at(
        self,
        *,
        created_at: datetime,
        category: str,
        risk_level: str = "NORMAL",
        outcome: str = "SUCCEEDED",
    ) -> datetime:
        elevated = (
            category == TraceCategory.FORGET
            or outcome.upper() in {"ERROR", "FAILED", "DENIED"}
            or risk_level.upper() in {"HIGH", "CRITICAL"}
        )
        return created_at + timedelta(
            days=self.elevated_retention_days if elevated else self.normal_retention_days
        )


__all__ = ["TraceCategory", "TraceSamplingPolicy", "assert_redacted"]
