"""Trace models for the vNext formation and evolution pipeline.

Trace records are intentionally redacted: they store IDs, hashes,
classifications and scores, but not the raw event text or memory content.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TraceSpanKind(str):
    """Named formation/evolution stages used as ``kind`` values."""

    EVENT = "EVENT"
    WORKING = "WORKING"
    EPISODE = "EPISODE"
    CANDIDATE = "CANDIDATE"
    CONSOLIDATION = "CONSOLIDATION"
    EVOLUTION = "EVOLUTION"
    LEGACY = "LEGACY"


class TraceSpan(BaseModel):
    """One span in a formation or evolution trace.

    The model never stores raw content.  ``hashes`` holds content hashes,
    ``classification`` holds category/scope/type/action/reason metadata, and
    ``scores`` holds numeric decision metrics.
    """

    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    parent_id: str | None = None
    kind: Literal[
        "EVENT",
        "WORKING",
        "EPISODE",
        "CANDIDATE",
        "CONSOLIDATION",
        "EVOLUTION",
        "LEGACY",
    ]
    layer: str = Field(default="")
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    # References to entities in the formation chain.
    ids: dict[str, str] = Field(default_factory=dict)
    # Content hashes; no raw text.
    hashes: dict[str, str] = Field(default_factory=dict)
    # Categorical / enum fields and decisions.
    classification: dict[str, Any] = Field(default_factory=dict)
    # Numeric scores: confidence, utility, stability, promotion score, ...
    scores: dict[str, float] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)
    # Whether the span was created in redacted mode (always true for vNext).
    redacted: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def event_id(self) -> str | None:
        return self.ids.get("event_id")

    @property
    def candidate_id(self) -> str | None:
        return self.ids.get("candidate_id")

    @property
    def memory_id(self) -> str | None:
        return self.ids.get("memory_id")


__all__ = ["TraceSpan", "TraceSpanKind"]
