"""SQLite storage for facts, entities, and predicates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

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
    pending_index    INTEGER NOT NULL DEFAULT 1,
    index_version    INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (subject_id) REFERENCES entities(entity_id),
    FOREIGN KEY (predicate_id) REFERENCES predicates(predicate_id)
);
CREATE TABLE IF NOT EXISTS fact_evidence (
    evidence_id TEXT PRIMARY KEY,
    fact_id     TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    source_id       TEXT DEFAULT '',
    source_text     TEXT DEFAULT '',
    event_id        TEXT DEFAULT '',
    source_hash     TEXT DEFAULT '',
    safety_audit_id TEXT DEFAULT '',
    safety_action   TEXT DEFAULT '',
    observed_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_evidence_owner_fact
    ON fact_evidence(user_id, fact_id);
CREATE TABLE IF NOT EXISTS fact_conflicts (
    conflict_id     TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    new_fact_id     TEXT NOT NULL,
    existing_fact_id TEXT DEFAULT '',
    relation        TEXT NOT NULL,
    resolution      TEXT DEFAULT '',
    reason          TEXT DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_conflicts_owner
    ON fact_conflicts(user_id, created_at);
CREATE TABLE IF NOT EXISTS memory_projection_outbox (
    outbox_id      TEXT PRIMARY KEY,
    memory_id      TEXT NOT NULL,
    memory_type    TEXT NOT NULL,
    operation      TEXT NOT NULL,
    payload_hash   TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TEXT,
    error_code     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_status_next_retry
    ON memory_projection_outbox(status, next_retry_at);
CREATE INDEX IF NOT EXISTS ix_memory_projection_outbox_memory_id_type
    ON memory_projection_outbox(memory_id, memory_type);
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
            "access_count_30d": (
                "ALTER TABLE facts ADD COLUMN access_count_30d INTEGER NOT NULL DEFAULT 0"
            ),
            "pending_index": (
                "ALTER TABLE facts ADD COLUMN pending_index INTEGER NOT NULL DEFAULT 1"
            ),
            "index_version": (
                "ALTER TABLE facts ADD COLUMN index_version INTEGER NOT NULL DEFAULT 0"
            ),
        }
        for column, sql in migrations.items():
            if column not in fact_columns:
                self._conn.execute(sql)
        evidence_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(fact_evidence)")
        }
        evidence_migrations = {
            "event_id": "ALTER TABLE fact_evidence ADD COLUMN event_id TEXT DEFAULT ''",
            "source_hash": "ALTER TABLE fact_evidence ADD COLUMN source_hash TEXT DEFAULT ''",
            "safety_audit_id": (
                "ALTER TABLE fact_evidence ADD COLUMN safety_audit_id TEXT DEFAULT ''"
            ),
            "safety_action": "ALTER TABLE fact_evidence ADD COLUMN safety_action TEXT DEFAULT ''",
        }
        for column, sql in evidence_migrations.items():
            if column not in evidence_columns:
                self._conn.execute(sql)

        for row in self._conn.execute(
            "SELECT evidence_id, fact_id, user_id, source_id, source_text, event_id, source_hash "
            "FROM fact_evidence"
        ).fetchall():
            event_id = row["event_id"] or row["source_id"] or f"legacy:{row['evidence_id']}"
            source_hash = row["source_hash"] or hashlib.sha256(
                f"{row['user_id']}|{row['fact_id']}|{row['source_id']}|{row['source_text']}".encode(
                    "utf-8"
                )
            ).hexdigest()
            self._conn.execute(
                "UPDATE fact_evidence SET event_id = ?, source_hash = ? WHERE evidence_id = ?",
                (event_id, source_hash, row["evidence_id"]),
            )

        self._conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_facts_owner_status ON facts(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_facts_scope_sp
                ON facts(user_id, scope, project_id, subject_id, predicate_id, status);
            CREATE INDEX IF NOT EXISTS idx_entities_owner_type ON entities(user_id, entity_type);
            CREATE INDEX IF NOT EXISTS idx_entities_owner_name ON entities(user_id, canonical_name);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_fact_evidence_fact_event_source
                ON fact_evidence(fact_id, event_id, source_hash);
            """
        )

    @contextmanager
    def transaction(self):
        """Run fact, conflict, and evidence writes as one SQLite transaction."""
        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

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

    def _insert_fact(self, fact: Fact) -> str:
        """Private Fact persistence sink; callers must own the transaction boundary."""
        self._conn.execute(
            """INSERT OR REPLACE INTO facts
               (fact_id, subject_id, predicate_id, object_id, object_value,
                source_text, source_id, observed_at, confidence, status, version,
                memory_type, scope, project_id, user_id, last_accessed_at,
                access_count_30d, pending_index, index_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fact.fact_id, fact.subject_id, fact.predicate_id, fact.object_id,
                fact.object_value, fact.source_text, fact.source_id,
                fact.observed_at, fact.confidence, fact.status, fact.version,
                fact.memory_type, fact.scope, fact.project_id, fact.user_id,
                fact.last_accessed_at, fact.access_count_30d,
                int(fact.pending_index), fact.index_version,
            ),
        )
        return fact.fact_id

    def insert_fact(self, fact: Fact) -> str:
        """Legacy fixture helper; production code must use FactMemoryPipeline commits."""
        with self.transaction():
            return self._insert_fact(fact)

    def list_pending_facts(self, limit: int = 100) -> list[Fact]:
        rows = self._conn.execute(
            "SELECT * FROM facts WHERE pending_index = 1 ORDER BY observed_at ASC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def mark_indexed(self, fact_id: str, version: int, user_id: str = "") -> bool:
        query = "UPDATE facts SET pending_index = 0, index_version = ? WHERE fact_id = ?"
        params: list[object] = [version, fact_id]
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        cursor = self._conn.execute(query, params)
        self._conn.commit()
        return cursor.rowcount > 0

    def _enqueue_fact_projection(self, fact: Fact) -> str:
        """Add one Fact projection job inside the current Fact transaction."""
        operation = "upsert" if fact.status == "active" else "delete"
        payload = {
            "memory_id": fact.fact_id,
            "memory_type": "fact",
            "operation": operation,
            "status": fact.status,
            "version": fact.version,
            "index_version": fact.index_version,
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        outbox_id = "outbox_" + hashlib.sha256(
            f"{fact.fact_id}|fact|{operation}|{payload_hash}".encode("utf-8")
        ).hexdigest()[:48]
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT OR IGNORE INTO memory_projection_outbox
               (outbox_id, memory_id, memory_type, operation, payload_hash, status,
                attempts, next_retry_at, error_code, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 0, NULL, '', ?, ?)""",
            (outbox_id, fact.fact_id, "fact", operation, payload_hash, now, now),
        )
        return outbox_id

    def _save_fact_evidence(self, fact: Fact, *, provenance=None) -> str:
        """Private provenance-aware evidence sink used by approved Fact commits."""
        event_id = str(getattr(provenance, "event_id", "") or fact.source_id or fact.fact_id)
        source_hash = str(getattr(provenance, "source_hash", "") or hashlib.sha256(
            f"{fact.user_id}|{fact.fact_id}|{fact.source_id}|{fact.source_text}".encode("utf-8")
        ).hexdigest())
        audit_id = str(getattr(provenance, "safety_audit_id", "") or "")
        safety_action = getattr(provenance, "safety_action", "")
        safety_action = str(getattr(safety_action, "value", safety_action) or "")
        evidence_id = "fev_" + hashlib.sha256(
            f"{fact.fact_id}|{event_id}|{source_hash}".encode("utf-8")
        ).hexdigest()[:24]
        self._conn.execute(
            """INSERT OR IGNORE INTO fact_evidence
               (evidence_id, fact_id, user_id, source_id, source_text, event_id,
                source_hash, safety_audit_id, safety_action, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence_id,
                fact.fact_id,
                fact.user_id,
                fact.source_id,
                fact.source_text,
                event_id,
                source_hash,
                audit_id,
                safety_action,
                fact.observed_at,
            ),
        )
        return evidence_id

    def save_fact_evidence(self, fact: Fact, *, provenance=None) -> str:
        """Compatibility helper that persists Fact evidence in its own transaction."""
        with self.transaction():
            return self._save_fact_evidence(fact, provenance=provenance)

    def _save_manual_fact_evidence(self, fact: Fact, evidence: Any) -> str:
        """Append one caller-supplied item to the Fact's append-only evidence chain."""
        event_id = str(getattr(evidence, "event_id", "") or fact.source_id or fact.fact_id)
        content = str(getattr(evidence, "content", "") or "").strip()
        source_type = str(getattr(evidence, "source_type", "manual_config") or "manual_config")
        timestamp = getattr(evidence, "timestamp", None) or datetime.now(timezone.utc)
        observed_at = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
        source_hash = hashlib.sha256(
            f"{fact.user_id}|{fact.fact_id}|{event_id}|{source_type}|{content}|{observed_at}".encode("utf-8")
        ).hexdigest()
        evidence_id = "fev_" + hashlib.sha256(
            f"{fact.fact_id}|{event_id}|{source_hash}".encode("utf-8")
        ).hexdigest()[:24]
        self._conn.execute(
            """INSERT OR IGNORE INTO fact_evidence
               (evidence_id, fact_id, user_id, source_id, source_text, event_id,
                source_hash, safety_audit_id, safety_action, observed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                evidence_id,
                fact.fact_id,
                fact.user_id,
                f"manual_evidence:{source_type}",
                content,
                event_id,
                source_hash,
                "",
                "manual_update",
                observed_at,
            ),
        )
        return evidence_id

    def list_fact_evidence(self, fact_id: str, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM fact_evidence WHERE fact_id = ? AND user_id = ? ORDER BY observed_at",
            (fact_id, user_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _save_fact_conflict(self, result) -> None:
        old_id = result.existing_fact.fact_id if result.existing_fact is not None else ""
        user_id = result.new_fact.user_id
        conflict_id = "fconf_" + hashlib.sha256(
            f"{user_id}|{old_id}|{result.new_fact.fact_id}|{result.relation}".encode("utf-8")
        ).hexdigest()[:24]
        self._conn.execute(
            """INSERT OR REPLACE INTO fact_conflicts
               (conflict_id, user_id, new_fact_id, existing_fact_id,
                relation, resolution, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                conflict_id, user_id, result.new_fact.fact_id, old_id,
                result.relation, result.resolution or "", result.reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def save_fact_conflict(self, result) -> None:
        """Compatibility helper that persists a conflict in its own transaction."""
        with self.transaction():
            self._save_fact_conflict(result)

    def list_fact_conflicts(self, user_id: str, limit: int = 100) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM fact_conflicts WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_fact_artifacts(self, fact_ids: list[str], user_id: str) -> int:
        ids = [item for item in dict.fromkeys(fact_ids) if item]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        params = [user_id, *ids]
        evidence = self._conn.execute(
            f"DELETE FROM fact_evidence WHERE user_id = ? AND fact_id IN ({placeholders})",
            params,
        ).rowcount
        conflicts = self._conn.execute(
            f"""DELETE FROM fact_conflicts WHERE user_id = ? AND
                (new_fact_id IN ({placeholders}) OR existing_fact_id IN ({placeholders}))""",
            [user_id, *ids, *ids],
        ).rowcount
        self._conn.commit()
        return evidence + conflicts
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

    def _update_fact_status(
        self, fact_id: str, new_status: str, user_id: Optional[str] = None
    ) -> bool:
        query = "UPDATE facts SET status = ?, pending_index = 1 WHERE fact_id = ?"
        params: list[object] = [new_status, fact_id]
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        cursor = self._conn.execute(query, params)
        return cursor.rowcount > 0

    def transition_fact_status(
        self,
        fact_id: str,
        new_status: str,
        *,
        user_id: Optional[str] = None,
        transition_action: str = "supersede",
    ) -> bool:
        """Atomically persist a Fact lifecycle change, lineage, and projection job."""
        with self.transaction():
            changed = self._update_fact_status(fact_id, new_status, user_id)
            if not changed:
                return False
            fact = self.get_fact(fact_id, user_id=user_id)
            if fact is None:
                return False
            self._append_fact_lifecycle_lineage(fact, transition_action)
            self._enqueue_fact_projection(fact)
            return True

    def _append_fact_lifecycle_lineage(self, fact: Fact, transition_action: str) -> None:
        """Append Fact lifecycle lineage when the unified authority table is present."""
        table = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_lineage'"
        ).fetchone()
        if table is None:
            return
        previous = self._conn.execute(
            "SELECT MAX(evidence_revision) FROM memory_lineage "
            "WHERE memory_id = ? AND memory_type = 'fact'",
            (fact.fact_id,),
        ).fetchone()[0]
        evidence_revision = int(previous or 0) + 1
        lineage_id = "lineage_" + hashlib.sha256(
            (
                f"{fact.fact_id}|fact|{fact.version}|{evidence_revision}|"
                f"{transition_action}|{fact.status}"
            ).encode("utf-8")
        ).hexdigest()[:48]
        self._conn.execute(
            """INSERT OR IGNORE INTO memory_lineage
               (lineage_id, memory_id, memory_type, parent_memory_id, root_memory_id,
                semantic_version, evidence_revision, transition_action, created_at)
               VALUES (?, ?, 'fact', NULL, ?, ?, ?, ?, ?)""",
            (
                lineage_id,
                fact.fact_id,
                fact.fact_id,
                max(1, int(fact.version)),
                evidence_revision,
                transition_action,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def update_fact(
        self,
        fact_id: str,
        *,
        user_id: str,
        object_value: str | None = None,
        object_type: str | None = None,
        confidence: float | None = None,
        status: str | None = None,
        version: int | None = None,
        evidence_text: str | None = None,
        evidences: list[Any] | None = None,
        transition_action: str = "revise",
    ) -> Fact | None:
        """Apply a manual Fact edit together with lineage, evidence, and an outbox job.

        This is the Fact equivalent of the domain writer: the business row, optional
        new evidence, lineage, and projection command are persisted in one transaction.
        """
        with self.transaction():
            current = self.get_fact(fact_id, user_id=user_id)
            if current is None:
                return None

            new_object_value = (
                str(object_value).strip()
                if object_value is not None
                else current.object_value
            )
            if not new_object_value:
                raise ValueError("fact object_value must not be empty")
            if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
                raise ValueError("fact confidence must be within [0, 1]")

            old_entity = self.get_entity(current.object_id, user_id=user_id)
            current_object_type = str(getattr(old_entity, "entity_type", "") or "Other")
            entity_type = str(object_type or current_object_type or "Other").strip() or "Other"
            object_changed = (
                new_object_value != current.object_value
                or entity_type != current_object_type
            )
            new_object_id = current.object_id
            if object_changed:
                new_object_id = Entity.make_id(entity_type, new_object_value, user_id)
                self._conn.execute(
                    """INSERT OR REPLACE INTO entities
                       (entity_id, canonical_name, entity_type, aliases, user_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        new_object_id,
                        new_object_value,
                        entity_type,
                        json.dumps([], ensure_ascii=False),
                        user_id,
                    ),
                )

            semantic_changed = (
                object_changed
                or (confidence is not None and float(confidence) != current.confidence)
            )
            new_version = current.version + 1 if semantic_changed else current.version
            if version is not None:
                if int(version) < current.version:
                    raise ValueError("fact version cannot move backwards")
                new_version = max(new_version, int(version))
            new_status = str(status or current.status)
            if not new_status:
                raise ValueError("fact status must not be empty")

            source_text = (
                str(evidence_text).strip()
                if evidence_text is not None
                else current.source_text
            )
            observed_at = (
                datetime.now(timezone.utc).isoformat()
                if evidence_text is not None
                else current.observed_at
            )
            source_id = (
                f"manual_update:{fact_id}:v{new_version}"
                if evidence_text is not None
                else current.source_id
            )
            cursor = self._conn.execute(
                """UPDATE facts
                   SET object_id = ?, object_value = ?, source_text = ?, source_id = ?,
                       observed_at = ?, confidence = ?, status = ?, version = ?,
                       pending_index = 1
                   WHERE fact_id = ? AND user_id = ?""",
                (
                    new_object_id,
                    new_object_value,
                    source_text,
                    source_id,
                    observed_at,
                    float(confidence) if confidence is not None else current.confidence,
                    new_status,
                    new_version,
                    fact_id,
                    user_id,
                ),
            )
            if cursor.rowcount <= 0:
                return None
            updated = self.get_fact(fact_id, user_id=user_id)
            if updated is None:
                return None
            if evidence_text is not None and source_text:
                self._save_fact_evidence(updated)
            for evidence in evidences or []:
                self._save_manual_fact_evidence(updated, evidence)
            self._append_fact_lifecycle_lineage(updated, transition_action)
            self._enqueue_fact_projection(updated)
            return updated

    def update_fact_status(
        self, fact_id: str, new_status: str, user_id: Optional[str] = None
    ) -> bool:
        """Compatibility helper; production transitions are owned by the pipeline."""
        with self.transaction():
            return self._update_fact_status(fact_id, new_status, user_id)

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
            pending_index=bool(row["pending_index"]),
            index_version=row["index_version"],
        )
