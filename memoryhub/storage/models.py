"""
SQLAlchemy ORM 模型定义

定义数据库表结构，与 Pydantic schemas 对应。
"""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, Text
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
    scene = Column(String(64), index=True)
    task_type = Column(String(128), index=True)
    occurred_at = Column(DateTime)
    text = Column(Text)
    payload = Column(JSON)
    schema_version = Column(String(16), default="1.0")
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
    scope_scene = Column(String(64), index=True)
    scope_task_type = Column(String(128), index=True)
    scope_app = Column(String(64))
    confidence = Column(Float, default=0.0)
    status = Column(String(16), default="active", index=True)
    level = Column(String(16), default="long")
    version = Column(Integer, default=1)
    parent_id = Column(String(32))
    evidences = Column(JSON)
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
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ConflictRow(Base):
    """冲突记录表 — 对应 ConflictRecord"""
    __tablename__ = "conflicts"

    conflict_id = Column(String(32), primary_key=True)
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
