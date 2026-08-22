"""Versioned vNext API DTOs.

These models define the wire contract only.  They do not call repositories,
retrievers, model providers, or write services; adapters delegate business
behavior to the canonical application services defined by S0-02.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from memoryhub.domain.contracts import (
    Activation,
    EpisodeSnapshot,
    LifecycleLayer,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
    WorkingSnapshot,
)


class _ApiEnum(str, Enum):
    pass


class ConsistencyMode(_ApiEnum):
    EVENTUAL = "EVENTUAL"
    AUTHORITY_CHECKED = "AUTHORITY_CHECKED"


class FormationResponseStatus(_ApiEnum):
    EVENT_ACCEPTED = "EVENT_ACCEPTED"
    WORKING_UPDATED = "WORKING_UPDATED"
    CHECKPOINT_CREATED = "CHECKPOINT_CREATED"
    REFLECTION_PENDING = "REFLECTION_PENDING"


class ForgetStatus(_ApiEnum):
    ACCEPTED = "ACCEPTED"
    READ_BLOCKED = "READ_BLOCKED"
    CLEARING_PROJECTIONS = "CLEARING_PROJECTIONS"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


class APIErrorCode(_ApiEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    POLICY_REJECTED = "POLICY_REJECTED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    PARTIAL_RESULT = "PARTIAL_RESULT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class APIError(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    code: APIErrorCode
    message: str = Field(min_length=1)
    retryable: bool = False
    trace_id: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class WriteEventRequest(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    events: list[MemoryEventContract] = Field(min_length=1)


class WriteEventResponse(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    event_ids: list[str] = Field(default_factory=list)
    working_state_version: int | None = Field(default=None, ge=0)
    checkpoint_created: bool = False
    episode_id: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    memory_ids: list[str] = Field(default_factory=list)
    formation_status: FormationResponseStatus = FormationResponseStatus.EVENT_ACCEPTED
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)


class MemoryRetrievalRequest(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    query: str = ""
    task_id: str = ""
    session_id: str = ""
    current_goal: str = ""
    current_step: str = ""
    current_phase: str = ""
    active_entities: list[str] = Field(default_factory=list)
    active_constraints: list[str] = Field(default_factory=list)
    scope_level: MemoryScope | None = None
    scope: str = ""
    intent_hint: RetrievalIntent | None = None
    token_budget: int = Field(default=2000, ge=128, le=1_000_000)
    consistency: ConsistencyMode = ConsistencyMode.EVENTUAL
    cursor: str = ""
    page_size: int = Field(default=20, ge=1, le=100)


class RetrievedMemory(APIModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    memory_type: MemoryType
    layer: LifecycleLayer
    scope_level: MemoryScope
    scope: str = Field(min_length=1)
    content_version: int = Field(ge=1)
    evolution_status: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(ge=0.0)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)


class ContextPayload(APIModel):
    current_state: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    relevant_memory_ids: list[str] = Field(default_factory=list)
    conflict_notes: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    rendered_context: str = ""
    original_tokens: int = Field(default=0, ge=0)
    selected_tokens: int = Field(default=0, ge=0)
    dropped_reasons: dict[str, str] = Field(default_factory=dict)


class MemoryRetrievalResponse(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    intent: RetrievalIntent
    retrieval_plan: dict[str, Any] = Field(default_factory=dict)
    selected_memories: list[RetrievedMemory] = Field(default_factory=list)
    context: ContextPayload = Field(default_factory=ContextPayload)
    activations: list[Activation] = Field(default_factory=list)
    degraded_channels: list[str] = Field(default_factory=list)
    completeness: Literal["FULL", "PARTIAL", "NONE"] = "FULL"
    warnings: list[str] = Field(default_factory=list)
    next_cursor: str = ""
    total_count: int = Field(default=0, ge=0)


class ResumeTaskRequest(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    resume_token: str = ""
    expected_snapshot_version: int | None = Field(default=None, ge=1)


class ResumeTaskResponse(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    working_state: WorkingSnapshot | None = None
    episode_snapshot: EpisodeSnapshot | None = None
    restored_state: dict[str, Any] = Field(default_factory=dict)
    stale_resources: list[str] = Field(default_factory=list)
    required_revalidation: list[str] = Field(default_factory=list)
    resume_token: str = Field(min_length=1)


class ForgetRequest(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    target_memory_ids: list[str] = Field(default_factory=list)
    normalized_key: str = ""
    scope_level: MemoryScope | None = None
    scope: str = ""
    instruction: str = ""
    dry_run: bool = True
    confirm: bool = False
    cascade: bool = True

    @model_validator(mode="after")
    def validate_selector(self) -> "ForgetRequest":
        if not any((self.target_memory_ids, self.normalized_key, self.scope, self.instruction)):
            raise ValueError("forget request requires an explicit selector")
        if not self.dry_run and not self.confirm:
            raise ValueError("forget execution requires confirm=true")
        if self.scope and self.scope_level is None:
            raise ValueError("scope_level is required when scope is provided")
        return self


class ForgetResponse(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    forget_request_id: str = Field(min_length=1)
    authority_status: ForgetStatus
    projection_status: ForgetStatus
    verification_status: ForgetStatus
    residual_retrieval_count: int = Field(default=0, ge=0)
    affected_memory_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DiagnosticRequest(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    target_type: Literal[
        "memory",
        "evidence",
        "lineage",
        "retrieval_trace",
        "projection",
        "candidate",
    ]
    target_id: str = Field(min_length=1)
    include_sensitive: bool = False
    cursor: str = ""
    page_size: int = Field(default=50, ge=1, le=200)


class DiagnosticResponse(APIModel):
    api_version: Literal["vnext/v1"] = "vnext/v1"
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    target_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    items: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: str = ""
    redacted: bool = True


class LegacySearchCompatibilityResponse(APIModel):
    """Stable old response shape; it contains no retrieval algorithm."""

    results: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    total_count: int = Field(default=0, ge=0)
    trace_id: str = ""

    @classmethod
    def from_vnext(cls, response: MemoryRetrievalResponse) -> "LegacySearchCompatibilityResponse":
        results = [
            {
                "memory_id": item.memory_id,
                "memory_type": item.memory_type.value.lower(),
                "content": item.content,
                "score": item.score,
                "memory_level": item.layer.value.lower(),
                "metadata": {
                    "scope": item.scope,
                    "content_version": item.content_version,
                },
            }
            for item in response.selected_memories
        ]
        return cls(
            results=results,
            latency_ms=0.0,
            total_count=response.total_count,
            trace_id=response.trace_id,
        )


__all__ = [
    "APIError",
    "APIErrorCode",
    "Activation",
    "ConsistencyMode",
    "ContextPayload",
    "DiagnosticRequest",
    "DiagnosticResponse",
    "ForgetRequest",
    "ForgetResponse",
    "ForgetStatus",
    "FormationResponseStatus",
    "LegacySearchCompatibilityResponse",
    "MemoryRetrievalRequest",
    "MemoryRetrievalResponse",
    "RetrievedMemory",
    "ResumeTaskRequest",
    "ResumeTaskResponse",
    "WriteEventRequest",
    "WriteEventResponse",
]
