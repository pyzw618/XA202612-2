"""
Repository 层 — 每张表一个 Repository，封装全部 CRUD 操作。

用法:
    db = DatabaseManager()
    event_repo = EventRepository(db)
    event_repo.insert(event_row)
    rows = event_repo.find_by_user("user_001")
"""

import json
from typing import Optional, List
from .database import DatabaseManager
from .models import EventRow, PreferenceRow, KnowledgeRow, ConflictRow, ForgetRow


# ============================================================
# 基类
# ============================================================
class BaseRepository:
    """Repository 基类：提供通用 CRUD 操作。"""

    def __init__(self, db: DatabaseManager, table_name: str, model_class, pk_column: str):
        self.db = db
        self.table = table_name
        self.model = model_class
        self.pk = pk_column

    # -- 增 --

    def insert(self, row) -> None:
        """插入一行。"""
        d = row.to_dict()
        columns = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT OR REPLACE INTO {self.table} ({columns}) VALUES ({placeholders})"
        self.db.execute(sql, tuple(d.values()))
        self.db.commit()

    def insert_batch(self, rows: List) -> None:
        """批量插入（事务内）。"""
        conn = self.db.get_conn()
        for row in rows:
            d = row.to_dict()
            columns = ", ".join(d.keys())
            placeholders = ", ".join("?" for _ in d)
            sql = f"INSERT OR REPLACE INTO {self.table} ({columns}) VALUES ({placeholders})"
            conn.execute(sql, tuple(d.values()))
        conn.commit()

    # -- 删 --

    def delete_by_id(self, pk_value: str) -> bool:
        """按主键删除。返回是否成功。"""
        sql = f"DELETE FROM {self.table} WHERE {self.pk} = ?"
        cur = self.db.execute(sql, (pk_value,))
        self.db.commit()
        return cur.rowcount > 0

    # -- 查 --

    def get_by_id(self, pk_value: str) -> Optional[object]:
        """按主键查询单条。"""
        sql = f"SELECT * FROM {self.table} WHERE {self.pk} = ?"
        cur = self.db.execute(sql, (pk_value,))
        row = cur.fetchone()
        return self.model.from_row(tuple(row)) if row else None

    def get_all(self, limit: int = 1000, offset: int = 0) -> List:
        """全量查询（带分页）。"""
        sql = f"SELECT * FROM {self.table} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        cur = self.db.execute(sql, (limit, offset))
        return [self.model.from_row(tuple(r)) for r in cur.fetchall()]

    def count(self) -> int:
        """总行数。"""
        cur = self.db.execute(f"SELECT COUNT(*) FROM {self.table}")
        return cur.fetchone()[0]

    def _fetch_all(self, sql: str, params: tuple = ()) -> List:
        cur = self.db.execute(sql, params)
        return [self.model.from_row(tuple(r)) for r in cur.fetchall()]

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[object]:
        cur = self.db.execute(sql, params)
        row = cur.fetchone()
        return self.model.from_row(tuple(row)) if row else None


# ============================================================
# 表 1: EventRepository
# ============================================================
class EventRepository(BaseRepository):
    """events 表操作。"""

    def __init__(self, db: DatabaseManager):
        super().__init__(db, "events", EventRow, "id")

    def find_by_user(self, user_id: str, limit: int = 100) -> List[EventRow]:
        return self._fetch_all(
            "SELECT * FROM events WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        )

    def find_by_session(self, session_id: str) -> List[EventRow]:
        return self._fetch_all(
            "SELECT * FROM events WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )

    def find_by_task(self, task_id: str) -> List[EventRow]:
        return self._fetch_all(
            "SELECT * FROM events WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )

    def find_by_type(self, event_type: str, limit: int = 100) -> List[EventRow]:
        return self._fetch_all(
            "SELECT * FROM events WHERE event_type = ? ORDER BY created_at DESC LIMIT ?",
            (event_type, limit),
        )

    def find_by_scene(self, scene: str, task_type: str = "", limit: int = 100) -> List[EventRow]:
        if task_type:
            return self._fetch_all(
                "SELECT * FROM events WHERE scene = ? AND task_type = ? ORDER BY created_at DESC LIMIT ?",
                (scene, task_type, limit),
            )
        return self._fetch_all(
            "SELECT * FROM events WHERE scene = ? ORDER BY created_at DESC LIMIT ?",
            (scene, limit),
        )


# ============================================================
# 表 2: PreferenceRepository
# ============================================================
class PreferenceRepository(BaseRepository):
    """preferences 表操作。"""

    def __init__(self, db: DatabaseManager):
        super().__init__(db, "preferences", PreferenceRow, "memory_id")

    def find_by_user(self, user_id: str) -> List[PreferenceRow]:
        return self._fetch_all(
            "SELECT * FROM preferences WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )

    def find_active(self, user_id: str = "") -> List[PreferenceRow]:
        """查询所有 active 状态的偏好。"""
        if user_id:
            return self._fetch_all(
                "SELECT * FROM preferences WHERE status = 'active' AND user_id = ? ORDER BY confidence DESC",
                (user_id,),
            )
        return self._fetch_all(
            "SELECT * FROM preferences WHERE status = 'active' ORDER BY confidence DESC"
        )

    def find_by_type(self, pref_type: str, user_id: str = "") -> List[PreferenceRow]:
        if user_id:
            return self._fetch_all(
                "SELECT * FROM preferences WHERE preference_type = ? AND user_id = ?",
                (pref_type, user_id),
            )
        return self._fetch_all(
            "SELECT * FROM preferences WHERE preference_type = ?",
            (pref_type,),
        )

    def find_by_scope(self, scene: str, task_type: str = "") -> List[PreferenceRow]:
        if task_type:
            return self._fetch_all(
                "SELECT * FROM preferences WHERE scope_scene = ? AND scope_task_type = ? AND status = 'active'",
                (scene, task_type),
            )
        return self._fetch_all(
            "SELECT * FROM preferences WHERE scope_scene = ? AND status = 'active'",
            (scene,),
        )

    def find_by_level(self, level: str) -> List[PreferenceRow]:
        return self._fetch_all(
            "SELECT * FROM preferences WHERE level = ? AND status = 'active'",
            (level,),
        )

    def archive(self, memory_id: str) -> bool:
        """将偏好归档（软删除）。"""
        import time
        self.db.execute(
            "UPDATE preferences SET status = 'archived', updated_at = ? WHERE memory_id = ?",
            (time.time(), memory_id),
        )
        self.db.commit()
        return True


# ============================================================
# 表 3: KnowledgeRepository
# ============================================================
class KnowledgeRepository(BaseRepository):
    """knowledge 表操作。"""

    def __init__(self, db: DatabaseManager):
        super().__init__(db, "knowledge", KnowledgeRow, "memory_id")

    def find_by_user(self, user_id: str) -> List[KnowledgeRow]:
        return self._fetch_all(
            "SELECT * FROM knowledge WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )

    def find_active(self, user_id: str = "") -> List[KnowledgeRow]:
        if user_id:
            return self._fetch_all(
                "SELECT * FROM knowledge WHERE status = 'active' AND user_id = ? ORDER BY confidence DESC",
                (user_id,),
            )
        return self._fetch_all(
            "SELECT * FROM knowledge WHERE status = 'active' ORDER BY confidence DESC"
        )

    def find_by_type(self, knowledge_type: str) -> List[KnowledgeRow]:
        return self._fetch_all(
            "SELECT * FROM knowledge WHERE knowledge_type = ? AND status = 'active'",
            (knowledge_type,),
        )

    def find_by_scope(self, scene: str, task_type: str = "") -> List[KnowledgeRow]:
        if task_type:
            return self._fetch_all(
                "SELECT * FROM knowledge WHERE scope_scene = ? AND scope_task_type = ? AND status = 'active'",
                (scene, task_type),
            )
        return self._fetch_all(
            "SELECT * FROM knowledge WHERE scope_scene = ? AND status = 'active'",
            (scene,),
        )

    def increment_success(self, memory_id: str) -> None:
        """成功复用次数 +1。"""
        import time
        self.db.execute(
            "UPDATE knowledge SET success_count = success_count + 1, total_count = total_count + 1, updated_at = ? WHERE memory_id = ?",
            (time.time(), memory_id),
        )
        self.db.commit()

    def increment_total(self, memory_id: str) -> None:
        """调用次数 +1（未成功）。"""
        import time
        self.db.execute(
            "UPDATE knowledge SET total_count = total_count + 1, updated_at = ? WHERE memory_id = ?",
            (time.time(), memory_id),
        )
        self.db.commit()


# ============================================================
# 表 4: ConflictRepository
# ============================================================
class ConflictRepository(BaseRepository):
    """conflicts 表操作。"""

    def __init__(self, db: DatabaseManager):
        super().__init__(db, "conflicts", ConflictRow, "conflict_id")

    def find_by_user(self, user_id: str) -> List[ConflictRow]:
        return self._fetch_all(
            "SELECT * FROM conflicts WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )

    def find_pending(self) -> List[ConflictRow]:
        """查询所有等待人工裁决的冲突。"""
        return self._fetch_all(
            "SELECT * FROM conflicts WHERE decision = 'pending' ORDER BY created_at DESC"
        )

    def find_by_memory(self, memory_id: str) -> List[ConflictRow]:
        """查询涉及某条记忆的所有冲突。"""
        return self._fetch_all(
            "SELECT * FROM conflicts WHERE old_memory_id = ? OR new_memory_id = ? ORDER BY created_at DESC",
            (memory_id, memory_id),
        )

    def resolve(self, conflict_id: str, decision: str, resolved_by: str = "auto") -> bool:
        """裁决冲突。"""
        self.db.execute(
            "UPDATE conflicts SET decision = ?, resolved_by = ? WHERE conflict_id = ?",
            (decision, resolved_by, conflict_id),
        )
        self.db.commit()
        return True


# ============================================================
# 表 5: ForgetRepository
# ============================================================
class ForgetRepository(BaseRepository):
    """forget_history 表操作。"""

    def __init__(self, db: DatabaseManager):
        super().__init__(db, "forget_history", ForgetRow, "forget_id")

    def find_by_user(self, user_id: str) -> List[ForgetRow]:
        return self._fetch_all(
            "SELECT * FROM forget_history WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )

    def get_audit_log(self, limit: int = 50) -> List[ForgetRow]:
        """获取最近的遗忘审计日志。"""
        return self._fetch_all(
            "SELECT * FROM forget_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
