from __future__ import annotations

import json
import sqlite3

from scripts.migrate_vnext import apply_path, scan_connection


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


def test_invalid_version_is_invalid_not_promoted() -> None:
    conn = _legacy_db()
    conn.execute("UPDATE preferences SET version='not-a-version' WHERE memory_id='pref-1'")
    conn.commit()
    report = scan_connection(conn)
    invalid = next(item for item in report["records"] if item["memory_id"] == "pref-1")
    assert invalid["planned_action"] == "INVALID"
    assert "invalid_version" in invalid["invalid_reasons"]
    assert invalid["version_valid"] is False
    conn.close()


def test_apply_backups_and_leaves_uncertain_rows_in_review(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    backup_path = tmp_path / "legacy.backup.db"
    report_path = tmp_path / "migration.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE preferences (
            memory_id TEXT PRIMARY KEY, tenant_id TEXT, user_id TEXT,
            version INTEGER, parent_id TEXT, evidences TEXT, created_at TEXT,
            status TEXT, payload TEXT, content TEXT, preference_type TEXT,
            is_global INTEGER, scope_app TEXT, extra_payload TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO preferences
        (memory_id,tenant_id,user_id,version,evidences,status,payload,content,
         preference_type,is_global,scope_app,extra_payload)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        [
            ("good", "tenant-1", "user-1", 2, '[{"event_id":"evt-1"}]',
             "active", '{"project_id":"project-a"}', "markdown", "output_style", 0, "", "{}"),
            (
                "review", "", "user-1", 1, "[]", "active", "{}", "unknown",
                "output_style", 1, "", "{}",
            ),
        ],
    )
    conn.commit()
    conn.close()

    report = apply_path(
        db_path,
        report_path=report_path,
        backup_path=backup_path,
        checkpoint_path=checkpoint_path,
    )

    assert report["apply"]["status"] == "APPLIED_WITH_REVIEW"
    assert report["apply"]["applied_memory_ids"] == ["good"]
    assert report["apply"]["review_memory_ids"] == ["review"]
    assert report["validation"]["input_hash_verified"] is True
    assert backup_path.exists()
    assert checkpoint_path.exists()
    with sqlite3.connect(db_path) as checked:
        good = checked.execute(
            "SELECT tenant_id, extra_payload FROM preferences WHERE memory_id='good'"
        ).fetchone()
        review = checked.execute(
            "SELECT tenant_id, extra_payload FROM preferences WHERE memory_id='review'"
        ).fetchone()
        checkpoint = checked.execute(
            "SELECT status, applied_count, review_count FROM vnext_migration_checkpoints"
        ).fetchone()
    assert good[0] == "tenant-1"
    assert "vnext_authority" in json.loads(good[1])
    assert review[0] == ""
    assert "vnext_authority" not in json.loads(review[1])
    assert checkpoint == ("APPLIED_WITH_REVIEW", 1, 1)
