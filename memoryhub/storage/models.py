"""
SQLAlchemy ORM 模型定义

定义数据库表结构，与 Pydantic schemas 对应。
"""

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint,
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

    memory_id = Column(String(32), primary_key=True)
    user_id = Column(String(64), index=True)
    memory_type = Column(String(16), default="knowledge")
    knowledge_type = Column(String(32))
    name = Column(String(256))
    content = Column(Text)
    steps = Column(JSON)
    tools = Column(JSON)
    template_body = Column(Text)
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
