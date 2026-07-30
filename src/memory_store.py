"""
Memory Store — SQLite 持久化存储层。

管理记忆条目的增删查，数据自动写入 SQLite 落盘，
程序重启后自动恢复，是 BM25 + FAISS 共用的数据源。
"""

import json
import os
import sqlite3
import uuid
import time
import threading
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# 默认数据库路径
DEFAULT_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@dataclass
class MemoryRecord:
    """单条记忆记录。"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    content: str = ""
    embedding: Optional[List[float]] = None
    created_at: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class MemoryStore:
    """
    SQLite 持久化的记忆存储。

    用法:
        store = MemoryStore()                          # 默认路径 data/memories.db
        store = MemoryStore(":memory:")                # 内存模式（测试用）
        store.add("文本", embedding=[0.1, 0.2, ...])
        records = store.get_all()                      # 自动从 SQLite 加载
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: SQLite 数据库路径。
                     ":memory:" → 纯内存（测试用）
                     None → 默认 data/memories.db
        """
        if db_path is None:
            os.makedirs(DEFAULT_DB_DIR, exist_ok=True)
            db_path = os.path.join(DEFAULT_DB_DIR, "memories.db")

        self._db_path = db_path
        self._records: List[MemoryRecord] = []
        self._lock = threading.Lock()

        # 初始化数据库
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 写性能更好
        self._create_table()
        self._load_from_db()

    # ---- 公开 API ----

    def add(
        self,
        content: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[dict] = None,
    ) -> MemoryRecord:
        """添加一条记忆，即时写入 SQLite。"""
        record = MemoryRecord(
            content=content,
            embedding=embedding,
            metadata=metadata or {},
        )
        with self._lock:
            self._records.append(record)
            self._insert_row(record)
        return record

    def add_batch(self, items: List[dict]) -> List[MemoryRecord]:
        """批量添加，使用事务提升写入性能。"""
        records = []
        for item in items:
            record = MemoryRecord(
                content=item["content"],
                embedding=item.get("embedding"),
                metadata=item.get("metadata", {}),
            )
            records.append(record)

        with self._lock:
            self._records.extend(records)
            with self._conn:
                for r in records:
                    self._insert_row(r)
        return records

    def get_by_id(self, record_id: str) -> Optional[MemoryRecord]:
        """按 ID 查找。"""
        with self._lock:
            for r in self._records:
                if r.id == record_id:
                    return r
        return None

    def get_all(self) -> List[MemoryRecord]:
        """返回全部记录的快照。"""
        with self._lock:
            return list(self._records)

    def delete(self, record_id: str) -> bool:
        """按 ID 删除（内存 + SQLite 同步删除）。"""
        with self._lock:
            for i, r in enumerate(self._records):
                if r.id == record_id:
                    self._records.pop(i)
                    self._conn.execute(
                        "DELETE FROM memories WHERE id = ?", (record_id,)
                    )
                    self._conn.commit()
                    return True
        return False

    def close(self):
        """关闭数据库连接。"""
        self._conn.close()

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return f"<MemoryStore records={len(self._records)} db={self._db_path}>"

    # ---- 内部：SQLite 操作 ----

    def _create_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id          TEXT PRIMARY KEY,
                content     TEXT NOT NULL,
                embedding   BLOB,
                created_at  REAL NOT NULL,
                metadata    TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self._conn.commit()

    def _insert_row(self, record: MemoryRecord):
        """插入单行并立即提交。"""
        emb_blob = None
        if record.embedding is not None:
            emb_blob = np.array(record.embedding, dtype=np.float32).tobytes()

        self._conn.execute(
            """INSERT OR REPLACE INTO memories (id, content, embedding, created_at, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (
                record.id,
                record.content,
                emb_blob,
                record.created_at,
                json.dumps(record.metadata, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def _load_from_db(self):
        """从 SQLite 加载全部记录到内存。"""
        rows = self._conn.execute(
            "SELECT id, content, embedding, created_at, metadata FROM memories ORDER BY created_at"
        ).fetchall()

        self._records = []
        for row in rows:
            emb = None
            if row[2] is not None:
                emb = np.frombuffer(row[2], dtype=np.float32).tolist()

            record = MemoryRecord(
                id=row[0],
                content=row[1],
                embedding=emb,
                created_at=row[3],
                metadata=json.loads(row[4]) if row[4] else {},
            )
            self._records.append(record)
