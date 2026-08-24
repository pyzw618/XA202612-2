"""Reflection input/output schema and failure types."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReflectionInput(BaseModel):
    """Everything a reflection model needs to propose a candidate memory."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    payload_summary: dict[str, Any] = Field(default_factory=dict)
    working_state_snapshot: dict[str, Any] = Field(default_factory=dict)
    episode_history_summary: list[dict[str, Any]] = Field(default_factory=list)
    requested_memory_type: str | None = None
    scope_hint: str | None = None
    occurred_at: datetime = Field(default_factory=datetime.now)


class ReflectionOutput(BaseModel):
    """A reflection result that is always a Candidate, never an Authority write."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    memory_type: str = Field(min_length=1)
    normalized_key: str = Field(min_length=1)
    claim: dict[str, Any] = Field(min_length=1)
    scope_level: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    utility: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    supporting_episode_ids: list[str] = Field(default_factory=list)
    status: str = "ACCUMULATING"


class ReflectionRunError(RuntimeError):
    """Reflection failed after retries and should be routed to REVIEW."""

    def __init__(self, message: str, *, input_hash: str = "") -> None:
        super().__init__(message)
        self.input_hash = input_hash


__all__ = ["ReflectionInput", "ReflectionOutput", "ReflectionRunError"]
