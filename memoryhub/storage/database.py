"""
数据库引擎与会话管理

基于 SQLAlchemy ORM，提供 SQLite 持久化和 Repository CRUD。
"""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker

from memoryhub.adapter.schemas import (
    ExtractionTask,
    ExtractionTaskStatus,
    ExtractionType,
    ForgetRecord,
    KnowledgeMemory,
    MemoryEvent,
    MemoryStatus,
    PreferenceMemory,
    SceneScope,
)
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.storage.models import (
    Base,
    ConflictRow,
    EventRow,
    ExtractionTaskRow,
    ForgetRow,
    KnowledgeRow,
    KnowledgeVersionRow,
    MidTermMemoryRow,
    PreferenceRow,
    ShortTermMemoryRow,
)

# ============================================================
# 数据库管理器
# ============================================================


class Database:
    """
    SQLite 数据库管理器。

    使用方式:
        db = Database("data/memoryhub.db")
        db.init_schema()
        with db.session() as s:
            s.add(row)
            s.commit()
    """

    def __init__(self, db_path: str = "data/memoryhub.db"):
        self.db_path = db_path
        self.engine = None
        self.session_factory = None

    def init_schema(self) -> None:
        """初始化数据库 schema — 创建所有表。"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        # Repeated migration/initialization must release the previous pool
        # first.  This is required on Windows where an undisposed SQLite pool
        # keeps the database file locked between idempotent runs.
        if self.engine is not None:
            self.engine.dispose()

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        # WAL 模式 — 读写不互斥
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self._ensure_compatible_schema()
        self.session_factory = sessionmaker(bind=self.engine)

    def _ensure_compatible_schema(self) -> None:
        """Apply additive SQLite migrations required by the current data contract."""
        migrations = {
            "events": {
                "tenant_id": "VARCHAR(64)",
                "turn_id": "VARCHAR(64)",
                "tool_calls": "JSON",
                "schema_version": "VARCHAR(16) DEFAULT '1.1'",
                "content_version": "INTEGER DEFAULT 1",
                "policy_version": "VARCHAR(64)",
                "retention_class": "VARCHAR(32)",
                "sensitivity_level": "VARCHAR(32)",
                "policy_action": "VARCHAR(16)",
                "idempotency_key": "VARCHAR(128)",
                "trace_id": "VARCHAR(64)",
                "source_hash": "VARCHAR(64)",
                "redactions": "JSON",
                "quality": "JSON",
            },
            "preferences": {
                "tenant_id": "VARCHAR(64)",
                "payload": "JSON",
                "is_global": "BOOLEAN DEFAULT 0",
                "quality_score": "FLOAT DEFAULT 1.0",
                "extract_source": "VARCHAR(32) DEFAULT 'implicit_inference'",
                "root_id": "VARCHAR(32)",
                "tags": "JSON",
                "extra_payload": "JSON",
                "pending_index": "BOOLEAN DEFAULT 1",
                "index_version": "INTEGER DEFAULT 0",
                "projection_version": "INTEGER DEFAULT 0",
                "health_score": "FLOAT DEFAULT 1.0",
                "stability": "FLOAT DEFAULT 1.0",
                "last_accessed_at": "DATETIME",
                "access_count_30d": "INTEGER DEFAULT 0",
            },
            "knowledge": {
                "tenant_id": "VARCHAR(64)",
                "extra_payload": "JSON",
                "pending_index": "BOOLEAN DEFAULT 1",
                "index_version": "INTEGER DEFAULT 0",
                "projection_version": "INTEGER DEFAULT 0",
                "health_score": "FLOAT DEFAULT 1.0",
                "stability": "FLOAT DEFAULT 1.0",
                "last_accessed_at": "DATETIME",
                "access_count_30d": "INTEGER DEFAULT 0",
            },
            "conflicts": {
                "user_id": "VARCHAR(64) DEFAULT 'default'",
                "result_memory_id": "VARCHAR(32)",
                "resolved_at": "DATETIME",
            },
            "working_states": {
                "field_sources": "JSON DEFAULT '{}'",
            },
            "task_episodes": {
                "resource_versions": "JSON DEFAULT '{}'",
            },
            "memory_lineage": {
                "tenant_id": "VARCHAR(64)",
                "user_id": "VARCHAR(64)",
                "content_version": "INTEGER DEFAULT 1",
                "schema_version": "VARCHAR(16) DEFAULT 'vnext/v1'",
                "policy_version": "VARCHAR(64)",
            },
            "memory_evidence": {
                "tenant_id": "VARCHAR(64)",
                "user_id": "VARCHAR(64)",
                "content_ref": "VARCHAR(256)",
                "schema_version": "VARCHAR(16) DEFAULT 'vnext/v1'",
                "content_version": "INTEGER DEFAULT 1",
                "policy_version": "VARCHAR(64)",
                "sensitivity_level": "VARCHAR(32)",
            },
            "memory_projection_outbox": {
                "tenant_id": "VARCHAR(64)",
                "user_id": "VARCHAR(64)",
                "event_id": "VARCHAR(64)",
                "content_version": "INTEGER DEFAULT 1",
                "projection_type": "VARCHAR(32) DEFAULT 'vector'",
                "max_attempts": "INTEGER DEFAULT 5",
                "priority": "INTEGER DEFAULT 0",
                "backoff_policy": "JSON",
                "lease_version": "INTEGER DEFAULT 0",
                "lease_token": "VARCHAR(64)",
                "lease_expires_at": "DATETIME",
                "dead_lettered_at": "DATETIME",
            },
            "forget_history": {
                "tenant_id": "VARCHAR(64)",
                "request_id": "VARCHAR(128)",
                "idempotency_key": "VARCHAR(128)",
                "state": "VARCHAR(32) DEFAULT 'ACCEPTED'",
                "actor_id": "VARCHAR(128)",
                "reason": "TEXT",
                "affected_memory_ids": "JSON",
                "warnings": "JSON",
            },
            "extraction_tasks": {
                "tenant_id": "VARCHAR(64) DEFAULT ''",
                "candidate_ids": "JSON DEFAULT '[]'",
                "candidate_statuses": "JSON DEFAULT '{}'",
                "memory_ids": "JSON DEFAULT '[]'",
            },
        }
        with self.engine.begin() as conn:
            for table, columns in migrations.items():
                existing = {row[1] for row in conn.exec_driver_sql(
                    f"PRAGMA table_info({table})"
                ).fetchall()}
                for column, ddl in columns.items():
                    if column not in existing:
                        conn.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"
                        )
                # SQLite 不支持在 ALTER TABLE 中直接加索引，需单独创建
                if table in ("preferences", "knowledge"):
                    conn.exec_driver_sql(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id "
                        f"ON {table} (tenant_id)"
                    )
                    conn.exec_driver_sql(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_pending_index "
                        f"ON {table} (pending_index)"
                    )
                    conn.exec_driver_sql(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_index_version "
                        f"ON {table} (index_version)"
                    )
                    conn.exec_driver_sql(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_projection_version "
                        f"ON {table} (projection_version)"
                    )

            # Base.metadata.create_all() creates newly introduced tables on both new
            # and existing SQLite files.  Create their lookup indexes explicitly as
            # well so databases initialized by older releases receive the same plan.
            for index_ddl in (
                "CREATE INDEX IF NOT EXISTS ix_events_tenant_id "
                "ON events (tenant_id)",
                "CREATE INDEX IF NOT EXISTS ix_events_idempotency_key "
                "ON events (idempotency_key)",
                "CREATE INDEX IF NOT EXISTS ix_events_trace_id "
                "ON events (trace_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_lineage_tenant_user "
                "ON memory_lineage (tenant_id, user_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_evidence_tenant_user "
                "ON memory_evidence (tenant_id, user_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_tenant_user "
                "ON memory_projection_outbox (tenant_id, user_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_event_id "
                "ON memory_projection_outbox (event_id)",
                "CREATE INDEX IF NOT EXISTS ix_forget_history_tenant_user "
                "ON forget_history (tenant_id, user_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_forget_history_idempotency "
                "ON forget_history (tenant_id, user_id, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_projection_outbox_event_version "
                "ON memory_projection_outbox "
                "(tenant_id, event_id, content_version, projection_type, operation)",
                "CREATE INDEX IF NOT EXISTS ix_memory_lineage_memory_type_created_at "
                "ON memory_lineage (memory_id, memory_type, created_at)",
                "CREATE INDEX IF NOT EXISTS ix_memory_lineage_root_memory_id "
                "ON memory_lineage (root_memory_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_evidence_memory_type_occurred_at "
                "ON memory_evidence (memory_id, memory_type, occurred_at)",
                "CREATE INDEX IF NOT EXISTS ix_memory_evidence_event_id "
                "ON memory_evidence (event_id)",
                "CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_status_next_retry "
                "ON memory_projection_outbox (status, next_retry_at)",
                "CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_memory_id_type "
                "ON memory_projection_outbox (memory_id, memory_type)",
            ):
                conn.exec_driver_sql(index_ddl)

    @contextmanager
    def session(self) -> Session:
        """
        获取数据库会话（上下文管理器）。

        使用方式:
            with db.session() as s:
                result = s.query(PreferenceRow).all()
        """
        if self.session_factory is None:
            raise RuntimeError("数据库未初始化，请先调用 init_schema()")
        s = self.session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def close(self) -> None:
        """关闭数据库连接。"""
        if self.engine:
            self.engine.dispose()


# ============================================================
# 工具函数 — ORM ↔ Pydantic 转换
# ============================================================

def _pref_row_to_pydantic(row: PreferenceRow) -> PreferenceMemory:
    """PreferenceRow → PreferenceMemory"""
    return PreferenceMemory(
        memory_id=row.memory_id,
        user_id=row.user_id,
        preference_type=row.preference_type,
        text=row.content,
        payload=row.payload or {},
        scope=SceneScope(
            scene=row.scope_scene or "",
            task_type=row.scope_task_type or "",
            app=row.scope_app or "",
        ),
        is_global=bool(row.is_global),
        confidence=row.confidence or 0.0,
        quality_score=row.quality_score if row.quality_score is not None else 1.0,
        extract_source=row.extract_source or "implicit_inference",
        status=MemoryStatus(row.status) if row.status else MemoryStatus.ACTIVE,
        level=row.level or "long",
        version=row.version or 1,
        parent_id=row.parent_id or "",
        root_id=row.root_id or "",
        evidences=row.evidences or [],
        tags=row.tags or [],
        extra_payload=row.extra_payload or {},
        health_score=row.health_score if row.health_score is not None else 1.0,
        stability=row.stability if row.stability is not None else 1.0,
        last_accessed_at=row.last_accessed_at,
        access_count_30d=row.access_count_30d or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _know_row_to_pydantic(row: KnowledgeRow) -> KnowledgeMemory:
    """KnowledgeRow → KnowledgeMemory"""
    return KnowledgeMemory(
        memory_id=row.memory_id,
        user_id=row.user_id,
        knowledge_type=row.knowledge_type,
        name=row.name or "",
        content=row.content,
        steps=row.steps or [],
        tools=row.tools or [],
        template_body=row.template_body or "",
        subject=row.subject or "",
        predicate=row.predicate or "",
        object_value=row.object_value or "",
        object_type=row.object_type or "",
        single_value=row.single_value,
        scope=SceneScope(
            scene=row.scope_scene or "",
            task_type=row.scope_task_type or "",
            app=row.scope_app or "",
        ),
        confidence=row.confidence or 0.0,
        success_count=row.success_count or 0,
        total_count=row.total_count or 0,
        status=MemoryStatus(row.status) if row.status else MemoryStatus.ACTIVE,
        level=row.level or "long",
        version=row.version or 1,
        parent_id=row.parent_id or "",
        evidences=row.evidences or [],
        extra_payload=row.extra_payload or {},
        health_score=row.health_score if row.health_score is not None else 1.0,
        stability=row.stability if row.stability is not None else 1.0,
        last_accessed_at=row.last_accessed_at,
        access_count_30d=row.access_count_30d or 0,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ============================================================
# 事件 CRUD
# ============================================================


class EventRepository:
    """Convert an event ORM row into a complete MemoryEvent model."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _parse_occurred_at(value: str):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None

    @classmethod
    def _to_row(cls, event: MemoryEvent) -> EventRow:
        # 统一走 model_dump(mode="json")：Gate 放行的安全事件（_SafeMemoryEvent）
        # 容器是深度只读的 _ImmutableMapping，直接访问 .payload 会给 SQLAlchemy
        # JSON 列传入不可序列化对象（TypeError）；model_dump 会按契约投影回普通
        # JSON dict/list，保证持久化格式兼容。
        data = event.model_dump(mode="json")
        return EventRow(
            event_id=data["event_id"],
            source_type=data["source_type"],
            event_type=data["event_type"],
            user_id=data["user_id"],
            session_id=data["session_id"],
            turn_id=data["turn_id"],
            scene=data["scene"],
            task_type=data["task_type"],
            occurred_at=cls._parse_occurred_at(data["occurred_at"]),
            text=data["text"],
            payload=data["payload"],
            tool_calls=data["tool_calls"],
            schema_version=data["schema_version"],
            source_hash=data["source_hash"],
            redactions=data["redactions"],
            quality=data["quality"],
        )

    def save(self, event: MemoryEvent) -> None:
        with self.db.session() as session:
            session.merge(self._to_row(event))

    def batch_save(self, events: list[MemoryEvent]) -> int:
        with self.db.session() as session:
            for event in events:
                session.merge(self._to_row(event))
        return len(events)

    def get_by_id(self, event_id: str) -> Optional[MemoryEvent]:
        with self.db.session() as session:
            row = session.query(EventRow).filter(EventRow.event_id == event_id).first()
            return _event_row_to_pydantic(row) if row is not None else None

    def get_vnext_contract(self, event_id: str) -> MemoryEventContract | None:
        """Read the policy-approved vNext envelope without exposing event text.

        Legacy extraction still uses ``get_by_id``.  The Formation worker uses
        this narrow projection so tenant, policy and canonical task identity
        remain bound to the event that passed EventGateway.
        """

        with self.db.session() as session:
            row = session.query(EventRow).filter(EventRow.event_id == event_id).first()
            if row is None or not row.tenant_id or not row.policy_action:
                return None
            occurred_at = row.occurred_at
            if occurred_at is None:
                return None
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
            return MemoryEventContract(
                tenant_id=row.tenant_id,
                user_id=row.user_id or "",
                event_id=row.event_id,
                event_type=row.event_type or "event",
                source_type=row.source_type or "unknown",
                task_id=row.task_type or "",
                session_id=row.session_id or "",
                occurred_at=occurred_at,
                payload=dict(row.payload or {}),
                policy_action=row.policy_action,
                source_hash=row.source_hash or "",
                idempotency_key=row.idempotency_key or row.event_id,
                trace_id=row.trace_id or row.event_id,
                content_version=row.content_version or 1,
                policy_version=row.policy_version or "policy/v1",
                retention_class=row.retention_class or "standard",
                sensitivity_level=row.sensitivity_level or "NONE",
            )

    def get_by_source_hash(self, source_hash: str) -> Optional[MemoryEvent]:
        """按来源内容指纹去重查询；用于相同 source_hash 不重复进入记忆链路。"""
        with self.db.session() as session:
            row = (
                session.query(EventRow)
                .filter(EventRow.source_hash == source_hash)
                .order_by(EventRow.occurred_at.asc())
                .first()
            )
            return _event_row_to_pydantic(row) if row is not None else None

    def get_by_session(self, session_id: str) -> list[MemoryEvent]:
        with self.db.session() as session:
            rows = session.query(EventRow).filter(EventRow.session_id == session_id).all()
            return [_event_row_to_pydantic(row) for row in rows]

    def get_by_task_type(self, user_id: str, task_type: str) -> list[MemoryEvent]:
        with self.db.session() as session:
            rows = session.query(EventRow).filter(
                EventRow.user_id == user_id, EventRow.task_type == task_type
            ).all()
            return [_event_row_to_pydantic(row) for row in rows]

    def get_trajectory(
        self, user_id: str, session_id: str, task_type: str = ""
    ) -> list[MemoryEvent]:
        """Load one persisted safe trajectory in deterministic execution order."""
        with self.db.session() as session:
            query = session.query(EventRow).filter(
                EventRow.user_id == user_id,
                EventRow.session_id == session_id,
            )
            if task_type:
                query = query.filter(EventRow.task_type == task_type)
            rows = query.order_by(
                EventRow.occurred_at.asc(),
                EventRow.turn_id.asc(),
                EventRow.event_id.asc(),
            ).all()
            return [_event_row_to_pydantic(row) for row in rows]

    def get_recent(self, user_id: str, limit: int = 100, offset: int = 0) -> list[MemoryEvent]:
        with self.db.session() as session:
            rows = (
                session.query(EventRow).filter(EventRow.user_id == user_id)
                .order_by(EventRow.occurred_at.desc()).offset(offset).limit(limit).all()
            )
            return [_event_row_to_pydantic(row) for row in rows]

    def count(self, user_id: str) -> int:
        """统计指定用户的事件总数（供列表分页）。"""
        with self.db.session() as session:
            return (
                session.query(func.count(EventRow.event_id))
                .filter(EventRow.user_id == user_id)
                .scalar()
                or 0
            )


def _event_row_to_pydantic(row: EventRow) -> MemoryEvent:
    return MemoryEvent(
        event_id=row.event_id,
        source_type=row.source_type,
        event_type=row.event_type or "",
        user_id=row.user_id or "",
        session_id=row.session_id or "",
        turn_id=row.turn_id or "",
        scene=row.scene or "",
        task_type=row.task_type or "",
        occurred_at=(row.occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.occurred_at else ""),
        text=row.text or "",
        payload=row.payload or {},
        tool_calls=row.tool_calls or [],
        schema_version=row.schema_version or "1.1",
        source_hash=row.source_hash or "0" * 64,
        redactions=row.redactions or [],
        quality=row.quality or {},
    )


# ============================================================
# ?? CRUD
# ============================================================


class PreferenceRepository:
    """偏好记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, memory: PreferenceMemory, *, session: Session | None = None) -> None:
        """保存偏好；传入 session 时由调用方控制事务边界。"""
        if session is None:
            with self.db.session() as managed_session:
                self._save(managed_session, memory)
            return
        self._save(session, memory)

    @staticmethod
    def _save(session: Session, memory: PreferenceMemory) -> None:
        # root_id 兜底：有 parent 但没显式传 root 时，从父记录继承
        root_id = memory.root_id or None
        if not root_id and memory.parent_id:
            parent = (
                session.query(PreferenceRow)
                .filter(PreferenceRow.memory_id == memory.parent_id)
                .first()
            )
            if parent is not None:
                root_id = parent.root_id or parent.memory_id
        row = PreferenceRow(
            memory_id=memory.memory_id,
            tenant_id=(
                memory.extra_payload.get("vnext_authority", {}) or {}
            ).get("tenant_id"),
            user_id=memory.user_id,
            preference_type=(
                memory.preference_type.value
                if hasattr(memory.preference_type, "value")
                else str(memory.preference_type)
            ),
            content=memory.text,
            payload=memory.payload,
            scope_scene=memory.scope.scene,
            scope_task_type=memory.scope.task_type,
            scope_app=memory.scope.app,
            is_global=memory.is_global,
            confidence=memory.confidence,
            quality_score=memory.quality_score,
            extract_source=memory.extract_source,
            status=(
                memory.status.value
                if hasattr(memory.status, "value")
                else str(memory.status)
            ),
            level=(
                memory.level.value if hasattr(memory.level, "value") else memory.level
            ),
            version=memory.version,
            parent_id=memory.parent_id or None,
            root_id=root_id,
            evidences=(
                [e.model_dump(mode="json") for e in memory.evidences]
                if memory.evidences
                else []
            ),
            tags=memory.tags,
            extra_payload=memory.extra_payload,
            health_score=memory.health_score,
            stability=memory.stability,
            last_accessed_at=memory.last_accessed_at,
            access_count_30d=memory.access_count_30d,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            pending_index=True,
        )
        session.merge(row)

    def list_pending(self) -> list[PreferenceMemory]:
        """列出需要同步到向量索引的偏好记忆。"""
        with self.db.session() as s:
            rows = (
                s.query(PreferenceRow)
                .filter(PreferenceRow.pending_index.is_(True))
                .order_by(PreferenceRow.updated_at.desc())
                .all()
            )
            return [_pref_row_to_pydantic(r) for r in rows]

    def mark_indexed(self, memory_ids: list[str], index_version: int) -> None:
        """标记指定记忆已同步到向量索引。"""
        from datetime import datetime

        with self.db.session() as s:
            s.query(PreferenceRow).filter(
                PreferenceRow.memory_id.in_(memory_ids)
            ).update(
                {
                    "pending_index": False,
                    "index_version": index_version,
                    "updated_at": datetime.now(),
                },
                synchronize_session=False,
            )

    def get_by_id(self, memory_id: str) -> Optional[PreferenceMemory]:
        """按 ID 查询"""
        with self.db.session() as s:
            row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
            if row is None:
                return None
            return _pref_row_to_pydantic(row)

    def get_active(self, user_id: str, scene: str = "") -> list[PreferenceMemory]:
        """查询活跃偏好，支持场景过滤；无场景偏好时降级命中 is_global=true 偏好。"""
        with self.db.session() as s:
            q = s.query(PreferenceRow).filter(
                PreferenceRow.user_id == user_id,
                PreferenceRow.status == "active",
            )
            if scene:
                q = q.filter(
                    (PreferenceRow.scope_scene == scene)
                    | (PreferenceRow.scope_scene == "*")
                )
            rows = q.order_by(PreferenceRow.confidence.desc()).all()
            return [_pref_row_to_pydantic(r) for r in rows]

    def get_by_scope(self, user_id: str, scene: str, task_type: str) -> list[PreferenceMemory]:
        """按 scope 精确查询"""
        with self.db.session() as s:
            query = s.query(PreferenceRow).filter(
                PreferenceRow.user_id == user_id,
                PreferenceRow.scope_scene == scene,
                PreferenceRow.status == "active",
            )
            if task_type:
                query = query.filter(PreferenceRow.scope_task_type == task_type)
            rows = query.order_by(PreferenceRow.confidence.desc()).all()
            return [_pref_row_to_pydantic(r) for r in rows]

    def list_all(self, status: str = "active", user_id: str = "") -> list[PreferenceMemory]:
        """列出指定状态的全部偏好记忆（应用启动时全量加载用）"""
        with self.db.session() as s:
            query = s.query(PreferenceRow).filter(PreferenceRow.status == status)
            if user_id:
                query = query.filter(PreferenceRow.user_id == user_id)
            rows = query.order_by(PreferenceRow.confidence.desc()).all()
            return [_pref_row_to_pydantic(r) for r in rows]

    def update_status(self, memory_id: str, status: str, user_id: str = "") -> bool:
        """更新状态"""
        from datetime import datetime

        with self.db.session() as s:
            q = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id)
            if user_id:
                q = q.filter(PreferenceRow.user_id == user_id)
            return q.update({
                "status": status,
                "pending_index": True,
                "updated_at": datetime.now(),
            }) == 1

    def record_access(self, memory_id: str, user_id: str = "") -> bool:
        """Record an owner-bound retrieval for lifecycle health calculations."""
        with self.db.session() as session:
            query = session.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id)
            if user_id:
                query = query.filter(PreferenceRow.user_id == user_id)
            return query.update({
                "last_accessed_at": datetime.now(),
                "access_count_30d": func.coalesce(PreferenceRow.access_count_30d, 0) + 1,
                "updated_at": datetime.now(),
            }) == 1


    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """
        获取版本链（单条 SQL）。

        优先用 root_id 一次查全链；旧数据没有 root_id 时退回
        parent 链逐级追溯（仅过渡期，新写入都会填 root_id）。
        """
        with self.db.session() as s:
            row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
            if row is None:
                return []

            # 快路径：有 root_id → 一条 SQL 拿整条链，按版本升序
            if row.root_id:
                rows = (
                    s.query(PreferenceRow)
                    .filter(PreferenceRow.root_id == row.root_id)
                    .order_by(PreferenceRow.version)
                    .all()
                )
                if rows:
                    return [_pref_row_to_pydantic(r) for r in rows]

            # 慢路径（旧数据兜底）：parent 链追溯到根，再向下收集
            chain_ids = []
            current = row
            seen = set()
            while current is not None and current.memory_id not in seen:
                seen.add(current.memory_id)
                chain_ids.insert(0, current.memory_id)
                current = (
                    s.query(PreferenceRow)
                    .filter(PreferenceRow.memory_id == current.parent_id)
                    .first()
                    if current.parent_id
                    else None
                )
            child = (
                s.query(PreferenceRow)
                .filter(PreferenceRow.parent_id == row.memory_id)
                .all()
            )
            for c in sorted(child, key=lambda r: r.version):
                if c.memory_id not in seen:
                    chain_ids.append(c.memory_id)
            if not chain_ids:
                return []
            rows = (
                s.query(PreferenceRow)
                .filter(PreferenceRow.memory_id.in_(chain_ids))
                .all()
            )
            by_id = {r.memory_id: r for r in rows}
            return [_pref_row_to_pydantic(by_id[mid]) for mid in chain_ids if mid in by_id]


# ============================================================
# 知识 CRUD
# ============================================================


class KnowledgeRepository:
    """知识记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, memory: KnowledgeMemory, *, session: Session | None = None) -> None:
        """保存知识；传入 session 时由调用方控制事务边界。"""
        if session is None:
            with self.db.session() as managed_session:
                self._save(managed_session, memory)
            return
        self._save(session, memory)

    @staticmethod
    def _save(session: Session, memory: KnowledgeMemory) -> None:
        existing = session.get(KnowledgeRow, memory.memory_id)
        if existing is not None and memory.version > (existing.version or 1):
            snapshot_id = f"{memory.memory_id}:v{existing.version or 1}"
            if session.get(KnowledgeVersionRow, snapshot_id) is None:
                snapshot = _know_row_to_pydantic(existing)
                session.add(
                    KnowledgeVersionRow(
                        snapshot_id=snapshot_id,
                        memory_id=existing.memory_id,
                        user_id=existing.user_id,
                        version=existing.version or 1,
                        payload=snapshot.model_dump(mode="json"),
                        created_at=existing.updated_at or datetime.now(),
                    )
                )
        row = KnowledgeRow(
            memory_id=memory.memory_id,
            tenant_id=(
                memory.extra_payload.get("vnext_authority", {}) or {}
            ).get("tenant_id"),
            user_id=memory.user_id,
            knowledge_type=(
                memory.knowledge_type.value
                if hasattr(memory.knowledge_type, "value")
                else str(memory.knowledge_type)
            ),
            name=memory.name,
            content=memory.content,
            steps=memory.steps,
            tools=memory.tools,
            template_body=memory.template_body or None,
            subject=memory.subject or None,
            predicate=memory.predicate or None,
            object_value=memory.object_value or None,
            object_type=memory.object_type or None,
            single_value=memory.single_value,
            scope_scene=memory.scope.scene,
            scope_task_type=memory.scope.task_type,
            scope_app=memory.scope.app,
            confidence=memory.confidence,
            success_count=memory.success_count,
            total_count=memory.total_count,
            status=(
                memory.status.value
                if hasattr(memory.status, "value")
                else str(memory.status)
            ),
            level=(
                memory.level.value if hasattr(memory.level, "value") else memory.level
            ),
            version=memory.version,
            parent_id=memory.parent_id or None,
            evidences=(
                [e.model_dump(mode="json") for e in memory.evidences]
                if memory.evidences
                else []
            ),
            extra_payload=memory.extra_payload,
            health_score=memory.health_score,
            stability=memory.stability,
            last_accessed_at=memory.last_accessed_at,
            access_count_30d=memory.access_count_30d,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            pending_index=True,
        )
        session.merge(row)

    def get_version_history(
        self, memory_id: str, *, user_id: str = ""
    ) -> list[KnowledgeMemory]:
        """Return immutable prior snapshots followed by the current version."""
        with self.db.session() as s:
            query = s.query(KnowledgeVersionRow).filter(
                KnowledgeVersionRow.memory_id == memory_id
            )
            if user_id:
                query = query.filter(KnowledgeVersionRow.user_id == user_id)
            snapshots = [
                KnowledgeMemory.model_validate(row.payload)
                for row in query.order_by(KnowledgeVersionRow.version.asc()).all()
            ]
            current = s.get(KnowledgeRow, memory_id)
            if current is not None and (not user_id or current.user_id == user_id):
                current_memory = _know_row_to_pydantic(current)
                if not snapshots or snapshots[-1].version != current_memory.version:
                    snapshots.append(current_memory)
            return snapshots

    def list_pending(self) -> list[KnowledgeMemory]:
        """列出需要同步到向量索引的知识记忆。"""
        with self.db.session() as s:
            rows = (
                s.query(KnowledgeRow)
                .filter(KnowledgeRow.pending_index.is_(True))
                .order_by(KnowledgeRow.updated_at.desc())
                .all()
            )
            return [_know_row_to_pydantic(r) for r in rows]

    def mark_indexed(self, memory_ids: list[str], index_version: int) -> None:
        """标记指定记忆已同步到向量索引。"""
        from datetime import datetime

        with self.db.session() as s:
            s.query(KnowledgeRow).filter(
                KnowledgeRow.memory_id.in_(memory_ids)
            ).update(
                {
                    "pending_index": False,
                    "index_version": index_version,
                    "updated_at": datetime.now(),
                },
                synchronize_session=False,
            )

    def get_by_id(self, memory_id: str) -> Optional[KnowledgeMemory]:
        """按 ID 查询"""
        with self.db.session() as s:
            row = s.query(KnowledgeRow).filter(KnowledgeRow.memory_id == memory_id).first()
            if row is None:
                return None
            return _know_row_to_pydantic(row)

    def get_by_type(
        self, user_id: str, knowledge_type: str = "", status: str = "active"
    ) -> list[KnowledgeMemory]:
        """按类型查询"""
        with self.db.session() as s:
            q = s.query(KnowledgeRow).filter(
                KnowledgeRow.user_id == user_id,
                KnowledgeRow.status == status,
            )
            if knowledge_type:
                q = q.filter(KnowledgeRow.knowledge_type == knowledge_type)
            rows = q.order_by(KnowledgeRow.confidence.desc()).all()
            return [_know_row_to_pydantic(r) for r in rows]

    def get_by_scope(
        self, user_id: str, scene: str, task_type: str, status: str = "active"
    ) -> list[KnowledgeMemory]:
        """按场景和任务类型查询"""
        with self.db.session() as s:
            query = s.query(KnowledgeRow).filter(
                KnowledgeRow.user_id == user_id,
                KnowledgeRow.status == status,
            )
            if scene:
                query = query.filter(KnowledgeRow.scope_scene == scene)
            if task_type:
                query = query.filter(KnowledgeRow.scope_task_type == task_type)
            rows = query.order_by(KnowledgeRow.confidence.desc()).all()
            return [_know_row_to_pydantic(r) for r in rows]

    def list_all(self, status: str = "active", user_id: str = "") -> list[KnowledgeMemory]:
        """列出指定状态的全部知识记忆（应用启动时全量加载用）"""
        with self.db.session() as s:
            query = s.query(KnowledgeRow).filter(KnowledgeRow.status == status)
            if user_id:
                query = query.filter(KnowledgeRow.user_id == user_id)
            rows = query.order_by(KnowledgeRow.confidence.desc()).all()
            return [_know_row_to_pydantic(r) for r in rows]

    def update_status(self, memory_id: str, status: str, user_id: str = "") -> bool:
        """Update knowledge status with an optional owner constraint."""
        with self.db.session() as session:
            query = session.query(KnowledgeRow).filter(KnowledgeRow.memory_id == memory_id)
            if user_id:
                query = query.filter(KnowledgeRow.user_id == user_id)
            return query.update({
                "status": status,
                "pending_index": True,
                "updated_at": datetime.now(),
            }) == 1

    def search_by_name(
        self, keyword: str, user_id: str = ""
    ) -> list[KnowledgeMemory]:
        """按名称模糊搜索（可选限定用户）"""
        with self.db.session() as s:
            query = s.query(KnowledgeRow).filter(
                KnowledgeRow.name.contains(keyword),
                KnowledgeRow.status == "active",
            )
            if user_id:
                query = query.filter(KnowledgeRow.user_id == user_id)
            rows = query.order_by(KnowledgeRow.confidence.desc()).all()
            return [_know_row_to_pydantic(r) for r in rows]

    def record_access(self, memory_id: str, user_id: str = "") -> bool:
        """Record an owner-bound retrieval for lifecycle health calculations."""
        with self.db.session() as session:
            query = session.query(KnowledgeRow).filter(KnowledgeRow.memory_id == memory_id)
            if user_id:
                query = query.filter(KnowledgeRow.user_id == user_id)
            return query.update({
                "last_accessed_at": datetime.now(),
                "access_count_30d": func.coalesce(KnowledgeRow.access_count_30d, 0) + 1,
                "updated_at": datetime.now(),
            }) == 1


    def increment_usage(
        self, memory_id: str, success: bool, user_id: str = ""
    ) -> None:
        """记录使用情况并可选更新成功率（支持限定用户）"""
        with self.db.session() as s:
            updates = {
                "total_count": KnowledgeRow.total_count + 1,
                "updated_at": datetime.now(),
            }
            if success:
                updates["success_count"] = KnowledgeRow.success_count + 1
            query = s.query(KnowledgeRow).filter(KnowledgeRow.memory_id == memory_id)
            if user_id:
                query = query.filter(KnowledgeRow.user_id == user_id)
            query.update(updates)


# ============================================================
# 冲突 CRUD
# ============================================================


class ConflictRepository:
    """冲突记录仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, conflict) -> None:
        """保存冲突记录"""
        with self.db.session() as s:
            values = {
                "user_id": conflict.user_id,
                "old_memory_id": conflict.old_memory_id,
                "new_memory_id": conflict.new_memory_id,
                "memory_type": conflict.memory_type,
                "old_content": conflict.old_content,
                "new_content": conflict.new_content,
                "conflict_field": conflict.conflict_field,
                "decision": (
                    conflict.decision.value
                    if hasattr(conflict.decision, "value")
                    else conflict.decision
                ),
                "reason": conflict.reason,
                "result_memory_id": (
                    conflict.result_memory_id
                    if hasattr(conflict, "result_memory_id")
                    else ""
                ),
                "resolved_at": conflict.resolved_at,
            }
            row = s.get(ConflictRow, conflict.conflict_id)
            if row is None:
                s.add(ConflictRow(
                    conflict_id=conflict.conflict_id,
                    created_at=conflict.created_at,
                    **values,
                ))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def list_all(self, status: str = "", user_id: str = "") -> list:
        """List conflicts, optionally filtering by decision/status."""
        from memoryhub.adapter.schemas import ConflictRecord

        with self.db.session() as session:
            query = session.query(ConflictRow)
            if status:
                query = query.filter(ConflictRow.decision == status)
            if user_id:
                query = query.filter(ConflictRow.user_id == user_id)
            rows = query.order_by(ConflictRow.created_at.desc()).all()
            return [
                ConflictRecord(
                    conflict_id=row.conflict_id,
                    user_id=row.user_id or "default",
                    old_memory_id=row.old_memory_id,
                    new_memory_id=row.new_memory_id,
                    memory_type=row.memory_type,
                    old_content=row.old_content,
                    new_content=row.new_content,
                    decision=row.decision,
                    reason=row.reason or "",
                    result_memory_id=row.result_memory_id or "",
                    created_at=row.created_at or datetime.now(),
                    resolved_at=row.resolved_at,
                )
                for row in rows
            ]

    def get_pending(self) -> list:
        """Return unresolved conflicts."""
        return self.list_all("pending")

    def delete_for_memories(self, memory_ids: list[str]) -> int:
        """Delete conflicts linked to already owner-validated memory IDs."""
        ids = {item for item in memory_ids if item}
        if not ids:
            return 0
        with self.db.session() as session:
            rows = session.query(ConflictRow).filter(
                (ConflictRow.old_memory_id.in_(ids))
                | (ConflictRow.new_memory_id.in_(ids))
                | (ConflictRow.result_memory_id.in_(ids))
            ).all()
            count = len(rows)
            for row in rows:
                session.delete(row)
            return count

    def resolve(
        self,
        conflict_id: str,
        decision: str,
        reason: str,
        result_id: str = "",
        user_id: str = "",
    ) -> bool:
        """Persist a conflict decision and report whether the record existed."""
        with self.db.session() as session:
            count = (
                session.query(ConflictRow)
                .filter(
                    ConflictRow.conflict_id == conflict_id,
                    *([ConflictRow.user_id == user_id] if user_id else []),
                )
                .update(
                    {
                        "decision": decision,
                        "reason": reason,
                        "result_memory_id": result_id,
                        "resolved_at": datetime.now(),
                    }
                )
            )
            return count == 1


# ============================================================
# 遗忘记录 CRUD
# ============================================================


class ForgetRepository:
    """遗忘记录仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, record: ForgetRecord) -> None:
        """保存遗忘记录"""
        with self.db.session() as s:
            row = ForgetRow(
                record_id=record.record_id,
                user_id=record.user_id,
                instruction=record.instruction,
                target_memory_ids=record.target_memory_ids,
                deleted_count=record.deleted_count,
                created_at=record.created_at,
            )
            s.add(row)

    def get_history(self, user_id: str) -> list[ForgetRecord]:
        """获取遗忘历史"""
        with self.db.session() as s:
            rows = (
                s.query(ForgetRow)
                .filter(ForgetRow.user_id == user_id)
                .order_by(ForgetRow.created_at.desc())
                .all()
            )
            return [
                ForgetRecord(
                    record_id=r.record_id,
                    user_id=r.user_id,
                    instruction=r.instruction or "",
                    target_memory_ids=r.target_memory_ids or [],
                    deleted_count=r.deleted_count or 0,
                    created_at=r.created_at,
                )
                for r in rows
            ]

    def get_by_id(self, record_id: str) -> ForgetRecord | None:
        """按 record_id 查询单条遗忘记录（供遗忘历史详情页）。"""
        with self.db.session() as s:
            row = s.query(ForgetRow).filter(ForgetRow.record_id == record_id).first()
            if row is None:
                return None
            return ForgetRecord(
                record_id=row.record_id,
                user_id=row.user_id or "",
                instruction=row.instruction or "",
                target_memory_ids=row.target_memory_ids or [],
                deleted_count=row.deleted_count or 0,
                created_at=row.created_at,
            )

    def delete_memories(self, memory_ids: list[str], table: str) -> int:
        """
        从指定表物理删除记忆记录。

        参数:
            memory_ids: 记忆 ID 列表
            table: "preferences" | "knowledge"

        返回:
            成功删除数量
        """
        row_cls = {"preferences": PreferenceRow, "knowledge": KnowledgeRow}.get(table)
        if row_cls is None:
            raise ValueError(f"不支持的表: {table}")

        pk_col = "memory_id"
        with self.db.session() as s:
            count = (
                s.query(row_cls)
                .filter(getattr(row_cls, pk_col).in_(memory_ids))
                .delete(synchronize_session=False)
            )
            return count


# ============================================================
# 持久化抽取任务
# ============================================================


_SAFE_EXTRACTION_ERROR_CODE = re.compile(r"^extraction\.[a-z0-9_.-]{1,100}$")


def _safe_extraction_error_code(value: str) -> str:
    if not value:
        return ""
    return value if _SAFE_EXTRACTION_ERROR_CODE.fullmatch(value) else "extraction.internal_error"


def _utcnow_naive() -> datetime:
    """Return UTC suitable for SQLite DATETIME comparisons."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _extraction_task_row_to_pydantic(row: ExtractionTaskRow) -> ExtractionTask:
    return ExtractionTask(
        task_id=row.task_id,
        event_id=row.event_id,
        event_ids=row.event_ids or [row.event_id],
        tenant_id=row.tenant_id or "",
        user_id=row.user_id,
        extractor_type=row.extractor_type,
        status=row.status,
        attempt_count=row.attempt_count or 0,
        max_attempts=row.max_attempts or 3,
        next_retry_at=row.next_retry_at,
        lease_expires_at=row.lease_expires_at,
        last_error_code=row.last_error_code or "",
        candidate_ids=list(row.candidate_ids or []),
        candidate_statuses=dict(row.candidate_statuses or {}),
        memory_ids=list(row.memory_ids or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ExtractionTaskRepository:
    """Durable retry/dead-letter state referencing gate-approved events only."""

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _identity(event_ids: list[str], extractor_type: str) -> tuple[str, str]:
        normalized_ids = sorted({event_id for event_id in event_ids if event_id})
        if not normalized_ids:
            raise ValueError("event_ids must not be empty")
        kind = extractor_type.value if hasattr(extractor_type, "value") else str(extractor_type)
        if kind not in {item.value for item in ExtractionType}:
            raise ValueError("unsupported extractor type")
        task_key = hashlib.sha256(
            (kind + "|" + "|".join(normalized_ids)).encode("utf-8")
        ).hexdigest()
        return task_key, f"xt_{task_key[:29]}"

    def enqueue(
        self,
        *,
        event_ids: list[str],
        tenant_id: str = "",
        user_id: str,
        extractor_type: str,
        max_attempts: int = 3,
        error_code: str = "",
        now: datetime | None = None,
    ) -> tuple[ExtractionTask, bool]:
        """Idempotently enqueue one extractor/event-set pair."""
        task_key, task_id = self._identity(event_ids, extractor_type)
        ordered_ids = list(dict.fromkeys(event_ids))
        current = now or _utcnow_naive()
        with self.db.session() as session:
            existing = (
                session.query(ExtractionTaskRow)
                .filter(ExtractionTaskRow.task_key == task_key)
                .first()
            )
            if existing is not None:
                return _extraction_task_row_to_pydantic(existing), False
            row = ExtractionTaskRow(
                task_id=task_id,
                task_key=task_key,
                event_id=ordered_ids[0],
                event_ids=ordered_ids,
                tenant_id=tenant_id,
                user_id=user_id,
                extractor_type=(
                    extractor_type.value
                    if hasattr(extractor_type, "value")
                    else str(extractor_type)
                ),
                status=ExtractionTaskStatus.PENDING.value,
                attempt_count=0,
                max_attempts=max(1, int(max_attempts)),
                next_retry_at=current,
                lease_expires_at=None,
                last_error_code=_safe_extraction_error_code(error_code),
                created_at=current,
                updated_at=current,
            )
            session.add(row)
            session.flush()
            return _extraction_task_row_to_pydantic(row), True

    def get(self, task_id: str, *, user_id: str | None = None) -> ExtractionTask | None:
        with self.db.session() as session:
            query = session.query(ExtractionTaskRow).filter(
                ExtractionTaskRow.task_id == task_id
            )
            if user_id is not None:
                query = query.filter(ExtractionTaskRow.user_id == user_id)
            row = query.first()
            return _extraction_task_row_to_pydantic(row) if row is not None else None

    def list(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[ExtractionTask]:
        with self.db.session() as session:
            query = session.query(ExtractionTaskRow).filter(
                ExtractionTaskRow.user_id == user_id
            )
            if status:
                query = query.filter(ExtractionTaskRow.status == status)
            rows = (
                query.order_by(ExtractionTaskRow.created_at.desc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [_extraction_task_row_to_pydantic(row) for row in rows]

    def claim_due(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
        lease_seconds: int = 300,
    ) -> list[ExtractionTask]:
        """Claim due work; expired running leases are recoverable after process loss."""
        current = now or _utcnow_naive()
        with self.db.session() as session:
            due = or_(
                ExtractionTaskRow.status.in_([
                    ExtractionTaskStatus.PENDING.value,
                    ExtractionTaskStatus.RETRY.value,
                ]) & or_(
                    ExtractionTaskRow.next_retry_at.is_(None),
                    ExtractionTaskRow.next_retry_at <= current,
                ),
                (ExtractionTaskRow.status == ExtractionTaskStatus.RUNNING.value)
                & (ExtractionTaskRow.lease_expires_at <= current),
            )
            query = session.query(ExtractionTaskRow).filter(due)
            if user_id is not None:
                query = query.filter(ExtractionTaskRow.user_id == user_id)
            rows = (
                query.order_by(ExtractionTaskRow.created_at.asc())
                .limit(max(1, min(int(limit), 200)))
                .all()
            )
            claimed_ids: list[str] = []
            lease_expires_at = current + timedelta(seconds=max(1, lease_seconds))
            for row in rows:
                # Conditional UPDATE makes the claim atomic across concurrent workers.
                claimed_count = (
                    session.query(ExtractionTaskRow)
                    .filter(ExtractionTaskRow.task_id == row.task_id, due)
                    .update(
                        {
                            ExtractionTaskRow.status: ExtractionTaskStatus.RUNNING.value,
                            ExtractionTaskRow.attempt_count: (row.attempt_count or 0) + 1,
                            ExtractionTaskRow.lease_expires_at: lease_expires_at,
                            ExtractionTaskRow.updated_at: current,
                        },
                        synchronize_session=False,
                    )
                )
                if claimed_count == 1:
                    claimed_ids.append(row.task_id)
            session.flush()
            session.expire_all()
            return [
                _extraction_task_row_to_pydantic(session.get(ExtractionTaskRow, task_id))
                for task_id in claimed_ids
            ]

    def mark_succeeded(self, task_id: str, *, now: datetime | None = None) -> ExtractionTask:
        return self._finish(
            task_id,
            status=ExtractionTaskStatus.SUCCEEDED.value,
            error_code="",
            next_retry_at=None,
            now=now,
        )

    def record_formation_result(
        self,
        task_id: str,
        *,
        candidate_ids: list[str] | None = None,
        candidate_statuses: dict[str, str] | None = None,
        memory_ids: list[str] | None = None,
    ) -> ExtractionTask:
        """Idempotently publish the durable Formation result on the task."""

        with self.db.session() as session:
            row = session.get(ExtractionTaskRow, task_id)
            if row is None:
                raise KeyError("extraction task not found")
            row.candidate_ids = sorted(set(row.candidate_ids or []) | set(candidate_ids or []))
            row.memory_ids = sorted(set(row.memory_ids or []) | set(memory_ids or []))
            statuses = dict(row.candidate_statuses or {})
            statuses.update({str(k): str(v) for k, v in (candidate_statuses or {}).items()})
            row.candidate_statuses = statuses
            session.flush()
            return _extraction_task_row_to_pydantic(row)

    def mark_failed(
        self,
        task_id: str,
        *,
        error_code: str,
        now: datetime | None = None,
        base_delay_seconds: int = 60,
    ) -> ExtractionTask:
        current = now or _utcnow_naive()
        with self.db.session() as session:
            row = session.get(ExtractionTaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            if (row.attempt_count or 0) >= (row.max_attempts or 3):
                row.status = ExtractionTaskStatus.DEAD_LETTER.value
                row.next_retry_at = None
            else:
                row.status = ExtractionTaskStatus.RETRY.value
                delay = max(1, base_delay_seconds) * (2 ** max(0, row.attempt_count - 1))
                row.next_retry_at = current + timedelta(seconds=delay)
            row.last_error_code = _safe_extraction_error_code(error_code)
            row.lease_expires_at = None
            row.updated_at = current
            session.flush()
            return _extraction_task_row_to_pydantic(row)

    def mark_dead(
        self, task_id: str, *, error_code: str, now: datetime | None = None
    ) -> ExtractionTask:
        return self._finish(
            task_id,
            status=ExtractionTaskStatus.DEAD_LETTER.value,
            error_code=error_code,
            next_retry_at=None,
            now=now,
        )

    def retry_dead(
        self, task_id: str, *, user_id: str, now: datetime | None = None
    ) -> ExtractionTask | None:
        current = now or _utcnow_naive()
        with self.db.session() as session:
            row = (
                session.query(ExtractionTaskRow)
                .filter(
                    ExtractionTaskRow.task_id == task_id,
                    ExtractionTaskRow.user_id == user_id,
                    ExtractionTaskRow.status == ExtractionTaskStatus.DEAD_LETTER.value,
                )
                .first()
            )
            if row is None:
                return None
            row.status = ExtractionTaskStatus.RETRY.value
            row.attempt_count = 0
            row.next_retry_at = current
            row.lease_expires_at = None
            row.last_error_code = ""
            row.updated_at = current
            session.flush()
            return _extraction_task_row_to_pydantic(row)

    def _finish(
        self,
        task_id: str,
        *,
        status: str,
        error_code: str,
        next_retry_at: datetime | None,
        now: datetime | None,
    ) -> ExtractionTask:
        current = now or _utcnow_naive()
        with self.db.session() as session:
            row = session.get(ExtractionTaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            row.status = status
            row.last_error_code = _safe_extraction_error_code(error_code)
            row.next_retry_at = next_retry_at
            row.lease_expires_at = None
            row.updated_at = current
            session.flush()
            return _extraction_task_row_to_pydantic(row)


# ============================================================
# 记忆分层仓储（短期工作记忆 / 中期情景，REFACTOR_PLAN_V2 §4.4）
# ============================================================


class ShortTermMemoryRepository:
    """短期记忆（工作记忆）仓储：会话内事件缓冲，TTL 到期清理。"""

    def __init__(self, db: Database):
        self.db = db

    def add(self, *, user_id: str, session_id: str, event_id: str,
            source_type: str = "", text: str = "", payload: dict | None = None,
            scene: str = "", task_type: str = "", ttl_until=None) -> str:
        row_id = (
            f"stm_{hashlib.sha256(f'{user_id}:{session_id}:{event_id}'.encode()).hexdigest()[:24]}"
        )
        with self.db.session() as s:
            if s.get(ShortTermMemoryRow, row_id) is None:
                s.add(
                    ShortTermMemoryRow(
                        id=row_id, user_id=user_id, session_id=session_id,
                        event_id=event_id, source_type=source_type, text=text,
                        payload=payload or {}, scene=scene, task_type=task_type,
                        created_at=datetime.now(), ttl_until=ttl_until,
                    )
                )
        return row_id

    def list_by_session(self, user_id: str, session_id: str) -> list[dict]:
        with self.db.session() as s:
            rows = (
                s.query(ShortTermMemoryRow)
                .filter(
                    ShortTermMemoryRow.user_id == user_id,
                    ShortTermMemoryRow.session_id == session_id,
                )
                .order_by(ShortTermMemoryRow.created_at.asc())
                .all()
            )
            return [self._to_dict(r) for r in rows]

    def list_all(self, user_id: str = "") -> list[dict]:
        with self.db.session() as s:
            q = s.query(ShortTermMemoryRow)
            if user_id:
                q = q.filter(ShortTermMemoryRow.user_id == user_id)
            rows = q.order_by(ShortTermMemoryRow.created_at.asc()).all()
            return [self._to_dict(r) for r in rows]

    def delete_for_session(self, user_id: str, session_id: str, task_type: str = "") -> int:
        with self.db.session() as s:
            q = s.query(ShortTermMemoryRow).filter(
                ShortTermMemoryRow.user_id == user_id,
                ShortTermMemoryRow.session_id == session_id,
            )
            if task_type:
                q = q.filter(ShortTermMemoryRow.task_type == task_type)
            count = q.delete(synchronize_session=False)
        return count

    def delete_expired(self, now=None) -> int:
        now = now or datetime.now()
        with self.db.session() as s:
            count = (
                s.query(ShortTermMemoryRow)
                .filter(ShortTermMemoryRow.ttl_until.isnot(None),
                        ShortTermMemoryRow.ttl_until < now)
                .delete(synchronize_session=False)
            )
        return count

    @staticmethod
    def _to_dict(row: ShortTermMemoryRow) -> dict:
        return {
            "id": row.id, "user_id": row.user_id, "session_id": row.session_id,
            "event_id": row.event_id, "source_type": row.source_type, "text": row.text,
            "payload": row.payload, "scene": row.scene, "task_type": row.task_type,
            "created_at": row.created_at,
        }


class MidTermMemoryRepository:
    """中期记忆（情景）仓储。"""

    def __init__(self, db: Database):
        self.db = db

    def add(self, *, episode_id: str, user_id: str, session_ids: list[str],
            scene: str = "", task_type: str = "", event_ids: list[str] | None = None,
            trajectory_summary: str = "", tools: list[str] | None = None,
            outcome: str = "success", occurred_at=None, decay_score: float = 1.0,
            status: str = "active") -> str:
        with self.db.session() as s:
            if s.get(MidTermMemoryRow, episode_id) is None:
                s.add(
                    MidTermMemoryRow(
                        episode_id=episode_id, user_id=user_id, session_ids=session_ids,
                        scene=scene, task_type=task_type, event_ids=event_ids or [],
                        trajectory_summary=trajectory_summary, tools=tools or [],
                        outcome=outcome, occurred_at=occurred_at,
                        last_accessed_at=None, decay_score=decay_score,
                        status=status, created_at=datetime.now(),
                    )
                )
        return episode_id

    def get_by_id(self, episode_id: str) -> dict | None:
        with self.db.session() as s:
            row = s.get(MidTermMemoryRow, episode_id)
            return self._to_dict(row) if row is not None else None

    def list_active(self, user_id: str = "") -> list[dict]:
        with self.db.session() as s:
            q = s.query(MidTermMemoryRow).filter(MidTermMemoryRow.status == "active")
            if user_id:
                q = q.filter(MidTermMemoryRow.user_id == user_id)
            rows = q.order_by(MidTermMemoryRow.occurred_at.asc()).all()
            return [self._to_dict(r) for r in rows]

    def list_all(self, user_id: str = "", status: str = "") -> list[dict]:
        with self.db.session() as s:
            q = s.query(MidTermMemoryRow)
            if user_id:
                q = q.filter(MidTermMemoryRow.user_id == user_id)
            if status:
                q = q.filter(MidTermMemoryRow.status == status)
            rows = q.order_by(MidTermMemoryRow.occurred_at.desc()).all()
            return [self._to_dict(r) for r in rows]

    def mark_consolidated(self, episode_id: str, status: str = "consolidated") -> bool:
        with self.db.session() as s:
            row = s.get(MidTermMemoryRow, episode_id)
            if row is None:
                return False
            row.status = status
            return True

    def delete(self, episode_id: str) -> bool:
        with self.db.session() as s:
            row = s.get(MidTermMemoryRow, episode_id)
            if row is None:
                return False
            s.delete(row)
            return True

    @staticmethod
    def _to_dict(row: MidTermMemoryRow) -> dict:
        return {
            "episode_id": row.episode_id, "user_id": row.user_id,
            "session_ids": row.session_ids or [], "scene": row.scene,
            "task_type": row.task_type, "event_ids": row.event_ids or [],
            "trajectory_summary": row.trajectory_summary, "tools": row.tools or [],
            "outcome": row.outcome, "occurred_at": row.occurred_at,
            "last_accessed_at": row.last_accessed_at, "decay_score": row.decay_score,
            "status": row.status, "created_at": row.created_at,
        }
