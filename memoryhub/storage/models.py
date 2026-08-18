"""
SQLAlchemy ORM 模型定义

定义数据库表结构，与 Pydantic schemas 对应。
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    """事件表 — 对应 MemoryEvent"""
    __tablename__ = "events"

    event_id = Column(String(32), primary_key=True)
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
    source_hash = Column(String(64), index=True)
    redactions = Column(JSON)
    quality = Column(JSON)


class PreferenceRow(Base):
    """偏好记忆表 — 对应 PreferenceMemory"""
    __tablename__ = "preferences"

    memory_id = Column(String(32), primary_key=True)
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
    # --- 向量索引同步状态 ---
    pending_index = Column(Boolean, default=True, index=True)
    index_version = Column(Integer, default=0, index=True)

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
    user_id = Column(String(64), index=True)
    instruction = Column(Text)
    target_memory_ids = Column(JSON)
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
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    parent_memory_id = Column(String(64), nullable=True)
    root_memory_id = Column(String(64), nullable=True)
    semantic_version = Column(Integer, nullable=False, default=1)
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
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    event_id = Column(String(64), nullable=False)
    source_hash = Column(String(64), nullable=False)
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
    )

    outbox_id = Column(String(64), primary_key=True)
    memory_id = Column(String(64), nullable=False, index=True)
    memory_type = Column(String(16), nullable=False, index=True)
    operation = Column(String(32), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime, nullable=True)
    error_code = Column(String(128), nullable=False, default="")
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
    user_id = Column(String(64), nullable=False, index=True)
    extractor_type = Column(String(16), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(128), nullable=False, default="")
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
