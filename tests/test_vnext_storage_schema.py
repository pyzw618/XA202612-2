from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from memoryhub.storage.database import Database
from memoryhub.storage.models import (
    IdempotencyRecordRow,
    MemoryCandidateRow,
)

ROOT = Path(__file__).parents[1]

_VNEXT_TABLES = {
    "working_states",
    "task_episodes",
    "episode_events",
    "memory_candidates",
    "memory_activations",
    "retrieval_logs",
    "idempotency_records",
}


def _database() -> tuple[Database, Path]:
    db_path = ROOT / "evaluation" / "results" / "vnext_storage_test.db"
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    return Database(str(db_path)), db_path


def _close_database(db: Database, db_path: Path) -> None:
    db.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def test_vnext_tables_indexes_and_governance_columns_are_created_idempotently() -> None:
    db, db_path = _database()
    try:
        db.init_schema()
        db.init_schema()
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        assert _VNEXT_TABLES <= tables

        for table in _VNEXT_TABLES:
            columns = {column["name"] for column in inspector.get_columns(table)}
            assert {"tenant_id", "user_id"} <= columns

        candidate_columns = {
            column["name"] for column in inspector.get_columns("memory_candidates")
        }
        assert {"formation_status", "status", "content_version"} <= candidate_columns
        activation_columns = {
            column["name"] for column in inspector.get_columns("memory_activations")
        }
        assert {"query_id", "memory_id", "content_version"} <= activation_columns

        episode_constraints = inspector.get_unique_constraints("episode_events")
        assert any(
            constraint["column_names"] == ["tenant_id", "episode_id", "seq_no"]
            for constraint in episode_constraints
        )
        idempotency_constraints = inspector.get_unique_constraints("idempotency_records")
        assert any(
            constraint["column_names"] == ["tenant_id", "idempotency_key"]
            for constraint in idempotency_constraints
        )

        event_columns = {column["name"] for column in inspector.get_columns("events")}
        evidence_columns = {
            column["name"] for column in inspector.get_columns("memory_evidence")
        }
        outbox_columns = {
            column["name"]
            for column in inspector.get_columns("memory_projection_outbox")
        }
        assert {"tenant_id", "content_version", "idempotency_key", "trace_id"} <= event_columns
        assert {"tenant_id", "content_ref", "content_version"} <= evidence_columns
        assert {"tenant_id", "event_id", "projection_type", "content_version"} <= outbox_columns
    finally:
        _close_database(db, db_path)


def test_idempotency_and_candidate_constraints_are_tenant_scoped() -> None:
    db, db_path = _database()
    try:
        db.init_schema()
        with db.session() as session:
            session.add_all([
                IdempotencyRecordRow(
                    idempotency_record_id="idem-a",
                    tenant_id="tenant-a",
                    user_id="user-a",
                    idempotency_key="same-key",
                    request_hash="a" * 64,
                ),
                IdempotencyRecordRow(
                    idempotency_record_id="idem-b",
                    tenant_id="tenant-b",
                    user_id="user-b",
                    idempotency_key="same-key",
                    request_hash="b" * 64,
                ),
            ])

        with pytest.raises(IntegrityError):
            with db.session() as session:
                session.add(
                    IdempotencyRecordRow(
                        idempotency_record_id="idem-a-retry",
                        tenant_id="tenant-a",
                        user_id="user-a",
                        idempotency_key="same-key",
                        request_hash="a" * 64,
                    )
                )

        with pytest.raises(IntegrityError):
            with db.session() as session:
                session.add(
                    MemoryCandidateRow(
                        candidate_id="candidate-invalid",
                        tenant_id="tenant-a",
                        user_id="user-a",
                        memory_type="PREFERENCE",
                        normalized_key="format.report",
                        claim={"value": "DOCX"},
                        scope_level="PROJECT",
                        scope="PROJECT:reporting",
                        status="ACTIVE",
                        confidence=0.5,
                        utility=0.5,
                        stability=0.5,
                    )
                )
    finally:
        _close_database(db, db_path)


def test_legacy_sqlite_tables_receive_additive_vnext_columns() -> None:
    db, db_path = _database()
    try:
        connection = sqlite3.connect(db_path)
        try:
            connection.executescript(
                """
                CREATE TABLE events (event_id VARCHAR(32) PRIMARY KEY);
                CREATE TABLE memory_lineage (
                    lineage_id VARCHAR(64) PRIMARY KEY,
                    memory_id VARCHAR(64) NOT NULL,
                    memory_type VARCHAR(16) NOT NULL,
                    root_memory_id VARCHAR(64),
                    semantic_version INTEGER NOT NULL,
                    evidence_revision INTEGER NOT NULL,
                    transition_action VARCHAR(16) NOT NULL,
                    created_at DATETIME NOT NULL
                );
                CREATE TABLE memory_evidence (
                    evidence_id VARCHAR(64) PRIMARY KEY,
                    memory_id VARCHAR(64) NOT NULL,
                    memory_type VARCHAR(16) NOT NULL,
                    event_id VARCHAR(64) NOT NULL,
                    source_hash VARCHAR(64) NOT NULL,
                    source_type VARCHAR(32) NOT NULL,
                    excerpt TEXT NOT NULL,
                    occurred_at DATETIME NOT NULL,
                    quality_score FLOAT NOT NULL,
                    safety_audit_id VARCHAR(64)
                );
                CREATE TABLE memory_projection_outbox (
                    outbox_id VARCHAR(64) PRIMARY KEY,
                    memory_id VARCHAR(64) NOT NULL,
                    memory_type VARCHAR(16) NOT NULL,
                    operation VARCHAR(32) NOT NULL,
                    payload_hash VARCHAR(64) NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_retry_at DATETIME,
                    error_code VARCHAR(128) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                );
                """
            )
        finally:
            connection.close()

        db.init_schema()
        inspector = inspect(db.engine)
        event_columns = {column["name"] for column in inspector.get_columns("events")}
        outbox_columns = {
            column["name"]
            for column in inspector.get_columns("memory_projection_outbox")
        }
        assert {"tenant_id", "content_version", "trace_id"} <= event_columns
        assert {"tenant_id", "event_id", "projection_type"} <= outbox_columns
    finally:
        _close_database(db, db_path)
