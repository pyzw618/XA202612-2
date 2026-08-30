"""Frozen vNext vocabulary and compatibility mappings.

The legacy API used ``level`` for ``short/mid/long``.  vNext keeps that
surface in adapters only and models lifecycle, type, status, action, usage,
scope, and retrieval intent as separate dimensions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Final, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class _ContractEnum(str, Enum):
    """String enum with stable wire values."""


class LifecycleLayer(_ContractEnum):
    """Where an object lives in the memory lifecycle."""

    WORKING = "WORKING"
    EPISODE = "EPISODE"
    LONG_TERM = "LONG_TERM"


class MemoryType(_ContractEnum):
    """What a long-term memory represents."""

    PREFERENCE = "PREFERENCE"
    SEMANTIC = "SEMANTIC"
    PROCEDURAL = "PROCEDURAL"
    EPISODIC = "EPISODIC"


class FormationStatus(_ContractEnum):
    """Formation pipeline stage; it is independent from lifecycle layer."""

    RAW_EVENT = "RAW_EVENT"
    WORKING_STATE = "WORKING_STATE"
    EPISODE_CHECKPOINT = "EPISODE_CHECKPOINT"
    CANDIDATE = "CANDIDATE"
    CONSOLIDATED_MEMORY = "CONSOLIDATED_MEMORY"


class EvolutionStatus(_ContractEnum):
    """Current status of a long-term version."""

    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class EvolutionAction(_ContractEnum):
    """A decision applied to a memory version; not a status."""

    REINFORCE = "REINFORCE"
    REVISE = "REVISE"
    SUPERSEDE = "SUPERSEDE"
    COEXIST = "COEXIST"
    REVIEW = "REVIEW"


class ActivationStatus(_ContractEnum):
    """Retrieval/usage progression without changing a memory's layer."""

    RECALLED = "RECALLED"
    SELECTED = "SELECTED"
    IN_CONTEXT = "IN_CONTEXT"
    USED = "USED"


class MemoryScope(_ContractEnum):
    """Scope precedence for long-term memory resolution."""

    TASK = "TASK"
    PROJECT = "PROJECT"
    APPLICATION = "APPLICATION"
    DOMAIN = "DOMAIN"
    GLOBAL = "GLOBAL"
    SESSION = "SESSION"


class RetrievalIntent(_ContractEnum):
    """The seven stable retrieval intents used by Router and evaluation."""

    CURRENT_STATE = "CURRENT_STATE"
    TASK_HISTORY = "TASK_HISTORY"
    PREFERENCE = "PREFERENCE"
    SEMANTIC_FACT = "SEMANTIC_FACT"
    PROCEDURE = "PROCEDURE"
    EXPERIENCE = "EXPERIENCE"
    MIXED = "MIXED"


class CandidateStatus(_ContractEnum):
    """Staging status; candidates are not ordinary retrieval results."""

    ACCUMULATING = "ACCUMULATING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    REVIEW = "REVIEW"


class EpisodeStatus(_ContractEnum):
    """Task episode lifecycle."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class BoundaryCheckpointType(_ContractEnum):
    """Kinds of task boundary checkpoint emitted by the detector."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    EXPLICIT = "EXPLICIT"
    PHASE = "PHASE"
    CONTEXT_PRESSURE = "CONTEXT_PRESSURE"


class BoundaryTriggerKind(_ContractEnum):
    """What caused a boundary decision."""

    HARD = "HARD"
    RULE = "RULE"
    MODEL = "MODEL"


class LineageRelation(_ContractEnum):
    """Allowed evidence/version relationships."""

    DERIVED_FROM = "DERIVED_FROM"
    REINFORCES = "REINFORCES"
    REVISES = "REVISES"
    SUPERSEDES = "SUPERSEDES"
    COEXISTS_WITH = "COEXISTS_WITH"
    DELETED_BY = "DELETED_BY"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GovernedModel(BaseModel):
    """Common identity, version and governance fields for vnext/v1 objects."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    schema_version: Literal["vnext/v1"] = "vnext/v1"
    content_version: int = Field(default=1, ge=1)
    policy_version: str = Field(default="policy/v1", min_length=1)
    retention_class: str = Field(default="standard", min_length=1)
    sensitivity_level: str = Field(default="NONE", min_length=1)
    created_by: str = Field(default="system", min_length=1)
    updated_by: str = Field(default="system", min_length=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class MemoryEventContract(GovernedModel):
    """Policy-processed event entering the canonical write path."""

    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    policy_action: Literal["ALLOW", "MASK", "DROP", "REVIEW"]
    source_hash: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)


class WorkingPatchOperation(BaseModel):
    """A field-level state change; full replacement is intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add", "replace", "remove"]
    path: str = Field(min_length=2, pattern=r"^/")
    value: Any = None
    source: str = Field(default="system", min_length=1)
    priority: int | None = Field(default=None, ge=0, le=100)


class WorkingPatch(GovernedModel):
    task_id: str = Field(min_length=1)
    base_version: int = Field(ge=0)
    operations: list[WorkingPatchOperation] = Field(min_length=1)
    event_refs: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class WorkingSnapshot(GovernedModel):
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    current_goal: str = Field(min_length=1)
    current_step: str = ""
    pending_steps: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    active_entities: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recent_findings: list[str] = Field(default_factory=list)
    recent_failures: list[str] = Field(default_factory=list)
    next_action: str = ""
    snapshot_version: int = Field(default=1, ge=1)


class EpisodeEventContract(GovernedModel):
    episode_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    seq_no: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    source_event_id: str = Field(min_length=1)


class EpisodeSnapshot(GovernedModel):
    episode_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    status: EpisodeStatus
    current_phase: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    pending_steps: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    last_event_seq: int = Field(default=0, ge=0)
    snapshot_version: int = Field(default=1, ge=1)
    stale_resources: list[str] = Field(default_factory=list)
    required_revalidation: list[str] = Field(default_factory=list)


class Candidate(GovernedModel):
    candidate_id: str = Field(min_length=1)
    memory_type: MemoryType
    normalized_key: str = Field(min_length=1)
    claim: dict[str, Any] = Field(min_length=1)
    scope_level: MemoryScope
    scope: str = Field(min_length=1)
    formation_status: Literal[FormationStatus.CANDIDATE] = FormationStatus.CANDIDATE
    status: CandidateStatus = CandidateStatus.ACCUMULATING
    confidence: float = Field(ge=0.0, le=1.0)
    utility: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    frequency: int = Field(default=0, ge=0)
    evidence_refs: list[str] = Field(default_factory=list)
    supporting_episode_ids: list[str] = Field(default_factory=list)
    conflicting_memory_ids: list[str] = Field(default_factory=list)


class LongTermEnvelope(GovernedModel):
    layer: Literal[LifecycleLayer.LONG_TERM] = LifecycleLayer.LONG_TERM
    memory_id: str = Field(min_length=1)
    memory_type: MemoryType
    normalized_key: str = Field(min_length=1)
    content: dict[str, Any] = Field(min_length=1)
    scope_level: MemoryScope
    scope: str = Field(min_length=1)
    evolution_status: EvolutionStatus = EvolutionStatus.ACTIVE
    confidence: float = Field(ge=0.0, le=1.0)
    utility: float = Field(ge=0.0, le=1.0)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    projection_version: int = Field(default=0, ge=0)
    evidence_refs: list[str] = Field(min_length=1)
    candidate_id: str | None = None


class Evidence(GovernedModel):
    evidence_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    episode_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    content_ref: str = Field(min_length=1)
    causal_group_id: str = Field(min_length=1)
    occurred_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    explicitness: float = Field(ge=0.0, le=1.0)
    trust_level: str = Field(min_length=1)


class Lineage(GovernedModel):
    lineage_id: str = Field(min_length=1)
    from_id: str = Field(min_length=1)
    to_id: str = Field(min_length=1)
    relation: LineageRelation
    evidence_id: str | None = None
    reason: str = Field(min_length=1)


class Activation(GovernedModel):
    activation_id: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    intent: RetrievalIntent
    status: ActivationStatus
    rank: int = Field(ge=1)
    initial_score: float = Field(ge=0.0)
    reranked_score: float = Field(ge=0.0)
    included_in_context: bool = False
    activated_at: datetime = Field(default_factory=_utc_now)
    used_at: datetime | None = None


LEGACY_LAYER_MAP: Final[Mapping[str, LifecycleLayer]] = {
    "short": LifecycleLayer.WORKING,
    "mid": LifecycleLayer.EPISODE,
    "long": LifecycleLayer.LONG_TERM,
}

LEGACY_TYPE_MAP: Final[Mapping[str, MemoryType]] = {
    "preference": MemoryType.PREFERENCE,
    "output_style": MemoryType.PREFERENCE,
    "tool_preference": MemoryType.PREFERENCE,
    "workflow_preference": MemoryType.PREFERENCE,
    "scene_preference": MemoryType.PREFERENCE,
    "format_preference": MemoryType.PREFERENCE,
    "language_preference": MemoryType.PREFERENCE,
    "knowledge.fact": MemoryType.SEMANTIC,
    "fact": MemoryType.SEMANTIC,
    "knowledge.workflow": MemoryType.PROCEDURAL,
    "workflow": MemoryType.PROCEDURAL,
    "knowledge.template": MemoryType.PROCEDURAL,
    "template": MemoryType.PROCEDURAL,
    "knowledge.case": MemoryType.EPISODIC,
    "case": MemoryType.EPISODIC,
}

LEGACY_STATUS_MAP: Final[Mapping[str, EvolutionStatus]] = {
    "active": EvolutionStatus.ACTIVE,
    "archived": EvolutionStatus.ARCHIVED,
    "deleted": EvolutionStatus.DELETED,
}


def _legacy_value(value: object) -> str:
    """Normalize a legacy enum or string without accepting arbitrary objects."""

    if isinstance(value, str):
        return value.strip().lower()
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value.strip().lower()
    raise ValueError(f"unsupported legacy value: {value!r}")


def map_legacy_memory_level(value: object) -> LifecycleLayer:
    """Map only the old ``short/mid/long`` layer field to vNext."""

    normalized = _legacy_value(value)
    try:
        return LEGACY_LAYER_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy memory level: {value!r}") from exc


def map_legacy_memory_type(value: object, *, knowledge_type: object | None = None) -> MemoryType:
    """Map legacy preference/knowledge values to an explicit vNext type."""

    normalized = _legacy_value(value)
    if normalized == "knowledge" and knowledge_type is not None:
        normalized = f"knowledge.{_legacy_value(knowledge_type)}"
    try:
        return LEGACY_TYPE_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy memory type: {value!r}") from exc


def map_legacy_memory_status(value: object) -> EvolutionStatus:
    """Map legacy status values while keeping pending data out of ACTIVE."""

    normalized = _legacy_value(value)
    try:
        return LEGACY_STATUS_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported legacy memory status: {value!r}") from exc


__all__ = [
    "ActivationStatus",
    "Activation",
    "BoundaryCheckpointType",
    "BoundaryTriggerKind",
    "Candidate",
    "CandidateStatus",
    "EpisodeEventContract",
    "EpisodeSnapshot",
    "EpisodeStatus",
    "EvolutionAction",
    "EvolutionStatus",
    "Evidence",
    "FormationStatus",
    "GovernedModel",
    "LEGACY_LAYER_MAP",
    "LEGACY_STATUS_MAP",
    "LEGACY_TYPE_MAP",
    "LifecycleLayer",
    "Lineage",
    "LineageRelation",
    "LongTermEnvelope",
    "MemoryEventContract",
    "MemoryScope",
    "MemoryType",
    "RetrievalIntent",
    "WorkingPatch",
    "WorkingPatchOperation",
    "WorkingSnapshot",
    "map_legacy_memory_level",
    "map_legacy_memory_status",
    "map_legacy_memory_type",
]
