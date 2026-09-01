"""
SQLAlchemy ORM 模型定义

定义数据库表结构，与 Pydantic schemas 对应。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    """事件表 — 对应 MemoryEvent"""
    __tablename__ = "events"

    event_id = Column(String(32), primary_key=True)
    # Nullable during the compatibility window; vNext writes require both keys.
    tenant_id = Column(String(64), index=True, nullable=True)
    source_type = Column(String(32), index=True)
    event_type = Column(String(64), index=True)
    user_id = Column(String(64), index=True)
    session_id = Column(String(64))
    turn_id = Column(String(64), index=True)
    scene = Column(String(64), index=True)
    task_type = Column(String(128), index=True)
    occurred_at = Column(DateTime)
    text = Column(Text)
    payload = Column(JSON)
    tool_calls = Column(JSON)
    schema_version = Column(String(16), default="1.1")
    content_version = Column(Integer, nullable=False, default=1)
    policy_version = Column(String(64), nullable=True)
    retention_class = Column(String(32), nullable=True)
    sensitivity_level = Column(String(32), nullable=True)
    policy_action = Column(String(16), nullable=True)
    idempotency_key = Column(String(128), nullable=True, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    source_hash = Column(String(64), index=True)
    redactions = Column(JSON)
    quality = Column(JSON)


class PreferenceRow(Base):
    """偏好记忆表 — 对应 PreferenceMemory"""
    __tablename__ = "preferences"

    memory_id = Column(String(32), primary_key=True)
    # Nullable for legacy rows; vNext Authority writes always bind a tenant.
    tenant_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True)
    memory_type = Column(String(16), default="preference")
    preference_type = Column(String(32))
    content = Column(Text)
    payload = Column(JSON)
    scope_scene = Column(String(64), index=True)
    scope_task_type = Column(String(128), index=True)
    scope_app = Column(String(64))
    is_global = Column(Boolean, default=False)
    confidence = Column(Float, default=0.0)
    quality_score = Column(Float, default=1.0)
    extract_source = Column(String(32), default="implicit_inference")
    status = Column(String(16), default="active", index=True)
    level = Column(String(16), default="long")
    version = Column(Integer, default=1)
    parent_id = Column(String(32))
    root_id = Column(String(32))
    evidences = Column(JSON)
    # --- 向量索引同步状态 ---
    pending_index = Column(Boolean, default=True, index=True)
    index_version = Column(Integer, default=0, index=True)
    projection_version = Column(Integer, default=0, index=True)

    tags = Column(JSON)
    extra_payload = Column(JSON)
    # --- 健康度字段（遗忘模块使用）---

    health_score = Column(Float, default=1.0, index=True)
    stability = Column(Float, default=1.0)
    last_accessed_at = Column(DateTime, nullable=True)
    access_count_30d = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeRow(Base):
    """知识记忆表 — 对应 KnowledgeMemory"""
    __tablename__ = "knowledge"
    __table_args__ = (
        Index(
            "ix_knowledge_fact_subject_predicate",
            "user_id",
            "subject",
            "predicate",
        ),
    )

    memory_id = Column(String(32), primary_key=True)
    # Nullable for legacy rows; vNext Authority writes always bind a tenant.
    tenant_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True)
    memory_type = Column(String(16), default="knowledge")
    knowledge_type = Column(String(32))
    name = Column(String(256))
    content = Column(Text)
    steps = Column(JSON)
    tools = Column(JSON)
    template_body = Column(Text)
    # --- 事实性知识（knowledge_type=FACT，见 REFACTOR_PLAN_V2 §4.8）---
    subject = Column(String(256))
    predicate = Column(String(256))
    object_value = Column(Text)
    object_type = Column(String(32))
    single_value = Column(Boolean, nullable=True)
    scope_scene = Column(String(64), index=True)
    scope_task_type = Column(String(128), index=True)
    scope_app = Column(String(64))
    confidence = Column(Float, default=0.0)
    success_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    status = Column(String(16), default="active", index=True)
    level = Column(String(16), default="long")
    version = Column(Integer, default=1)
    parent_id = Column(String(32))
    evidences = Column(JSON)
    extra_payload = Column(JSON)
    # --- 向量索引同步状态 ---
    pending_index = Column(Boolean, default=True, index=True)
    index_version = Column(Integer, default=0, index=True)
    projection_version = Column(Integer, default=0, index=True)

    health_score = Column(Float, default=1.0, index=True)
    stability = Column(Float, default=1.0)
    last_accessed_at = Column(DateTime, nullable=True)
    access_count_30d = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class KnowledgeVersionRow(Base):
    """Immutable snapshot of a knowledge version before in-place evolution."""
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("memory_id", "version", name="uq_knowledge_versions_memory_version"),
    )

    snapshot_id = Column(String(96), primary_key=True)
    memory_id = Column(String(32), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class ConflictRow(Base):
    """冲突记录表 — 对应 ConflictRecord"""
    __tablename__ = "conflicts"

    conflict_id = Column(String(32), primary_key=True)
    user_id = Column(String(64), default="default", index=True)
    old_memory_id = Column(String(32))
    new_memory_id = Column(String(32))
    memory_type = Column(String(16))
    old_content = Column(Text)
    new_content = Column(Text)
    conflict_field = Column(String(64))
    decision = Column(String(16), default="pending")
    reason = Column(Text)
    result_memory_id = Column(String(32))
    created_at = Column(DateTime, default=datetime.now)
    resolved_at = Column(DateTime)


class ForgetRow(Base):
    """遗忘记录表 — 对应 ForgetRecord"""
    __tablename__ = "forget_history"

    record_id = Column(String(32), primary_key=True)
    tenant_id = Column(String(64), nullable=True, index=True)
    user_id = Column(String(64), index=True)
    request_id = Column(String(128), nullable=True, index=True)
    idempotency_key = Column(String(128), nullable=True, index=True)
    state = Column(String(32), nullable=False, default="ACCEPTED", index=True)
    actor_id = Column(String(128), nullable=True)
    reason = Column(Text, nullable=True)
    instruction = Column(Text)
    target_memory_ids = Column(JSON)
    affected_memory_ids = Column(JSON, nullable=True)
    warnings = Column(JSON, nullable=True)
    deleted_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)


class MemoryLineageRow(Base):
    """记忆版本关系的权威记录；每次状态迁移追加一条。"""

    __tablename__ = "memory_lineage"
    __table_args__ = (
        Index(
            "ix_memory_lineage_memory_type_created_at",
            "memory_id",
            "memory_type",
            "created_at",
        ),
        Index("ix_memory_lineage_root_memory_id", "root_memory_id"),
    )

    lineage_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=True)
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    parent_memory_id = Column(String(64), nullable=True)
    root_memory_id = Column(String(64), nullable=True)
    semantic_version = Column(Integer, nullable=False, default=1)
    content_version = Column(Integer, nullable=False, default=1)
    schema_version = Column(String(16), nullable=False, default="vnext/v1")
    policy_version = Column(String(64), nullable=True)
    evidence_revision = Column(Integer, nullable=False, default=1)
    transition_action = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class MemoryEvidenceRow(Base):
    """记忆证据的权威记录；同一记忆中的同一事件来源只能写入一次。"""

    __tablename__ = "memory_evidence"
    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "event_id",
            "source_hash",
            name="uq_memory_evidence_memory_event_source",
        ),
        Index(
            "ix_memory_evidence_memory_type_occurred_at",
            "memory_id",
            "memory_type",
            "occurred_at",
        ),
        Index("ix_memory_evidence_event_id", "event_id"),
    )

    evidence_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=True)
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    event_id = Column(String(64), nullable=False)
    source_hash = Column(String(64), nullable=False)
    content_ref = Column(String(256), nullable=True)
    schema_version = Column(String(16), nullable=False, default="vnext/v1")
    content_version = Column(Integer, nullable=False, default=1)
    policy_version = Column(String(64), nullable=True)
    sensitivity_level = Column(String(32), nullable=True)
    source_type = Column(String(32), nullable=False)
    excerpt = Column(Text, nullable=False, default="")
    occurred_at = Column(DateTime, nullable=False, default=datetime.now)
    quality_score = Column(Float, nullable=False, default=1.0)
    safety_audit_id = Column(String(64), nullable=True, index=True)


class MemoryProjectionOutboxRow(Base):
    """异步索引和缓存投影的可靠事务 outbox。"""

    __tablename__ = "memory_projection_outbox"
    __table_args__ = (
        Index("ix_memory_projection_outbox_status_next_retry", "status", "next_retry_at"),
        Index(
            "ix_memory_projection_outbox_memory_id_type",
            "memory_id",
            "memory_type",
        ),
        Index(
            "uq_memory_projection_outbox_event",
            "tenant_id",
            "memory_id",
            "memory_type",
            "operation",
            "event_id",
            unique=True,
            sqlite_where=text("event_id IS NOT NULL"),
        ),
    )

    outbox_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=True)
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    operation = Column(String(32), nullable=False)
    event_id = Column(String(64), nullable=True, index=True)
    content_version = Column(Integer, nullable=False, default=1)
    projection_type = Column(String(32), nullable=False, default="vector")
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_retry_at = Column(DateTime, nullable=True)
    error_code = Column(String(128), nullable=False, default="")
    priority = Column(Integer, nullable=False, default=0)
    backoff_policy = Column(JSON, nullable=True, default=dict)
    lease_version = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(64), nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True)
    dead_lettered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class ExtractionTaskRow(Base):
    """可重试抽取任务；不保存事件正文、prompt 或异常原文。"""
    __tablename__ = "extraction_tasks"
    __table_args__ = (
        UniqueConstraint("task_key", name="uq_extraction_tasks_task_key"),
    )

    task_id = Column(String(32), primary_key=True)
    task_key = Column(String(64), nullable=False)
    event_id = Column(String(32), nullable=False, index=True)
    event_ids = Column(JSON, nullable=False)
    tenant_id = Column(String(64), nullable=False, default="", index=True)
    user_id = Column(String(64), nullable=False, index=True)
    extractor_type = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(128), nullable=False, default="")
    candidate_ids = Column(JSON, nullable=False, default=list)
    candidate_statuses = Column(JSON, nullable=False, default=dict)
    memory_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class ShortTermMemoryRow(Base):
    """短期记忆（工作记忆）：会话内事件缓冲，TTL 到期清理（REFACTOR_PLAN_V2 §4.4）。"""
    __tablename__ = "short_term_memory"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), index=True)
    session_id = Column(String(128), index=True)
    event_id = Column(String(64), index=True)
    source_type = Column(String(32), default="")
    text = Column(Text, default="")
    payload = Column(JSON)
    scene = Column(String(64), default="")
    task_type = Column(String(128), default="")
    created_at = Column(DateTime, default=datetime.now)
    ttl_until = Column(DateTime, nullable=True, index=True)


class MidTermMemoryRow(Base):
    """中期记忆（情景记忆）：完成任务轨迹/事件序列，健康度衰减（REFACTOR_PLAN_V2 §4.4）。"""
    __tablename__ = "mid_term_memory"

    episode_id = Column(String(64), primary_key=True)
    user_id = Column(String(64), index=True)
    session_ids = Column(JSON)
    scene = Column(String(64), default="")
    task_type = Column(String(128), default="")
    event_ids = Column(JSON)
    trajectory_summary = Column(Text, default="")
    tools = Column(JSON)
    outcome = Column(String(16), default="success")
    occurred_at = Column(DateTime, nullable=True)
    last_accessed_at = Column(DateTime, nullable=True)
    decay_score = Column(Float, default=1.0)
    status = Column(String(16), default="active", index=True)  # active | consolidated | archived
    created_at = Column(DateTime, default=datetime.now)


class WorkingStateRow(Base):
    """Versioned task working state; one current row per tenant/user/task."""

    __tablename__ = "working_states"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "task_id", name="uq_working_states_owner_task"
        ),
        CheckConstraint("version >= 1", name="ck_working_states_version_positive"),
    )

    working_state_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    project_id = Column(String(128), nullable=False, default="", index=True)
    session_id = Column(String(128), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    state = Column(JSON, nullable=False, default=dict)
    field_sources = Column(JSON, nullable=False, default=dict)
    last_event_id = Column(String(64), nullable=True)
    schema_version = Column(String(16), nullable=False, default="vnext/v1")
    content_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class TaskEpisodeRow(Base):
    """Episode authority row with resumable snapshot and monotonic sequence."""

    __tablename__ = "task_episodes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','SUSPENDED','COMPLETED','FAILED','ARCHIVED')",
            name="ck_task_episodes_status",
        ),
        CheckConstraint("snapshot_version >= 1", name="ck_task_episodes_snapshot_version"),
        CheckConstraint("last_event_seq >= 0", name="ck_task_episodes_last_event_seq"),
    )

    episode_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    project_id = Column(String(128), nullable=False, default="", index=True)
    session_id = Column(String(128), nullable=False, default="")
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)
    current_phase = Column(String(64), nullable=False, default="")
    goal = Column(Text, nullable=False, default="")
    snapshot = Column(JSON, nullable=False, default=dict)
    snapshot_version = Column(Integer, nullable=False, default=1)
    last_event_seq = Column(Integer, nullable=False, default=0)
    resume_token_hash = Column(String(128), nullable=True)
    stale_resources = Column(JSON, nullable=False, default=list)
    required_revalidation = Column(JSON, nullable=False, default=list)
    resource_versions = Column(JSON, nullable=False, default=dict)
    schema_version = Column(String(16), nullable=False, default="vnext/v1")
    content_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class EpisodeEventRow(Base):
    """Append-only episode event stream, unique by episode and sequence."""

    __tablename__ = "episode_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "episode_id", "seq_no", name="uq_episode_events_seq"),
        CheckConstraint("seq_no >= 1", name="ck_episode_events_seq_positive"),
    )

    episode_event_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    episode_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    seq_no = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    source_event_id = Column(String(64), nullable=False, index=True)
    content_version = Column(Integer, nullable=False, default=1)
    occurred_at = Column(DateTime, nullable=False, default=datetime.now)


class MemoryCandidateRow(Base):
    """Candidate staging row; status is explicit so ordinary retrieval can exclude it."""

    __tablename__ = "memory_candidates"
    __table_args__ = (
        CheckConstraint(
            "formation_status = 'CANDIDATE'",
            name="ck_memory_candidates_formation_status",
        ),
        CheckConstraint(
            "status IN ('ACCUMULATING','CONFIRMED','REJECTED','REVIEW')",
            name="ck_memory_candidates_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_memory_candidates_confidence",
        ),
        UniqueConstraint(
            "tenant_id", "user_id", "candidate_id", name="uq_memory_candidates_owner_id"
        ),
    )

    candidate_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(32), nullable=False, index=True)
    normalized_key = Column(String(256), nullable=False, index=True)
    claim = Column(JSON, nullable=False)
    scope_level = Column(String(32), nullable=False, index=True)
    scope = Column(String(256), nullable=False, index=True)
    formation_status = Column(String(32), nullable=False, default="CANDIDATE")
    status = Column(String(16), nullable=False, default="ACCUMULATING", index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    utility = Column(Float, nullable=False, default=0.0)
    stability = Column(Float, nullable=False, default=0.0)
    frequency = Column(Integer, nullable=False, default=0)
    evidence_refs = Column(JSON, nullable=False, default=list)
    supporting_episode_ids = Column(JSON, nullable=False, default=list)
    conflicting_memory_ids = Column(JSON, nullable=False, default=list)
    content_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class MemoryActivationRow(Base):
    """Retrieval activation audit row, separate from memory lifecycle state."""

    __tablename__ = "memory_activations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "query_id", "memory_id", "content_version",
            name="uq_memory_activations_query_memory_version",
        ),
        CheckConstraint("rank >= 1", name="ck_memory_activations_rank_positive"),
    )

    activation_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    query_id = Column(String(128), nullable=False, index=True)
    memory_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=False, default="")
    intent = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="RECALLED", index=True)
    rank = Column(Integer, nullable=False)
    initial_score = Column(Float, nullable=False, default=0.0)
    reranked_score = Column(Float, nullable=False, default=0.0)
    included_in_context = Column(Boolean, nullable=False, default=False)
    retrieval_id = Column(String(64), nullable=True, index=True)
    project_id = Column(String(128), nullable=False, default="")
    session_id = Column(String(128), nullable=False, default="")
    usage_source = Column(String(64), nullable=True)
    usage_confidence = Column(Float, nullable=True)
    content_version = Column(Integer, nullable=False, default=1)
    activated_at = Column(DateTime, nullable=False, default=datetime.now)
    used_at = Column(DateTime, nullable=True)


class RetrievalLogRow(Base):
    """Trace-safe retrieval summary; raw query/content is intentionally absent."""

    __tablename__ = "retrieval_logs"
    __table_args__ = (
        CheckConstraint("candidate_count >= 0", name="ck_retrieval_logs_candidate_count"),
        CheckConstraint("selected_count >= 0", name="ck_retrieval_logs_selected_count"),
    )

    retrieval_log_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    query_id = Column(String(128), nullable=False, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    intent = Column(String(32), nullable=False, index=True)
    consistency = Column(String(32), nullable=False, default="EVENTUAL")
    plan = Column(JSON, nullable=False, default=dict)
    candidate_count = Column(Integer, nullable=False, default=0)
    selected_count = Column(Integer, nullable=False, default=0)
    degraded_channels = Column(JSON, nullable=False, default=list)
    latency_ms = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)


class RolloutStateRow(Base):
    """Durable read-path rollout pointer; it never mutates Authority data."""

    __tablename__ = "vnext_rollout_state"

    state_id = Column(String(32), primary_key=True)
    current_level = Column(Integer, nullable=False, default=0)
    current_mode = Column(String(16), nullable=False, default="legacy")
    rollback_window_minutes = Column(Integer, nullable=False, default=60)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class RolloutObservationRow(Base):
    """Redacted, durable safety window counters for one rollout level."""

    __tablename__ = "vnext_rollout_observations"

    window_id = Column(String(128), primary_key=True)
    level = Column(Integer, nullable=False, index=True)
    request_count = Column(Integer, nullable=False, default=0)
    policy_leak_count = Column(Integer, nullable=False, default=0)
    cross_tenant_count = Column(Integer, nullable=False, default=0)
    forget_residual_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    observed_at = Column(DateTime, nullable=False, default=datetime.now, index=True)


class RolloutAuditRow(Base):
    """Durable redacted CUTOVER/ROLLBACK audit record."""

    __tablename__ = "vnext_rollout_audits"

    audit_id = Column(String(128), primary_key=True)
    action = Column(String(16), nullable=False, index=True)
    previous_level = Column(Integer, nullable=False)
    next_level = Column(Integer, nullable=False)
    previous_mode = Column(String(16), nullable=False)
    next_mode = Column(String(16), nullable=False)
    window_id = Column(String(128), nullable=False, index=True)
    reason = Column(String(256), nullable=False, default="")
    rollback_window_minutes = Column(Integer, nullable=False, default=60)
    metrics = Column(JSON, nullable=False, default=dict)
    recorded_at = Column(DateTime, nullable=False, default=datetime.now, index=True)


class ObservabilityTraceRow(Base):
    """Durable redacted trace span; never an Authority/content store."""

    __tablename__ = "observability_traces"
    __table_args__ = (
        Index("ix_observability_traces_tenant_created", "tenant_id", "created_at"),
        Index("ix_observability_traces_trace_created", "trace_id", "created_at"),
        Index("ix_observability_traces_category_status", "category", "status"),
    )

    span_id = Column(String(128), primary_key=True)
    trace_id = Column(String(128), nullable=False, index=True)
    parent_id = Column(String(128), nullable=True)
    kind = Column(String(32), nullable=False, index=True)
    layer = Column(String(64), nullable=False, default="")
    category = Column(String(32), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="SUCCEEDED", index=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=True, index=True)
    event_id = Column(String(128), nullable=True, index=True)
    memory_id = Column(String(128), nullable=True, index=True)
    query_id = Column(String(128), nullable=True, index=True)
    ids = Column(JSON, nullable=False, default=dict)
    hashes = Column(JSON, nullable=False, default=dict)
    classification = Column(JSON, nullable=False, default=dict)
    scores = Column(JSON, nullable=False, default=dict)
    reason_codes = Column(JSON, nullable=False, default=list)
    redacted = Column(Boolean, nullable=False, default=True)
    sampled = Column(Boolean, nullable=False, default=True)
    retention_class = Column(String(16), nullable=False, default="NORMAL", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)


class ObservabilityMetricRow(Base):
    """Durable aggregate metric; samples are bounded and contain no content."""

    __tablename__ = "observability_metrics"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "metric_name", "category", "status",
            name="uq_observability_metrics_dimension",
        ),
        Index("ix_observability_metrics_tenant_updated", "tenant_id", "updated_at"),
        Index("ix_observability_metrics_trace", "trace_id"),
        Index("ix_observability_metrics_task", "task_id"),
        Index("ix_observability_metrics_event", "event_id"),
        Index("ix_observability_metrics_memory", "memory_id"),
        Index("ix_observability_metrics_query", "query_id"),
        Index("ix_observability_metrics_category_status", "category", "status"),
    )

    metric_id = Column(String(256), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    metric_name = Column(String(128), nullable=False, index=True)
    category = Column(String(32), nullable=False, default="INFRASTRUCTURE", index=True)
    status = Column(String(32), nullable=False, default="SUCCEEDED", index=True)
    trace_id = Column(String(128), nullable=True)
    task_id = Column(String(128), nullable=True)
    event_id = Column(String(128), nullable=True)
    memory_id = Column(String(128), nullable=True)
    query_id = Column(String(128), nullable=True)
    count = Column(Integer, nullable=False, default=0)
    total_value = Column(Float, nullable=False, default=0.0)
    min_value = Column(Float, nullable=False, default=0.0)
    max_value = Column(Float, nullable=False, default=0.0)
    samples = Column(JSON, nullable=False, default=list)
    retention_class = Column(String(16), nullable=False, default="AGGREGATE")
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    expires_at = Column(DateTime, nullable=True)


class ObservabilityAuditRow(Base):
    """Durable redacted audit, including management/dashboard access."""

    __tablename__ = "observability_audits"
    __table_args__ = (
        Index("ix_observability_audits_tenant_created", "tenant_id", "created_at"),
        Index("ix_observability_audits_trace", "trace_id"),
        Index("ix_observability_audits_task", "task_id"),
        Index("ix_observability_audits_event", "event_id"),
        Index("ix_observability_audits_memory", "memory_id"),
        Index("ix_observability_audits_query", "query_id"),
        Index("ix_observability_audits_category_status", "category", "status"),
    )

    audit_id = Column(String(128), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    actor_id = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False, index=True)
    category = Column(String(32), nullable=False, default="MANAGEMENT", index=True)
    status = Column(String(32), nullable=False, default="SUCCEEDED", index=True)
    trace_id = Column(String(128), nullable=True)
    task_id = Column(String(128), nullable=True)
    event_id = Column(String(128), nullable=True)
    memory_id = Column(String(128), nullable=True)
    query_id = Column(String(128), nullable=True)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)
    details = Column(JSON, nullable=False, default=dict)
    redacted = Column(Boolean, nullable=False, default=True)
    retention_class = Column(String(16), nullable=False, default="ELEVATED")
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    expires_at = Column(DateTime, nullable=True, index=True)


class IdempotencyRecordRow(Base):
    """Tenant-scoped request deduplication record without raw request body."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_idempotency_records_tenant_key"
        ),
        CheckConstraint(
            "status IN ('ACCEPTED','COMMITTED','REJECTED')",
            name="ck_idempotency_records_status",
        ),
    )

    idempotency_record_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="ACCEPTED", index=True)
    response_ref = Column(String(256), nullable=True)
    event_id = Column(String(64), nullable=True, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    expires_at = Column(DateTime, nullable=True, index=True)
