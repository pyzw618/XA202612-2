"""
数据库管理器 — 统一管理 SQLite 连接。

用法:
    db = DatabaseManager(":memory:")            # 测试
    db = DatabaseManager("data/memories.db")    # 持久化
    db = DatabaseManager()                       # 默认路径
"""

import os
import sqlite3
import threading

# 默认数据库路径
_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class DatabaseManager:
    """
    SQLite 连接管理器，负责建表和提供连接。

    线程安全：每个线程从连接池取连接。
    """

    def __init__(self, db_path: str = ""):
        if not db_path:
            os.makedirs(_DEFAULT_DIR, exist_ok=True)
            db_path = os.path.join(_DEFAULT_DIR, "memories.db")

        self.db_path = db_path
        self._local = threading.local()

        # 立即建表
        conn = self._get_conn()
        self._create_all_tables(conn)

    # ---- 公开 API ----

    def get_conn(self) -> sqlite3.Connection:
        """获取当前线程的数据库连接。"""
        return self._get_conn()

    def execute(self, sql: str, params: tuple = ()):
        """执行一条 SQL，返回 cursor。"""
        conn = self._get_conn()
        return conn.execute(sql, params)

    def commit(self):
        """提交当前线程的事务。"""
        self._get_conn().commit()

    def close(self):
        """关闭当前线程的数据库连接。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ---- 内部 ----

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _create_all_tables(self, conn: sqlite3.Connection):
        from .schema import ALL_TABLES
        for name, ddl in ALL_TABLES:
            conn.executescript(ddl)
        conn.commit()
