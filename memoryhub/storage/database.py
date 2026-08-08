"""
数据库引擎与会话管理

提供 SQLAlchemy 引擎、会话工厂和 CRUD 操作接口。
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from memoryhub.storage.models import (
    Base,
    ConflictRow,
    EventRow,
    ForgetRow,
    KnowledgeRow,
    PreferenceRow,
)


class Database:
    """
    SQLite 数据库管理器

    使用方式:
        db = Database("data/memoryhub.db")
        db.init_schema()
        with db.session() as s:
            s.add(row)
            s.commit()
    """

    def __init__(self, db_path: str = "data/memoryhub.db"):
        """
        参数:
            db_path: SQLite 数据库文件路径
        """
        self.db_path = db_path
        self.engine = None
        self.session_factory = None

    def init_schema(self) -> None:
        """
        初始化数据库 schema

        数据流: 应用启动 → init_schema → 创建所有表
        """
        if self.engine is not None:
            return

        if self.db_path == ":memory:":
            self.engine = create_engine(
                "sqlite+pysqlite:///:memory:",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            path = Path(self.db_path).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                f"sqlite+pysqlite:///{path.as_posix()}",
                connect_args={"check_same_thread": False},
            )

        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        """
        获取数据库会话

        返回:
            SQLAlchemy Session 实例

        使用方式:
            with db.session() as s:
                result = s.query(PreferenceRow).all()
        """
        if self.session_factory is None:
            raise RuntimeError("database schema has not been initialized")
        return self.session_factory()

    def close(self) -> None:
        """关闭数据库连接"""
        if self.engine is not None:
            self.engine.dispose()
        self.engine = None
        self.session_factory = None


# ============================================================
# 事件 CRUD
# ============================================================

class EventRepository:
    """事件数据仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, event_row) -> None:
        """保存事件"""
        with self.db.session() as session:
            session.add(event_row)
            session.commit()

    def batch_save(self, rows: list) -> int:
        """批量保存事件，返回成功数量"""
        if not rows:
            return 0
        with self.db.session() as session:
            session.add_all(rows)
            session.commit()
        return len(rows)

    def get_by_id(self, event_id: str):
        """按 ID 查询事件"""
        with self.db.session() as session:
            return session.get(EventRow, event_id)

    def get_by_session(self, session_id: str) -> list:
        """按会话 ID 查询事件列表。"""
        with self.db.session() as session:
            return list(
                session.query(EventRow)
                .filter(EventRow.session_id == session_id)
                .order_by(EventRow.occurred_at.asc())
                .all()
            )

    def get_by_task_type(self, user_id: str, task_type: str) -> list:
        """按用户和规范化任务类型查询事件列表。"""
        with self.db.session() as session:
            return list(
                session.query(EventRow)
                .filter(EventRow.user_id == user_id, EventRow.task_type == task_type)
                .order_by(EventRow.occurred_at.desc())
                .all()
            )

    def get_recent(self, user_id: str, limit: int = 100) -> list:
        """获取最近的事件"""
        with self.db.session() as session:
            return list(
                session.query(EventRow)
                .filter(EventRow.user_id == user_id)
                .order_by(EventRow.occurred_at.desc())
                .limit(limit)
                .all()
            )


# ============================================================
# 偏好 CRUD
# ============================================================

class PreferenceRepository:
    """偏好记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, row) -> None:
        """保存偏好"""
        with self.db.session() as session:
            session.merge(row)
            session.commit()

    def get_by_id(self, memory_id: str):
        """按 ID 查询"""
        with self.db.session() as session:
            return session.get(PreferenceRow, memory_id)

    def get_active(self, user_id: str, scene: str = "") -> list:
        """查询活跃偏好，支持场景过滤"""
        with self.db.session() as session:
            query = session.query(PreferenceRow).filter(
                PreferenceRow.user_id == user_id,
                PreferenceRow.status == "active",
            )
            if scene:
                query = query.filter(
                    (PreferenceRow.scope_scene == scene) | (PreferenceRow.scope_scene == "")
                )
            return list(query.order_by(PreferenceRow.updated_at.desc()).all())

    def get_by_scope(self, user_id: str, scene: str, task_type: str) -> list:
        """按 scope 精确查询"""
        with self.db.session() as session:
            return list(
                session.query(PreferenceRow)
                .filter(
                    PreferenceRow.user_id == user_id,
                    PreferenceRow.status == "active",
                    (PreferenceRow.scope_scene == scene) | (PreferenceRow.scope_scene == ""),
                    (PreferenceRow.scope_task_type == task_type)
                    | (PreferenceRow.scope_task_type == ""),
                )
                .order_by(PreferenceRow.updated_at.desc())
                .all()
            )

    def update_status(self, memory_id: str, status: str) -> None:
        """更新状态"""
        with self.db.session() as session:
            row = session.get(PreferenceRow, memory_id)
            if row is not None:
                row.status = status
                session.commit()

    def get_version_chain(self, memory_id: str) -> list:
        """获取版本链"""
        with self.db.session() as session:
            current = session.get(PreferenceRow, memory_id)
            if current is None:
                return []
            rows = [current]
            while current.parent_id:
                current = session.get(PreferenceRow, current.parent_id)
                if current is None:
                    break
                rows.append(current)
            return sorted(rows, key=lambda row: row.version)


# ============================================================
# 知识 CRUD
# ============================================================

class KnowledgeRepository:
    """知识记忆仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, row) -> None:
        """保存知识"""
        with self.db.session() as session:
            session.merge(row)
            session.commit()

    def get_by_id(self, memory_id: str):
        """按 ID 查询"""
        with self.db.session() as session:
            return session.get(KnowledgeRow, memory_id)

    def get_by_type(self, user_id: str, knowledge_type: str = "") -> list:
        """按类型查询"""
        with self.db.session() as session:
            query = session.query(KnowledgeRow).filter(
                KnowledgeRow.user_id == user_id,
                KnowledgeRow.status == "active",
            )
            if knowledge_type:
                query = query.filter(KnowledgeRow.knowledge_type == knowledge_type)
            return list(query.order_by(KnowledgeRow.updated_at.desc()).all())

    def get_by_scope(self, user_id: str, scene: str, task_type: str) -> list:
        """按 scope 查询"""
        with self.db.session() as session:
            return list(
                session.query(KnowledgeRow)
                .filter(
                    KnowledgeRow.user_id == user_id,
                    KnowledgeRow.status == "active",
                    (KnowledgeRow.scope_scene == scene) | (KnowledgeRow.scope_scene == ""),
                    (KnowledgeRow.scope_task_type == task_type)
                    | (KnowledgeRow.scope_task_type == ""),
                )
                .order_by(KnowledgeRow.updated_at.desc())
                .all()
            )

    def search_by_name(self, keyword: str) -> list:
        """按名称模糊搜索"""
        with self.db.session() as session:
            return list(
                session.query(KnowledgeRow)
                .filter(KnowledgeRow.name.contains(keyword), KnowledgeRow.status == "active")
                .order_by(KnowledgeRow.updated_at.desc())
                .all()
            )

    def increment_usage(self, memory_id: str, success: bool) -> None:
        """增加使用计数"""
        with self.db.session() as session:
            row = session.get(KnowledgeRow, memory_id)
            if row is not None:
                row.total_count += 1
                if success:
                    row.success_count += 1
                session.commit()


# ============================================================
# 冲突 CRUD
# ============================================================

class ConflictRepository:
    """冲突记录仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, row) -> None:
        """保存冲突记录"""
        with self.db.session() as session:
            session.merge(row)
            session.commit()

    def get_pending(self) -> list:
        """获取待解决的冲突"""
        with self.db.session() as session:
            return list(
                session.query(ConflictRow)
                .filter(ConflictRow.decision == "pending")
                .order_by(ConflictRow.created_at.desc())
                .all()
            )

    def resolve(self, conflict_id: str, decision: str, reason: str, result_id: str) -> None:
        """记录冲突解决结果"""
        with self.db.session() as session:
            row = session.get(ConflictRow, conflict_id)
            if row is not None:
                from datetime import datetime

                row.decision = decision
                row.reason = reason
                row.result_memory_id = result_id
                row.resolved_at = datetime.now()
                session.commit()


# ============================================================
# 遗忘记录 CRUD
# ============================================================

class ForgetRepository:
    """遗忘记录仓储"""

    def __init__(self, db: Database):
        self.db = db

    def save(self, row) -> None:
        """保存遗忘记录"""
        with self.db.session() as session:
            session.merge(row)
            session.commit()

    def get_history(self, user_id: str) -> list:
        """获取遗忘历史"""
        with self.db.session() as session:
            return list(
                session.query(ForgetRow)
                .filter(ForgetRow.user_id == user_id)
                .order_by(ForgetRow.created_at.desc())
                .all()
            )

    def delete_memories(self, memory_ids: list[str], table: str) -> int:
        """
        从指定表删除记忆记录

        参数:
            memory_ids: 记忆 ID 列表
            table: 表名 ("preferences" | "knowledge")

        返回:
            成功删除数量
        """
        model = {
            "preferences": PreferenceRow,
            "knowledge": KnowledgeRow,
        }.get(table)
        if model is None:
            raise ValueError("table must be 'preferences' or 'knowledge'")
        if not memory_ids:
            return 0
        with self.db.session() as session:
            count = session.query(model).filter(model.memory_id.in_(memory_ids)).delete(
                synchronize_session=False
            )
            session.commit()
            return count
