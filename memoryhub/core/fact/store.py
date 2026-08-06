"""
SQLite 存储层 — 实体表 / 谓词表 / 事实表
"""

import sqlite3
import json
import logging
from typing import Optional

from .models import Entity, MemoryScope, PredicateDef, Fact

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    aliases        TEXT DEFAULT '[]',
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
    fact_id        TEXT PRIMARY KEY,
    subject_id     TEXT NOT NULL,
    predicate_id   TEXT NOT NULL,
    object_id      TEXT NOT NULL,
    object_value   TEXT NOT NULL,
    source_text    TEXT DEFAULT '',
    source_id      TEXT DEFAULT '',
    observed_at    TEXT NOT NULL,
    confidence     REAL DEFAULT 0.0,
    status         TEXT DEFAULT 'active',
    version        INTEGER DEFAULT 1,
    memory_type    TEXT NOT NULL DEFAULT 'fact',
    scope          TEXT NOT NULL DEFAULT 'global',
    project_id     TEXT,
    FOREIGN KEY (subject_id) REFERENCES entities(entity_id),
    FOREIGN KEY (predicate_id) REFERENCES predicates(predicate_id)
);

CREATE INDEX IF NOT EXISTS idx_facts_sp ON facts(subject_id, predicate_id);
CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);

CREATE TABLE IF NOT EXISTS fact_proposals (
    proposal_id      TEXT PRIMARY KEY,
    raw_triple       TEXT NOT NULL,
    admission        TEXT NOT NULL,
    source_id        TEXT DEFAULT '',
    project_id_hint  TEXT,
    scope_hint       TEXT,
    metadata         TEXT DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'proposed',
    result           TEXT DEFAULT '{}',
    rejection_reason TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fact_proposals_status
ON fact_proposals(status, updated_at);
"""


class FactStore:
    """事实记忆的 SQLite 持久化存储"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self):
        """为旧版数据库补充事实作用域字段。"""
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(facts)").fetchall()
        }
        migrations = {
            "memory_type": "ALTER TABLE facts ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'fact'",
            "scope": "ALTER TABLE facts ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'",
            "project_id": "ALTER TABLE facts ADD COLUMN project_id TEXT",
        }
        for column, sql in migrations.items():
            if column not in columns:
                self._conn.execute(sql)
        self._conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_facts_scope_sp
               ON facts(scope, project_id, subject_id, predicate_id, status)"""
        )

    def close(self):
        self._conn.close()

    # ─── 实体 CRUD ───────────────────────────────────────────────────

    def upsert_entity(self, entity: Entity) -> str:
        """写入或更新实体，返回 entity_id"""
        aliases_json = json.dumps(entity.aliases, ensure_ascii=False)
        self._conn.execute(
            """INSERT OR REPLACE INTO entities
               (entity_id, canonical_name, entity_type, aliases)
               VALUES (?, ?, ?, ?)""",
            (entity.entity_id, entity.canonical_name, entity.entity_type, aliases_json),
        )
        self._conn.commit()
        return entity.entity_id

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if row is None:
            return None
        return Entity(
            entity_id=row["entity_id"],
            canonical_name=row["canonical_name"],
            entity_type=row["entity_type"],
            aliases=json.loads(row["aliases"]),
        )

    def find_entity_by_name(self, name: str, entity_type: Optional[str] = None) -> list[Entity]:
        """
        按名称查找实体（精确匹配 canonical_name 或 aliases 包含）。
        entity_type 可选过滤。
        """
        results: list[Entity] = []
        # 1. 精确匹配 canonical_name
        query = "SELECT * FROM entities WHERE canonical_name = ?"
        params = [name]
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        rows = self._conn.execute(query, params).fetchall()

        # 2. 遍历检查 aliases JSON（SQLite 不擅长 JSON 数组查询，走 Python）
        if not rows:
            query2 = "SELECT * FROM entities"
            params2: list = []
            if entity_type:
                query2 += " WHERE entity_type = ?"
                params2.append(entity_type)
            all_rows = self._conn.execute(query2, params2).fetchall()
            for row in all_rows:
                aliases = json.loads(row["aliases"])
                if name in aliases:
                    rows = [row]
                    break

        for row in rows:
            results.append(Entity(
                entity_id=row["entity_id"],
                canonical_name=row["canonical_name"],
                entity_type=row["entity_type"],
                aliases=json.loads(row["aliases"]),
            ))
        return results

    def list_entities_by_type(self, entity_type: str) -> list[Entity]:
        """列出指定类型的所有实体"""
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE entity_type = ?", (entity_type,)
        ).fetchall()
        return [
            Entity(
                entity_id=r["entity_id"],
                canonical_name=r["canonical_name"],
                entity_type=r["entity_type"],
                aliases=json.loads(r["aliases"]),
            )
            for r in rows
        ]

    # ─── 谓词 CRUD ──────────────────────────────────────────────────

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
                1 if pred.single_value else 0,
            ),
        )
        self._conn.commit()
        return pred.predicate_id

    def get_predicate(self, predicate_id: str) -> Optional[PredicateDef]:
        row = self._conn.execute(
            "SELECT * FROM predicates WHERE predicate_id = ?", (predicate_id,)
        ).fetchone()
        if row is None:
            return None
        return PredicateDef(
            predicate_id=row["predicate_id"],
            canonical_name=row["canonical_name"],
            aliases=json.loads(row["aliases"]),
            domain=json.loads(row["domain_types"]),
            range=json.loads(row["range_types"]),
            single_value=bool(row["single_value"]),
        )

    def find_predicate_by_alias(self, alias_text: str) -> Optional[PredicateDef]:
        """遍历谓词表，找到 aliases 包含 alias_text 的谓词"""
        rows = self._conn.execute("SELECT * FROM predicates").fetchall()
        for row in rows:
            aliases = json.loads(row["aliases"])
            if alias_text in aliases:
                return PredicateDef(
                    predicate_id=row["predicate_id"],
                    canonical_name=row["canonical_name"],
                    aliases=aliases,
                    domain=json.loads(row["domain_types"]),
                    range=json.loads(row["range_types"]),
                    single_value=bool(row["single_value"]),
                )
        return None

    def list_predicates(self) -> list[PredicateDef]:
        rows = self._conn.execute("SELECT * FROM predicates").fetchall()
        return [
            PredicateDef(
                predicate_id=r["predicate_id"],
                canonical_name=r["canonical_name"],
                aliases=json.loads(r["aliases"]),
                domain=json.loads(r["domain_types"]),
                range=json.loads(r["range_types"]),
                single_value=bool(r["single_value"]),
            )
            for r in rows
        ]

    # ─── 事实 CRUD ──────────────────────────────────────────────────

    def insert_fact(self, fact: Fact) -> str:
        self._conn.execute(
            """INSERT OR REPLACE INTO facts
               (fact_id, subject_id, predicate_id, object_id, object_value,
                source_text, source_id, observed_at, confidence, status, version,
                memory_type, scope, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact.fact_id,
                fact.subject_id,
                fact.predicate_id,
                fact.object_id,
                fact.object_value,
                fact.source_text,
                fact.source_id,
                fact.observed_at,
                fact.confidence,
                fact.status,
                fact.version,
                fact.memory_type,
                fact.scope,
                fact.project_id,
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
    ) -> list[Fact]:
        """冲突检测核心查询：只查同一作用域下相同 S+P 的事实。"""
        if scope == MemoryScope.PROJECT.value:
            if not project_id:
                raise ValueError("查询项目事实必须提供 project_id")
            rows = self._conn.execute(
                """SELECT * FROM facts
                   WHERE subject_id = ? AND predicate_id = ? AND status = ?
                     AND scope = ? AND project_id = ?""",
                (subject_id, predicate_id, status, scope, project_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM facts
                   WHERE subject_id = ? AND predicate_id = ? AND status = ?
                     AND scope = ? AND project_id IS NULL""",
                (subject_id, predicate_id, status, MemoryScope.GLOBAL.value),
            ).fetchall()
        return [self._row_to_fact(r) for r in rows]

    def update_fact_status(self, fact_id: str, new_status: str):
        self._conn.execute(
            "UPDATE facts SET status = ? WHERE fact_id = ?",
            (new_status, fact_id),
        )
        self._conn.commit()

    def get_fact(self, fact_id: str) -> Optional[Fact]:
        row = self._conn.execute(
            "SELECT * FROM facts WHERE fact_id = ?", (fact_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_fact(row)

    def list_facts(
        self,
        status: str = "active",
        limit: int = 100,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> list[Fact]:
        query = "SELECT * FROM facts WHERE status = ?"
        params: list = [status]
        if scope == MemoryScope.GLOBAL.value:
            query += " AND scope = ? AND project_id IS NULL"
            params.append(scope)
        elif scope == MemoryScope.PROJECT.value:
            if not project_id:
                raise ValueError("查询项目事实必须提供 project_id")
            query += " AND scope = ? AND project_id = ?"
            params.extend((scope, project_id))
        elif project_id is not None:
            raise ValueError("提供 project_id 时必须指定 scope='project'")
        query += " ORDER BY observed_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_fact(r) for r in rows]

    # ─── 事实候选 CRUD ──────────────────────────────────────────────

    def save_proposal(self, proposal) -> str:
        """持久化 propose 结果，供后续独立 HTTP commit 使用。"""
        from dataclasses import asdict

        self._conn.execute(
            """INSERT OR REPLACE INTO fact_proposals
               (proposal_id, raw_triple, admission, source_id, project_id_hint,
                scope_hint, metadata, status, result, rejection_reason, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?,
                       COALESCE((SELECT status FROM fact_proposals WHERE proposal_id = ?), 'proposed'),
                       COALESCE((SELECT result FROM fact_proposals WHERE proposal_id = ?), '{}'),
                       COALESCE((SELECT rejection_reason FROM fact_proposals WHERE proposal_id = ?), ''),
                       datetime('now'))""",
            (
                proposal.candidate_id,
                json.dumps(asdict(proposal.raw_triple), ensure_ascii=False),
                json.dumps(asdict(proposal.admission), ensure_ascii=False),
                proposal.source_id,
                proposal.project_id_hint,
                proposal.scope_hint,
                json.dumps(proposal.metadata, ensure_ascii=False),
                proposal.candidate_id,
                proposal.candidate_id,
                proposal.candidate_id,
            ),
        )
        self._conn.commit()
        return proposal.candidate_id

    def get_proposal(self, proposal_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM fact_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "proposal_id": row["proposal_id"],
            "raw_triple": json.loads(row["raw_triple"]),
            "admission": json.loads(row["admission"]),
            "source_id": row["source_id"] or "",
            "project_id_hint": row["project_id_hint"],
            "scope_hint": row["scope_hint"],
            "metadata": json.loads(row["metadata"] or "{}"),
            "status": row["status"],
            "result": json.loads(row["result"] or "{}"),
            "rejection_reason": row["rejection_reason"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_proposals(self, status: Optional[str] = None, limit: int = 100) -> list[dict]:
        query = "SELECT proposal_id FROM fact_proposals"
        params: list = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self.get_proposal(row["proposal_id"]) for row in rows]

    def update_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        result: Optional[dict] = None,
        rejection_reason: str = "",
    ) -> None:
        self._conn.execute(
            """UPDATE fact_proposals
               SET status = ?, result = ?, rejection_reason = ?, updated_at = datetime('now')
               WHERE proposal_id = ?""",
            (
                status,
                json.dumps(result or {}, ensure_ascii=False),
                rejection_reason,
                proposal_id,
            ),
        )
        self._conn.commit()

    def _row_to_fact(self, row: sqlite3.Row) -> Fact:
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
        )
