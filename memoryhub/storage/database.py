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
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func, inspect, or_
from sqlalchemy.orm import Session, sessionmaker

from memoryhub.adapter.schemas import (
    Evidence,
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
from memoryhub.storage.models import (
    Base,
    ConflictRow,
    EventRow,
    ExtractionTaskRow,
    ForgetRow,
    KnowledgeRow,
    KnowledgeVersionRow,
    PreferenceRow,
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
                "turn_id": "VARCHAR(64)",
                "tool_calls": "JSON",
                "schema_version": "VARCHAR(16) DEFAULT '1.1'",
                "source_hash": "VARCHAR(64)",
                "redactions": "JSON",
                "quality": "JSON",
            },
            "preferences": {
                "payload": "JSON",
                "is_global": "BOOLEAN DEFAULT 0",
                "quality_score": "FLOAT DEFAULT 1.0",
                "extract_source": "VARCHAR(32) DEFAULT 'implicit_inference'",
                "root_id": "VARCHAR(32)",
                "tags": "JSON",
                "extra_payload": "JSON",
                "pending_index": "BOOLEAN DEFAULT 1",
                "index_version": "INTEGER DEFAULT 0",
                "health_score": "FLOAT DEFAULT 1.0",
                "stability": "FLOAT DEFAULT 1.0",
                "last_accessed_at": "DATETIME",
                "access_count_30d": "INTEGER DEFAULT 0",
            },
            "knowledge": {
                "pending_index": "BOOLEAN DEFAULT 1",
                "index_version": "INTEGER DEFAULT 0",
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
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_pending_index "
                        f"ON {table} (pending_index)"
                    )
                    conn.exec_driver_sql(
                        f"CREATE INDEX IF NOT EXISTS ix_{table}_index_version "
                        f"ON {table} (index_version)"
                    )

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
        return EventRow(
            event_id=event.event_id,
            source_type=event.source_type.value,
            event_type=event.event_type,
            user_id=event.user_id,
            session_id=event.session_id,
            turn_id=event.turn_id,
            scene=event.scene,
            task_type=event.task_type,
            occurred_at=cls._parse_occurred_at(event.occurred_at),
            text=event.text,
            payload=event.payload,
            tool_calls=[call.model_dump(mode="json") for call in event.tool_calls],
            schema_version=event.schema_version,
            source_hash=event.source_hash,
            redactions=event.redactions,
            quality=event.quality.model_dump(mode="json"),
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

    def get_recent(self, user_id: str, limit: int = 100) -> list[MemoryEvent]:
        with self.db.session() as session:
            rows = (
                session.query(EventRow).filter(EventRow.user_id == user_id)
                .order_by(EventRow.occurred_at.desc()).limit(limit).all()
            )
            return [_event_row_to_pydantic(row) for row in rows]


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

    def save(self, memory: PreferenceMemory) -> None:
        """保存偏好；新写入或更新后标记为待同步到向量索引。"""
        with self.db.session() as s:
            row = PreferenceRow(
                memory_id=memory.memory_id,
                user_id=memory.user_id,
                preference_type=memory.preference_type.value if hasattr(memory.preference_type, "value") else str(memory.preference_type),
                content=memory.text,
                payload=memory.payload,
                scope_scene=memory.scope.scene,
                scope_task_type=memory.scope.task_type,
                scope_app=memory.scope.app,
                is_global=memory.is_global,
                confidence=memory.confidence,
                quality_score=memory.quality_score,
                extract_source=memory.extract_source,
                status=memory.status.value if hasattr(memory.status, "value") else str(memory.status),
                level=memory.level.value if hasattr(memory.level, "value") else memory.level,
                version=memory.version,
                parent_id=memory.parent_id or None,
                root_id=memory.root_id or None,
                evidences=[e.model_dump(mode="json") for e in memory.evidences] if memory.evidences else [],
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
            s.merge(row)

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
        """查询活跃偏好，支持场景过滤"""
        with self.db.session() as s:
            q = s.query(PreferenceRow).filter(
                PreferenceRow.user_id == user_id,
                PreferenceRow.status == "active",
            )
            if scene:
                q = q.filter(PreferenceRow.scope_scene == scene)
            rows = q.order_by(PreferenceRow.confidence.desc()).all()
            return [_pref_row_to_pydantic(r) for r in rows]

    def get_by_scope(self, user_id: str, scene: str, task_type: str) -> list[PreferenceMemory]:
        """按 scope 精确查询"""
        with self.db.session() as s:
            rows = (
                s.query(PreferenceRow)
                .filter(
                    PreferenceRow.user_id == user_id,
                    PreferenceRow.scope_scene == scene,
                    PreferenceRow.scope_task_type == task_type,
                    PreferenceRow.status == "active",
                )
                .order_by(PreferenceRow.confidence.desc())
                .all()
            )
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
        from datetime import datetime, timedelta, timezone

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
        """获取版本链"""
        with self.db.session() as s:
            row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
            if row is None:
                return []

            # 追溯到最老版本
            root = row
            while root.parent_id:
                parent = s.query(PreferenceRow).filter(PreferenceRow.memory_id == root.parent_id).first()
                if parent is None:
                    break
                root = parent

            # 从最老版本向下遍历
            chain = [root]
            current = root
            while True:
                child = (
                    s.query(PreferenceRow)
                    .filter(PreferenceRow.parent_id == current.memory_id)
                    .first()
                )
                if child is None:
                    break
                chain.append(child)
                current = child

            return [_pref_row_to_pydantic(r) for r in chain]


# ============================================================
# 知识 CRUD
# ============================================================


class KnowledgeRepository:
    """知识记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, memory: KnowledgeMemory) -> None:
        """保存知识；新写入或更新后标记为待同步到向量索引。"""
        with self.db.session() as s:
            existing = s.get(KnowledgeRow, memory.memory_id)
            if existing is not None and memory.version > (existing.version or 1):
                snapshot_id = f"{memory.memory_id}:v{existing.version or 1}"
                if s.get(KnowledgeVersionRow, snapshot_id) is None:
                    snapshot = _know_row_to_pydantic(existing)
                    s.add(
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
                user_id=memory.user_id,
                knowledge_type=memory.knowledge_type.value if hasattr(memory.knowledge_type, "value") else str(memory.knowledge_type),
                name=memory.name,
                content=memory.content,
                steps=memory.steps,
                tools=memory.tools,
                template_body=memory.template_body or None,
                scope_scene=memory.scope.scene,
                scope_task_type=memory.scope.task_type,
                scope_app=memory.scope.app,
                confidence=memory.confidence,
                success_count=memory.success_count,
                total_count=memory.total_count,
                status=memory.status.value if hasattr(memory.status, "value") else str(memory.status),
                level=memory.level.value if hasattr(memory.level, "value") else memory.level,
                version=memory.version,
                parent_id=memory.parent_id or None,
                evidences=[e.model_dump(mode="json") for e in memory.evidences] if memory.evidences else [],
                health_score=memory.health_score,
                stability=memory.stability,
                last_accessed_at=memory.last_accessed_at,
                access_count_30d=memory.access_count_30d,
                created_at=memory.created_at,
                updated_at=memory.updated_at,
                pending_index=True,
            )
            s.merge(row)

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

    def get_by_type(self, user_id: str, knowledge_type: str = "") -> list[KnowledgeMemory]:
        """按类型查询"""
        with self.db.session() as s:
            q = s.query(KnowledgeRow).filter(
                KnowledgeRow.user_id == user_id,
                KnowledgeRow.status == "active",
            )
            if knowledge_type:
                q = q.filter(KnowledgeRow.knowledge_type == knowledge_type)
            rows = q.order_by(KnowledgeRow.confidence.desc()).all()
            return [_know_row_to_pydantic(r) for r in rows]

    def get_by_scope(self, user_id: str, scene: str, task_type: str) -> list[KnowledgeMemory]:
        """? scope ????????????????"""
        with self.db.session() as s:
            query = s.query(KnowledgeRow).filter(
                KnowledgeRow.user_id == user_id,
                KnowledgeRow.status == "active",
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
        """???????????? owner?"""
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
        """??????????? owner?"""
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
                "decision": conflict.decision.value if hasattr(conflict.decision, "value") else conflict.decision,
                "reason": conflict.reason,
                "result_memory_id": conflict.result_memory_id if hasattr(conflict, "result_memory_id") else "",
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
        user_id=row.user_id,
        extractor_type=row.extractor_type,
        status=row.status,
        attempt_count=row.attempt_count or 0,
        max_attempts=row.max_attempts or 3,
        next_retry_at=row.next_retry_at,
        lease_expires_at=row.lease_expires_at,
        last_error_code=row.last_error_code or "",
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
