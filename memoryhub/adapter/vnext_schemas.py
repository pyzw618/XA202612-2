"""Versioned vNext API DTOs.

These models define the wire contract only.  They do not call repositories,
retrievers, model providers, or write services; adapters delegate business
behavior to the canonical application services defined by S0-02.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Compatibility adapters for the legacy SearchRequest/Response surface live in
# this wire-contract module so higher layers can convert without duplication.
from memoryhub.adapter.schemas import (
    FactMemory,
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
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

    @classmethod
    def from_legacy_search_request(
        cls,
        request: SearchRequest,
        *,
        tenant_id: str | None = None,
        request_id: str = "",
    ) -> "MemoryRetrievalRequest":
        """Upgrade a legacy SearchRequest to the vNext retrieval contract.

        The legacy request has no tenant_id; callers should supply it explicitly.
        When omitted, the tenant_id falls back to user_id so unit tests and
        legacy adapters keep working, but production callers must provide it.
        """
        scope_level, scope = _legacy_scope_to_vnext(request.context, request.project_id)
        fallback_request_id = f"legacy-{request.user_id}-{hash(request.query) & 0xFFFFFFFF:08x}"
        return cls(
            api_version="vnext/v1",
            request_id=request_id or fallback_request_id,
            tenant_id=tenant_id or request.user_id or "default",
            user_id=request.user_id or "default",
            query=request.query,
            session_id=request.session_id,
            scope_level=scope_level,
            scope=scope,
            intent_hint=_legacy_intent_hint(request.level, request.memory_types),
            token_budget=max(128, request.top_k * 40),
            page_size=max(1, min(100, request.top_k or 5)),
        )


class RetrievedMemory(APIModel):
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    memory_type: MemoryType
    layer: LifecycleLayer
    scope_level: MemoryScope
    scope: str = Field(min_length=1)
    content_version: int = Field(ge=1)
    projection_version: int = Field(default=0, ge=0)
    evolution_status: str = Field(min_length=1)
    content: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(ge=0.0)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
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

    def to_legacy_search_response(self, *, latency_ms: float = 0.0) -> SearchResponse:
        """Downgrade a vNext response to the legacy SearchResponse shape.

        This preserves the wire contract for existing REST/MCP/CLI clients while
        still carrying vNext identity in result metadata.
        """
        results: list[SearchResult] = []
        preferences: list[PreferenceMemory] = []
        knowledge: list[KnowledgeMemory] = []
        facts: list[FactMemory] = []
        for item in self.selected_memories:
            result = _retrieved_memory_to_search_result(item)
            results.append(result)
            typed = _retrieved_memory_to_legacy_typed(item)
            if isinstance(typed, PreferenceMemory):
                preferences.append(typed)
            elif isinstance(typed, KnowledgeMemory):
                knowledge.append(typed)
            elif isinstance(typed, FactMemory):
                facts.append(typed)
        return SearchResponse(
            results=results,
            preferences=preferences,
            knowledge=knowledge,
            facts=facts,
            latency_ms=round(latency_ms, 2),
            total_count=self.total_count,
        )


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
    """Stable old response shape; it contains no retrieval algorithm.

    Prefer ``MemoryRetrievalResponse.to_legacy_search_response`` for full
    backward-compatible SearchResponse objects; this dict-only adapter remains
    for lightweight diagnostics and dashboards.
    """

    results: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    total_count: int = Field(default=0, ge=0)
    trace_id: str = ""

    @classmethod
    def from_vnext(
        cls,
        response: MemoryRetrievalResponse,
        *,
        latency_ms: float = 0.0,
    ) -> "LegacySearchCompatibilityResponse":
        results = []
        preferences = []
        knowledge = []
        facts = []
        for item in response.selected_memories:
            results.append(_retrieved_memory_to_legacy_dict(item))
            typed = _retrieved_memory_to_legacy_typed(item)
            if isinstance(typed, PreferenceMemory):
                preferences.append(typed.model_dump())
            elif isinstance(typed, KnowledgeMemory):
                knowledge.append(typed.model_dump())
            elif isinstance(typed, FactMemory):
                facts.append(typed.model_dump())
        return cls(
            results=results,
            preferences=preferences,
            knowledge=knowledge,
            facts=facts,
            latency_ms=round(latency_ms, 2),
            total_count=response.total_count,
            trace_id=response.trace_id,
        )


# ---------------------------------------------------------------------------
# Legacy SearchRequest/SearchResponse compatibility helpers (S3-01)
# ---------------------------------------------------------------------------


def _legacy_scope_to_vnext(
    context: SceneScope,
    project_id: str,
) -> tuple[MemoryScope | None, str]:
    """Map legacy SceneScope/project_id to vNext scope_level and scope string."""
    if project_id:
        return MemoryScope.PROJECT, f"PROJECT:{project_id}"
    if context.task_type:
        return MemoryScope.TASK, f"TASK:{context.task_type}"
    if context.app:
        return MemoryScope.APPLICATION, f"APPLICATION:{context.app}"
    if context.scene:
        return MemoryScope.SESSION, f"SESSION:{context.scene}"
    return None, ""


def _legacy_intent_hint(level: str, memory_types: list[str]) -> RetrievalIntent:
    """Infer a vNext intent hint from legacy level/memory_type filters."""
    normalized_level = (level or "").strip().lower()
    if normalized_level == "short":
        return RetrievalIntent.CURRENT_STATE
    if normalized_level == "mid":
        return RetrievalIntent.TASK_HISTORY
    normalized_types = {t.strip().lower() for t in memory_types if isinstance(t, str)}
    if normalized_types == {"preference"}:
        return RetrievalIntent.PREFERENCE
    if normalized_types and normalized_types <= {"knowledge", "fact"}:
        return RetrievalIntent.SEMANTIC_FACT
    return RetrievalIntent.MIXED


def _legacy_memory_level(layer: LifecycleLayer) -> str:
    return {
        LifecycleLayer.WORKING: "short",
        LifecycleLayer.EPISODE: "mid",
        LifecycleLayer.LONG_TERM: "long",
    }.get(layer, "long")


def _legacy_memory_type(memory_type: MemoryType) -> str:
    if memory_type is MemoryType.PREFERENCE:
        return "preference"
    if memory_type is MemoryType.SEMANTIC:
        return "fact"
    return "knowledge"


def _legacy_scene_scope(scope_level: MemoryScope, scope: str) -> SceneScope:
    value = scope.split(":", 1)[-1] if ":" in scope else scope
    if scope_level is MemoryScope.GLOBAL:
        return SceneScope()
    if scope_level is MemoryScope.PROJECT:
        return SceneScope(scene=value)
    return SceneScope(scene=value, task_type=value, app=value)


def _extract_content_text(content: dict[str, Any]) -> str:
    for key in ("text", "content", "value", "name"):
        value = content.get(key)
        if isinstance(value, str) and value:
            return value
    parts = [str(v) for v in content.values() if isinstance(v, str)]
    return " ".join(parts)


def _retrieved_memory_to_legacy_dict(item: RetrievedMemory) -> dict[str, Any]:
    # The legacy dict adapter preserves the original vNext layer value so that
    # lightweight dashboards continue to see the vNext layer identity.
    return {
        "memory_id": item.memory_id,
        "memory_type": _legacy_memory_type(item.memory_type),
        "content": _extract_content_text(item.content),
        "score": item.score,
        "source": "+".join(item.source_ids) or "vnext",
        "memory_level": item.layer.value.lower(),
        "metadata": {
            "scope": item.scope,
            "scope_level": item.scope_level.value,
            "content_version": item.content_version,
            "evolution_status": item.evolution_status,
            "score_breakdown": item.score_breakdown,
        },
    }


def _retrieved_memory_to_search_result(item: RetrievedMemory) -> SearchResult:
    return SearchResult(
        memory_id=item.memory_id,
        memory_type=_legacy_memory_type(item.memory_type),
        content=_extract_content_text(item.content),
        score=item.score,
        source="+".join(item.source_ids) or "vnext",
        metadata={
            "scope": item.scope,
            "scope_level": item.scope_level.value,
            "content_version": item.content_version,
            "evolution_status": item.evolution_status,
            "score_breakdown": item.score_breakdown,
        },
        memory_level=_legacy_memory_level(item.layer),
    )


def _retrieved_memory_to_legacy_typed(
    item: RetrievedMemory,
) -> PreferenceMemory | KnowledgeMemory | FactMemory | None:
    """Best-effort conversion to one of the legacy typed memory models."""
    from memoryhub.adapter.schemas import MemoryLevel, MemoryStatus

    status_map = {
        "ACTIVE": MemoryStatus.ACTIVE,
        "ARCHIVED": MemoryStatus.ARCHIVED,
        "DELETED": MemoryStatus.DELETED,
        "DORMANT": MemoryStatus.PENDING,
        "SUPERSEDED": MemoryStatus.ARCHIVED,
    }
    level_map = {
        LifecycleLayer.WORKING: MemoryLevel.SHORT,
        LifecycleLayer.EPISODE: MemoryLevel.MID,
        LifecycleLayer.LONG_TERM: MemoryLevel.LONG,
    }
    common: dict[str, Any] = {
        "user_id": item.user_id,
        "memory_id": item.memory_id,
        "confidence": item.score,
        "status": status_map.get(item.evolution_status.upper(), MemoryStatus.ACTIVE),
        "version": item.content_version,
        "level": level_map.get(item.layer, MemoryLevel.LONG),
    }
    content_text = _extract_content_text(item.content)
    if item.memory_type is MemoryType.PREFERENCE:
        return PreferenceMemory(
            **common,
            scope=_legacy_scene_scope(item.scope_level, item.scope),
            text=content_text,
            payload=item.content,
            preference_type="output_style",
            is_global=item.scope_level is MemoryScope.GLOBAL,
        )
    if item.memory_type is MemoryType.SEMANTIC:
        scope_label = "global" if item.scope_level is MemoryScope.GLOBAL else "project"
        return FactMemory(
            **common,
            scope=scope_label,
            fact_id=item.memory_id,
            source_text=content_text,
            object_value=content_text,
        )
    if item.memory_type in (MemoryType.PROCEDURAL, MemoryType.EPISODIC):
        return KnowledgeMemory(
            **common,
            scope=_legacy_scene_scope(item.scope_level, item.scope),
            name=item.content.get("name", item.memory_id),
            content=content_text,
            steps=item.content.get("steps", []),
        )
    return None


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
