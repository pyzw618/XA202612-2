"""SQLite storage for facts, entities, and predicates."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .models import Entity, Fact, MemoryScope, PredicateDef

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    aliases        TEXT DEFAULT '[]',
    user_id        TEXT NOT NULL DEFAULT 'default',
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS predicates (
    predicate_id   TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    aliases        TEXT DEFAULT '[]',
    domain_types   TEXT DEFAULT '[]',
    range_types    TEXT DEFAULT '[]',
    single_value   INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS facts (
    fact_id          TEXT PRIMARY KEY,
    subject_id       TEXT NOT NULL,
    predicate_id     TEXT NOT NULL,
    object_id        TEXT NOT NULL,
    object_value     TEXT NOT NULL,
    source_text      TEXT DEFAULT '',
    source_id        TEXT DEFAULT '',
    observed_at      TEXT NOT NULL,
    confidence       REAL DEFAULT 0.0,
    status           TEXT DEFAULT 'active',
    version          INTEGER DEFAULT 1,
    memory_type      TEXT NOT NULL DEFAULT 'fact',
    scope            TEXT NOT NULL DEFAULT 'global',
    project_id       TEXT,
    user_id          TEXT NOT NULL DEFAULT 'default',
    last_accessed_at TEXT,
    access_count_30d INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (subject_id) REFERENCES entities(entity_id),
    FOREIGN KEY (predicate_id) REFERENCES predicates(predicate_id)
);
"""


class FactStore:
    """Persistent facts store with strict user ownership boundaries."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        entity_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(entities)")
        }
        if "user_id" not in entity_columns:
            self._conn.execute(
                "ALTER TABLE entities ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            )

        fact_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(facts)")
        }
        migrations = {
            "memory_type": "ALTER TABLE facts ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'fact'",
            "scope": "ALTER TABLE facts ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'",
            "project_id": "ALTER TABLE facts ADD COLUMN project_id TEXT",
            "user_id": "ALTER TABLE facts ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'",
            "last_accessed_at": "ALTER TABLE facts ADD COLUMN last_accessed_at TEXT",
            "access_count_30d": "ALTER TABLE facts ADD COLUMN access_count_30d INTEGER NOT NULL DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in fact_columns:
                self._conn.execute(sql)
        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_facts_owner_status ON facts(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_facts_scope_sp
                ON facts(user_id, scope, project_id, subject_id, predicate_id, status);
            CREATE INDEX IF NOT EXISTS idx_entities_owner_type ON entities(user_id, entity_type);
            CREATE INDEX IF NOT EXISTS idx_entities_owner_name ON entities(user_id, canonical_name);
            """
        )

    def close(self) -> None:
        self._conn.close()

    def upsert_entity(self, entity: Entity) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO entities
               (entity_id, canonical_name, entity_type, aliases, user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (
                entity.entity_id,
                entity.canonical_name,
                entity.entity_type,
                json.dumps(entity.aliases, ensure_ascii=False),
                entity.user_id,
            ),
        )
        self._conn.commit()
        return entity.entity_id

    def get_entity(self, entity_id: str, user_id: Optional[str] = None) -> Optional[Entity]:
        query = "SELECT * FROM entities WHERE entity_id = ?"
        params: list[object] = [entity_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        row = self._conn.execute(query, params).fetchone()
        return self._row_to_entity(row) if row is not None else None

    def find_entity_by_name(
        self, name: str, entity_type: Optional[str] = None, user_id: str = "default"
    ) -> list[Entity]:
        query = "SELECT * FROM entities WHERE user_id = ?"
        params: list[object] = [user_id]
        if entity_type is not None:
            query += " AND entity_type = ?"
            params.append(entity_type)
        rows = self._conn.execute(query, params).fetchall()
        needle = name.strip().lower()
        result = []
        for row in rows:
            aliases = json.loads(row["aliases"] or "[]")
            names = [row["canonical_name"], *aliases]
            if any(str(item).strip().lower() == needle for item in names):
                result.append(self._row_to_entity(row))
        return result

    def list_entities_by_type(
        self, entity_type: str, user_id: str = "default"
    ) -> list[Entity]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE entity_type = ? AND user_id = ?",
            (entity_type, user_id),
        ).fetchall()
        return [self._row_to_entity(row) for row in rows]

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Entity:
        return Entity(
            entity_id=row["entity_id"],
            canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
            aliases=json.loads(row["aliases"] or "[]"),
            user_id=row["user_id"],
        )

    def upsert_predicate(self, pred: PredicateDef) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO predicates
               (predicate_id, canonical_name, aliases, domain_types, range_types, single_value)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                pred.predicate_id,
                pred.canonical_name,
                json.dumps(pred.aliases, ensure_ascii=False),
                json.dumps(pred.domain, ensure_ascii=False),
                json.dumps(pred.range, ensure_ascii=False),
                int(pred.single_value),
            ),
        )
        self._conn.commit()
        return pred.predicate_id

    def get_predicate(self, predicate_id: str) -> Optional[PredicateDef]:
        row = self._conn.execute(
            "SELECT * FROM predicates WHERE predicate_id = ?", (predicate_id,)
        ).fetchone()
        return self._row_to_predicate(row) if row is not None else None

    def find_predicate_by_alias(self, alias_text: str) -> Optional[PredicateDef]:
        for row in self._conn.execute("SELECT * FROM predicates").fetchall():
            aliases = json.loads(row["aliases"] or "[]")
            if alias_text == row["canonical_name"] or alias_text in aliases:
                return self._row_to_predicate(row)
        return None

    def list_predicates(self) -> list[PredicateDef]:
        return [
            self._row_to_predicate(row)
            for row in self._conn.execute("SELECT * FROM predicates").fetchall()
        ]

    @staticmethod
    def _row_to_predicate(row: sqlite3.Row) -> PredicateDef:
        return PredicateDef(
            predicate_id=row["predicate_id"],
            canonical_name=row["canonical_name"],
            aliases=json.loads(row["aliases"] or "[]"),
            domain=json.loads(row["domain_types"] or "[]"),
            range=json.loads(row["range_types"] or "[]"),
            single_value=bool(row["single_value"]),
        )

    def insert_fact(self, fact: Fact) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO facts
               (fact_id, subject_id, predicate_id, object_id, object_value,
                source_text, source_id, observed_at, confidence, status, version,
                memory_type, scope, project_id, user_id, last_accessed_at,
                access_count_30d)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact.fact_id, fact.subject_id, fact.predicate_id, fact.object_id,
                fact.object_value, fact.source_text, fact.source_id,
                fact.observed_at, fact.confidence, fact.status, fact.version,
                fact.memory_type, fact.scope, fact.project_id, fact.user_id,
                fact.last_accessed_at, fact.access_count_30d,
            ),
        )
        self._conn.commit()
        return fact.fact_id

    def find_facts_by_sp(
        self,
        subject_id: str,
        predicate_id: str,
        status: str = "active",
        scope: str = MemoryScope.GLOBAL.value,
        project_id: Optional[str] = None,
        user_id: str = "default",
    ) -> list[Fact]:
        query = """SELECT * FROM facts
                   WHERE user_id = ? AND subject_id = ? AND predicate_id = ?
                     AND status = ? AND scope = ?"""
        params: list[object] = [user_id, subject_id, predicate_id, status, scope]
        if scope == MemoryScope.PROJECT.value:
            if not project_id:
                raise ValueError("project facts require project_id")
            query += " AND project_id = ?"
            params.append(project_id)
        else:
            query += " AND project_id IS NULL"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def update_fact_status(
        self, fact_id: str, new_status: str, user_id: Optional[str] = None
    ) -> bool:
        query = "UPDATE facts SET status = ? WHERE fact_id = ?"
        params: list[object] = [new_status, fact_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        cursor = self._conn.execute(query, params)
        self._conn.commit()
        return cursor.rowcount > 0

    def get_fact(self, fact_id: str, user_id: Optional[str] = None) -> Optional[Fact]:
        query = "SELECT * FROM facts WHERE fact_id = ?"
        params: list[object] = [fact_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        row = self._conn.execute(query, params).fetchone()
        return self._row_to_fact(row) if row is not None else None

    def list_facts(
        self,
        status: Optional[str] = "active",
        limit: int = 100,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[Fact]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if scope == MemoryScope.GLOBAL.value:
            clauses.extend(("scope = ?", "project_id IS NULL"))
            params.append(scope)
        elif scope == MemoryScope.PROJECT.value:
            if not project_id:
                raise ValueError("project facts require project_id")
            clauses.extend(("scope = ?", "project_id = ?"))
            params.extend((scope, project_id))
        elif project_id is not None:
            raise ValueError("project_id requires scope='project'")
        query = "SELECT * FROM facts"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        return [
            self._row_to_fact(row)
            for row in self._conn.execute(query, params).fetchall()
        ]

    def record_access(self, fact_id: str, user_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._conn.execute(
            """UPDATE facts
               SET last_accessed_at = ?, access_count_30d = access_count_30d + 1
               WHERE fact_id = ? AND user_id = ? AND status = 'active'""",
            (now, fact_id, user_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def prune_orphan_entities(self, user_id: str) -> int:
        """Remove owner-scoped entities no longer referenced by non-deleted facts."""
        cursor = self._conn.execute(
            """DELETE FROM entities
               WHERE user_id = ?
                 AND entity_id NOT IN (
                     SELECT subject_id FROM facts
                     WHERE user_id = ? AND status != 'deleted'
                     UNION
                     SELECT object_id FROM facts
                     WHERE user_id = ? AND status != 'deleted'
                 )""",
            (user_id, user_id, user_id),
        )
        self._conn.commit()
        return cursor.rowcount

    def render_fact(self, fact: Fact) -> str:
        subject = self.get_entity(fact.subject_id, user_id=fact.user_id)
        predicate = self.get_predicate(fact.predicate_id)
        subject_name = subject.canonical_name if subject else fact.subject_id
        predicate_name = predicate.canonical_name if predicate else fact.predicate_id
        return " ".join(
            part for part in (
                subject_name, predicate_name, fact.object_value, fact.source_text
            ) if part
        )

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> Fact:
        return Fact(
            fact_id=row["fact_id"],
            subject_id=row["subject_id"],
            predicate_id=row["predicate_id"],
            object_id=row["object_id"],
            object_value=row["object_value"],
            source_text=row["source_text"],
            source_id=row["source_id"],
            observed_at=row["observed_at"],
            confidence=row["confidence"],
            status=row["status"],
            version=row["version"],
            memory_type=row["memory_type"],
            scope=row["scope"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            last_accessed_at=row["last_accessed_at"],
            access_count_30d=row["access_count_30d"],
        )
