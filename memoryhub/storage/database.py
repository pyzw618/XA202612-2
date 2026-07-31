"""
数据库引擎与会话管理

基于 SQLAlchemy ORM，提供 SQLite 持久化和 Repository CRUD。
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from memoryhub.adapter.schemas import (
    Evidence,
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
    ForgetRow,
    KnowledgeRow,
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
        self.session_factory = sessionmaker(bind=self.engine)

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
        content=row.content,
        scope=SceneScope(
            scene=row.scope_scene or "",
            task_type=row.scope_task_type or "",
            app=row.scope_app or "",
        ),
        confidence=row.confidence or 0.0,
        status=MemoryStatus(row.status) if row.status else MemoryStatus.ACTIVE,
        level=row.level or "long",
        version=row.version or 1,
        parent_id=row.parent_id or "",
        evidences=row.evidences or [],
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
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ============================================================
# 事件 CRUD
# ============================================================


class EventRepository:
    """事件数据仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, event: MemoryEvent) -> None:
        """保存事件"""
        with self.db.session() as s:
            row = EventRow(
                event_id=event.event_id,
                source_type=event.source_type.value if hasattr(event.source_type, "value") else str(event.source_type),
                event_type=event.event_type,
                user_id=event.user_id,
                session_id=event.session_id,
                scene=event.scene,
                task_type=event.task_type,
                occurred_at=event.occurred_at,
                text=event.text,
                payload=event.payload,
                source_hash=event.source_hash,
                quality=event.quality.model_dump() if event.quality else {},
            )
            s.add(row)

    def batch_save(self, events: list[MemoryEvent]) -> int:
        """批量保存事件，返回成功数量"""
        with self.db.session() as s:
            for event in events:
                row = EventRow(
                    event_id=event.event_id,
                    source_type=event.source_type.value if hasattr(event.source_type, "value") else str(event.source_type),
                    event_type=event.event_type,
                    user_id=event.user_id,
                    session_id=event.session_id,
                    scene=event.scene,
                    task_type=event.task_type,
                    occurred_at=event.occurred_at,
                    text=event.text,
                    payload=event.payload,
                    source_hash=event.source_hash,
                    quality=event.quality.model_dump() if event.quality else {},
                )
                s.add(row)
            return len(events)

    def get_by_id(self, event_id: str) -> Optional[MemoryEvent]:
        """按 ID 查询事件"""
        with self.db.session() as s:
            row = s.query(EventRow).filter(EventRow.event_id == event_id).first()
            if row is None:
                return None
            return MemoryEvent(
                event_id=row.event_id,
                event_type=row.event_type,
                user_id=row.user_id,
                session_id=row.session_id,
                scene=row.scene or "",
                task_type=row.task_type or "",
                content=row.payload or {},
                source=row.source_type or "",
                occurred_at=row.occurred_at,
            )

    def get_by_session(self, session_id: str) -> list[MemoryEvent]:
        """按会话 ID 查询事件列表"""
        with self.db.session() as s:
            rows = s.query(EventRow).filter(EventRow.session_id == session_id).all()
            return [_event_row_to_pydantic(r) for r in rows]

    def get_by_task_type(self, user_id: str, task_type: str) -> list[MemoryEvent]:
        """按用户和任务类型查询事件列表"""
        with self.db.session() as s:
            rows = (
                s.query(EventRow)
                .filter(EventRow.user_id == user_id, EventRow.task_type == task_type)
                .all()
            )
            return [_event_row_to_pydantic(r) for r in rows]

    def get_recent(self, user_id: str, limit: int = 100) -> list[MemoryEvent]:
        """获取最近的事件"""
        with self.db.session() as s:
            rows = (
                s.query(EventRow)
                .filter(EventRow.user_id == user_id)
                .order_by(EventRow.occurred_at.desc())
                .limit(limit)
                .all()
            )
            return [_event_row_to_pydantic(r) for r in rows]


def _event_row_to_pydantic(row: EventRow) -> MemoryEvent:
    from memoryhub.adapter.schemas import EventQuality, QualityStatus, SourceType
    quality_data = row.quality or {}
    if isinstance(quality_data, dict):
        quality = EventQuality(
            score=quality_data.get("score", 0.0),
            status=quality_data.get("status", QualityStatus.REJECTED),
            completeness=quality_data.get("completeness", 0.0),
            validity=quality_data.get("validity", 0.0),
            consistency=quality_data.get("consistency", 0.0),
        )
    else:
        quality = quality_data
    return MemoryEvent(
        event_id=row.event_id,
        source_type=SourceType(row.source_type) if row.source_type else SourceType.TOOL_RESULT,
        event_type=row.event_type or "",
        user_id=row.user_id or "",
        session_id=row.session_id or "",
        scene=row.scene or "",
        task_type=row.task_type or "",
        occurred_at=str(row.occurred_at) if row.occurred_at else "",
        text=row.text or "",
        payload=row.payload or {},
        source_hash=row.source_hash or "0" * 64,
        quality=quality,
    )


# ============================================================
# 偏好 CRUD
# ============================================================


class PreferenceRepository:
    """偏好记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, memory: PreferenceMemory) -> None:
        """保存偏好"""
        with self.db.session() as s:
            row = PreferenceRow(
                memory_id=memory.memory_id,
                user_id=memory.user_id,
                preference_type=memory.preference_type.value if hasattr(memory.preference_type, "value") else str(memory.preference_type),
                content=memory.content,
                scope_scene=memory.scope.scene,
                scope_task_type=memory.scope.task_type,
                scope_app=memory.scope.app,
                confidence=memory.confidence,
                status=memory.status.value if hasattr(memory.status, "value") else str(memory.status),
                level=memory.level.value if hasattr(memory.level, "value") else memory.level,
                version=memory.version,
                parent_id=memory.parent_id or None,
                evidences=[e.model_dump() for e in memory.evidences] if memory.evidences else [],
            )
            s.merge(row)

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

    def list_all(self, status: str = "active") -> list[PreferenceMemory]:
        """列出指定状态的全部偏好记忆（应用启动时全量加载用）"""
        with self.db.session() as s:
            rows = (
                s.query(PreferenceRow)
                .filter(PreferenceRow.status == status)
                .order_by(PreferenceRow.confidence.desc())
                .all()
            )
            return [_pref_row_to_pydantic(r) for r in rows]

    def update_status(self, memory_id: str, status: str) -> None:
        """更新状态"""
        from datetime import datetime

        with self.db.session() as s:
            s.query(PreferenceRow).filter(
                PreferenceRow.memory_id == memory_id
            ).update({"status": status, "updated_at": datetime.now()})

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
        """保存知识"""
        with self.db.session() as s:
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
                evidences=[e.model_dump() for e in memory.evidences] if memory.evidences else [],
            )
            s.merge(row)

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
        """按 scope 查询"""
        with self.db.session() as s:
            rows = (
                s.query(KnowledgeRow)
                .filter(
                    KnowledgeRow.user_id == user_id,
                    KnowledgeRow.scope_scene == scene,
                    KnowledgeRow.scope_task_type == task_type,
                    KnowledgeRow.status == "active",
                )
                .order_by(KnowledgeRow.confidence.desc())
                .all()
            )
            return [_know_row_to_pydantic(r) for r in rows]

    def list_all(self, status: str = "active") -> list[KnowledgeMemory]:
        """列出指定状态的全部知识记忆（应用启动时全量加载用）"""
        with self.db.session() as s:
            rows = (
                s.query(KnowledgeRow)
                .filter(KnowledgeRow.status == status)
                .order_by(KnowledgeRow.confidence.desc())
                .all()
            )
            return [_know_row_to_pydantic(r) for r in rows]

    def search_by_name(self, keyword: str) -> list[KnowledgeMemory]:
        """按名称模糊搜索"""
        with self.db.session() as s:
            rows = (
                s.query(KnowledgeRow)
                .filter(KnowledgeRow.name.contains(keyword))
                .order_by(KnowledgeRow.confidence.desc())
                .all()
            )
            return [_know_row_to_pydantic(r) for r in rows]

    def increment_usage(self, memory_id: str, success: bool) -> None:
        """增加使用计数"""
        from datetime import datetime

        with self.db.session() as s:
            updates = {"total_count": KnowledgeRow.total_count + 1, "updated_at": datetime.now()}
            if success:
                updates["success_count"] = KnowledgeRow.success_count + 1
            s.query(KnowledgeRow).filter(KnowledgeRow.memory_id == memory_id).update(updates)


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
            row = ConflictRow(
                conflict_id=conflict.conflict_id,
                old_memory_id=conflict.old_memory_id,
                new_memory_id=conflict.new_memory_id,
                memory_type=conflict.memory_type,
                old_content=conflict.old_content,
                new_content=conflict.new_content,
                decision=conflict.decision.value if hasattr(conflict.decision, "value") else conflict.decision,
                reason=conflict.reason,
                result_memory_id=conflict.result_memory_id if hasattr(conflict, "result_memory_id") else "",
            )
            s.add(row)

    def get_pending(self) -> list:
        """获取待解决的冲突"""
        from memoryhub.adapter.schemas import ConflictRecord
        from datetime import datetime

        with self.db.session() as s:
            rows = s.query(ConflictRow).filter(ConflictRow.decision == "pending").all()
            return [
                ConflictRecord(
                    conflict_id=r.conflict_id,
                    old_memory_id=r.old_memory_id,
                    new_memory_id=r.new_memory_id,
                    memory_type=r.memory_type,
                    old_content=r.old_content,
                    new_content=r.new_content,
                    decision=r.decision,
                    reason=r.reason or "",
                    created_at=r.created_at or datetime.now(),
                )
                for r in rows
            ]

    def resolve(self, conflict_id: str, decision: str, reason: str, result_id: str) -> None:
        """记录冲突解决结果"""
        from datetime import datetime

        with self.db.session() as s:
            s.query(ConflictRow).filter(ConflictRow.conflict_id == conflict_id).update({
                "decision": decision,
                "reason": reason,
                "result_memory_id": result_id,
                "resolved_at": datetime.now(),
            })


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
