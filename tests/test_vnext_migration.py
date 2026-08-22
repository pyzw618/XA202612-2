from __future__ import annotations

import sqlite3

from scripts.migrate_vnext import scan_connection


def _legacy_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE preferences (
            memory_id TEXT PRIMARY KEY,
            user_id TEXT,
            version INTEGER,
            parent_id TEXT,
            evidences TEXT,
            created_at TEXT,
            status TEXT,
            payload TEXT,
            is_global INTEGER,
            scope_app TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO preferences
        (memory_id,user_id,version,parent_id,evidences,created_at,status,payload,is_global,scope_app)
        VALUES (
            'pref-1','user-1',2,NULL,'[{"event_id":"evt-1"}]',
            '2026-08-22T05:00:00Z','active','{"project_id":"project-a"}',0,''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO preferences
        (memory_id,user_id,version,parent_id,evidences,created_at,status,payload,is_global,scope_app)
        VALUES ('pref-2','user-1',1,NULL,'[]','2026-08-22T05:00:00Z','active','{}',1,'')
        """
    )
    conn.commit()
    return conn


def test_dry_run_reports_count_hash_tenant_scope_invalid_and_review() -> None:
    conn = _legacy_db()
    report = scan_connection(conn)

    assert report["dry_run"] is True
    assert report["count"]["source_records"] == 2
    assert report["count"]["planned_review"] == 2
    assert report["tenant"]["UNKNOWN"] == 2
    assert report["scope"]["PROJECT:project-a"] == 1
    assert report["scope"]["GLOBAL"] == 1
    assert report["hash"]["input_hash"]
    assert report["review"]["count"] == 2
    assert report["validation"]["read_only_scan"] is True
    assert report["validation"]["no_irreversible_delete"] is True
    conn.close()


def test_dry_run_does_not_change_schema_or_rows() -> None:
    conn = _legacy_db()
    before_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    before_rows = conn.execute(
        "SELECT memory_id, payload FROM preferences ORDER BY memory_id"
    ).fetchall()

    scan_connection(conn)

    after_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    after_rows = conn.execute(
        "SELECT memory_id, payload FROM preferences ORDER BY memory_id"
    ).fetchall()
    assert [tuple(row) for row in before_tables] == [tuple(row) for row in after_tables]
    assert [tuple(row) for row in before_rows] == [tuple(row) for row in after_rows]
    conn.close()


def test_deleted_legacy_record_is_planned_as_tombstone_not_active() -> None:
    conn = _legacy_db()
    conn.execute(
        "UPDATE preferences SET memory_id='pref-deleted', status='deleted' WHERE memory_id='pref-1'"
    )
    conn.commit()

    report = scan_connection(conn)
    deleted = next(item for item in report["records"] if item["memory_id"] == "pref-deleted")
    assert deleted["planned_action"] == "DELETED_TOMBSTONE"
    assert deleted["planned_action"] != "LONG_TERM_ACTIVE"
    conn.close()
