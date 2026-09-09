"""用户自定义遗忘规则（REFACTOR_PLAN_V2 §4.5.2 / I-13）。

允许用户声明"删除所有涉及 X 的记忆"类规则：每条规则绑定一个主题（topic）与若干
关键词（keywords）。遗忘请求进入时，若指令命中某条规则的 topic，则该规则的
keywords 会被并入意图关键词，从而让"删除所有涉及 X 的记忆"这类语义规则真正生效，
且与安全敏感规则同管道（在遗忘执行前展开关键词，不改变遗忘写路径）。

本服务独立于 sensitive-info 的用户规则（后者加密存储、只服务安全门禁）；遗忘规则
内容为普通主题/关键词，不需要密文隔离。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from memoryhub.storage.sqlite_lock import sqlite_database_lock


class ForgetRuleError(RuntimeError):
    """稳定的遗忘规则错误码（不含任何用户内容）。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ForgetRuleService:
    """SQLite 持久化的用户遗忘规则：按用户存取主题与关键词。"""

    def __init__(self, database_path: str | Path | None = None):
        self._own_connection = database_path is not None
        self._path = None if database_path is None else Path(database_path)
        self._connection = None
        self._lock = (
            threading.RLock()
            if database_path is None
            else sqlite_database_lock(database_path)
        )
        if database_path is not None:
            self._open(database_path)

    def _open(self, database_path: str | Path) -> None:
        try:
            path_text = str(database_path)
            if path_text != ":memory:":
                parent = Path(path_text).expanduser().absolute().parent
                parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                path_text,
                timeout=30.0,
                check_same_thread=False,
                # This service keeps one connection for its lifetime.  In the
                # default sqlite3 transaction mode a create/delete call would
                # otherwise leave a write transaction open indefinitely and
                # lock every SQLAlchemy repository sharing the same database.
                isolation_level=None,
            )
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._initialize_schema()
        except (OSError, TypeError, ValueError, sqlite3.Error):
            raise ForgetRuleError("forget_rule.storage_error") from None

    def bind(self, connection) -> None:
        """允许复用既有 Database 的连接（默认情况下用于独立文件/内存库）。"""
        if self._connection is not None and self._own_connection:
            return
        self._connection = connection
        self._own_connection = False
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_forget_rules (
                    rule_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_forget_rules_user "
                "ON user_forget_rules (user_id, enabled)"
            )
        except sqlite3.Error:
            raise ForgetRuleError("forget_rule.storage_error") from None

    def _ensure(self):
        if self._connection is None:
            raise ForgetRuleError("forget_rule.storage_unavailable")

    def create(
        self, *, user_id: str, topic: str, keywords: list[str], enabled: bool = True
    ) -> dict[str, Any]:
        self._ensure()
        topic = (topic or "").strip()
        keywords = [k.strip() for k in (keywords or []) if str(k).strip()]
        if not topic or not keywords:
            raise ForgetRuleError("forget_rule.invalid_rule")
        rule_id = f"frule_{uuid.uuid4().hex[:24]}"
        now = _utc_text()
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO user_forget_rules
                        (rule_id, user_id, topic, keywords, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rule_id, user_id, topic, json.dumps(keywords, ensure_ascii=False),
                     int(enabled), now, now),
                )
            except sqlite3.Error:
                raise ForgetRuleError("forget_rule.storage_error") from None
        return self._row_to_dict(rule_id, user_id, topic, keywords, enabled, now, now)

    def list(self, user_id: str, *, include_disabled: bool = True) -> list[dict[str, Any]]:
        self._ensure()
        with self._lock:
            try:
                rows = self._connection.execute(
                    "SELECT rule_id, user_id, topic, keywords, enabled, created_at, updated_at "
                    "FROM user_forget_rules WHERE user_id = ?"
                    + ("" if include_disabled else " AND enabled = 1"),
                    (user_id,),
                ).fetchall()
            except sqlite3.Error:
                raise ForgetRuleError("forget_rule.storage_error") from None
        return [self._parse_row(r) for r in rows]

    def delete(self, user_id: str, rule_id: str) -> bool:
        self._ensure()
        with self._lock:
            try:
                cur = self._connection.execute(
                    "DELETE FROM user_forget_rules WHERE user_id = ? AND rule_id = ?",
                    (user_id, rule_id),
                )
            except sqlite3.Error:
                raise ForgetRuleError("forget_rule.storage_error") from None
        return cur.rowcount > 0

    def active_keywords(self, user_id: str) -> dict[str, list[str]]:
        """返回该用户全部启用规则的 topic→keywords 映射（供遗忘执行前展开）。"""
        rules = self.list(user_id, include_disabled=False)
        return {rule["topic"]: rule["keywords"] for rule in rules}

    def close(self) -> None:
        """Release the owned SQLite connection without affecting bound callers."""
        with self._lock:
            if self._connection is not None and self._own_connection:
                self._connection.close()
            self._connection = None

    @staticmethod
    def _row_to_dict(rule_id, user_id, topic, keywords, enabled, created_at, updated_at) -> dict:
        return {
            "rule_id": rule_id, "user_id": user_id, "topic": topic,
            "keywords": list(keywords) if isinstance(keywords, list) else
                        [k for k in (keywords or []) if k],
            "enabled": bool(enabled), "created_at": created_at, "updated_at": updated_at,
        }

    @staticmethod
    def _parse_row(row) -> dict[str, Any]:
        try:
            keywords = json.loads(row[3] or "[]")
        except (ValueError, TypeError):
            keywords = []
        return ForgetRuleService._row_to_dict(
            row[0], row[1], row[2], keywords, bool(row[4]), row[5], row[6]
        )


def _utc_text() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
