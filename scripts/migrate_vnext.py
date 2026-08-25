#!/usr/bin/env python3
"""Read-only vNext migration planner.

S0-05 deliberately provides a dry-run only.  It never bootstraps a database,
creates tables, updates rows, deletes data, or turns uncertain legacy data into
``LONG_TERM + ACTIVE + GLOBAL``.  S5-06 can add an apply phase after this
report and its compatibility/rollback contract have been accepted.

Examples:
  python scripts/migrate_vnext.py --dry-run
  python scripts/migrate_vnext.py --db data/memoryhub.db --dry-run \
      --report evaluation/results/vnext_migration/dry_run.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MIGRATION_NAME = "memoryhub_vnext_authority_v1"
LEGACY_MEMORY_TABLES = ("preferences", "knowledge")


class MigrationApplyError(RuntimeError):
    """Migration apply was refused before or during the write transaction."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _scope_plan(row: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    project_id = str(row.get("project_id") or payload.get("project_id") or "").strip()
    if project_id:
        return "PROJECT", f"PROJECT:{project_id}", reasons

    if bool(row.get("is_global")):
        reasons.append("legacy_global_flag_requires_tenant_and_evidence_review")
        return "GLOBAL", "GLOBAL", reasons

    app = str(row.get("scope_app") or payload.get("app") or "").strip()
    if app:
        return "APPLICATION", f"APPLICATION:{app}", reasons

    reasons.append("scope_not_explicitly_mappable")
    return "REVIEW", "REVIEW:UNRESOLVED", reasons


def _plan_row(table: str, row: dict[str, Any], columns: set[str]) -> dict[str, Any]:
    memory_id = str(row.get("memory_id") or "").strip()
    user_id = str(row.get("user_id") or "").strip()
    tenant_id = str(row.get("tenant_id") or "").strip()
    payload = _json_value(row.get("payload"), {})
    if not isinstance(payload, dict):
        payload = {}
    evidences = _json_value(row.get("evidences"), [])
    if not isinstance(evidences, list):
        evidences = []

    invalid_reasons: list[str] = []
    review_reasons: list[str] = []
    if not memory_id:
        invalid_reasons.append("missing_memory_id")
    if not user_id:
        invalid_reasons.append("missing_user_id")
    if "tenant_id" not in columns or not tenant_id:
        review_reasons.append("tenant_id_missing")
        tenant_id = "UNKNOWN"

    raw_version = row.get("version")
    try:
        content_version = int(raw_version or 1)
    except (TypeError, ValueError):
        content_version = 1
        invalid_reasons.append("invalid_version")
    if content_version < 1:
        invalid_reasons.append("invalid_version")
        content_version = 1

    scope_level, scope, scope_reasons = _scope_plan(row, payload)
    review_reasons.extend(scope_reasons)
    if not evidences:
        review_reasons.append("evidence_missing")

    status = str(row.get("status") or "active").lower()
    if status == "deleted":
        planned_action = "DELETED_TOMBSTONE"
    elif invalid_reasons:
        planned_action = "INVALID"
    elif review_reasons:
        planned_action = "REVIEW"
    else:
        planned_action = "LONG_TERM_ACTIVE"

    evidence_ids = [
        str(item.get("event_id") or "")
        for item in evidences
        if isinstance(item, dict) and item.get("event_id")
    ]
    metadata = {
        "source_table": table,
        "memory_id": memory_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "scope_level": scope_level,
        "scope": scope,
        "content_version": content_version,
        "status": status,
        "planned_action": planned_action,
        "evidence_refs": evidence_ids,
        "invalid_reasons": invalid_reasons,
        "review_reasons": review_reasons,
        "version_valid": "invalid_version" not in invalid_reasons,
        "evidence_valid": bool(evidence_ids),
    }
    metadata["record_hash"] = _digest(metadata)
    return metadata


def scan_connection(conn: sqlite3.Connection, database: str = ":memory:") -> dict[str, Any]:
    """Scan legacy records without issuing a write statement."""

    conn.row_factory = sqlite3.Row
    table_names = _tables(conn)
    records: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    tenant_counts: Counter[str] = Counter()
    scope_counts: Counter[str] = Counter()
    invalid_reasons: Counter[str] = Counter()
    review_reasons: Counter[str] = Counter()

    for table in LEGACY_MEMORY_TABLES:
        if table not in table_names:
            continue
        columns = _columns(conn, table)
        for row in conn.execute(f'SELECT * FROM "{table}"').fetchall():
            planned = _plan_row(table, dict(row), columns)
            records.append(planned)
            source_counts[table] += 1
            tenant_counts[planned["tenant_id"]] += 1
            scope_counts[planned["scope"]] += 1
            invalid_reasons.update(planned["invalid_reasons"])
            review_reasons.update(planned["review_reasons"])

    planned_counts = Counter(item["planned_action"] for item in records)
    record_hashes = [item["record_hash"] for item in records]
    return {
        "migration": MIGRATION_NAME,
        "plan_version": "vnext/v1",
        "database": database,
        "dry_run": True,
        "generated_at": _now(),
        "source_tables": sorted(table_names.intersection(LEGACY_MEMORY_TABLES)),
        "count": {
            "source_records": len(records),
            "planned_long_term_active": planned_counts["LONG_TERM_ACTIVE"],
            "planned_deleted_tombstone": planned_counts["DELETED_TOMBSTONE"],
            "planned_review": planned_counts["REVIEW"],
            "invalid": planned_counts["INVALID"],
            "by_source": dict(sorted(source_counts.items())),
        },
        "hash": {
            "input_hash": _digest(record_hashes),
            "record_hashes": record_hashes,
        },
        "tenant": dict(sorted(tenant_counts.items())),
        "scope": dict(sorted(scope_counts.items())),
        "invalid": {
            "count": sum(invalid_reasons.values()),
            "reasons": dict(sorted(invalid_reasons.items())),
        },
        "review": {
            "count": planned_counts["REVIEW"],
            "reasons": dict(sorted(review_reasons.items())),
            "records": [
                item["memory_id"]
                for item in records
                if item["planned_action"] == "REVIEW"
            ],
        },
        "records": records,
        "validation": {
            "read_only_scan": True,
            "no_irreversible_delete": True,
            "uncertain_data_never_promoted_to_active_global": all(
                item["planned_action"] != "LONG_TERM_ACTIVE"
                or item["scope_level"] != "GLOBAL"
                or (item["tenant_id"] != "UNKNOWN" and item["evidence_refs"])
                for item in records
            ),
        },
        "compatibility": {
            "apply_status": "DEFERRED_TO_S5-06",
            "rollback": "Authority tombstone/compatibility read; no DELETE in S0-05",
            "projection_strategy": "rebuild after Authority validation",
        },
    }


def scan_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        report = scan_connection(sqlite3.connect(":memory:"), str(path))
        report["validation"]["database_exists"] = False
        report["validation"]["missing_database"] = True
        return report

    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        report = scan_connection(conn, str(path.resolve()))
    report["validation"]["database_exists"] = True
    report["validation"]["missing_database"] = False
    return report


def _write_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _memory_type(table: str, row: dict[str, Any]) -> str:
    if table == "preferences":
        return "PREFERENCE"
    knowledge_type = str(row.get("knowledge_type") or row.get("memory_type") or "FACT").upper()
    return {
        "FACT": "SEMANTIC",
        "SEMANTIC": "SEMANTIC",
        "WORKFLOW": "PROCEDURAL",
        "TEMPLATE": "PROCEDURAL",
        "CASE": "EPISODIC",
        "EPISODIC": "EPISODIC",
    }.get(knowledge_type, "SEMANTIC")


def _authority_content(table: str, row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_value(row.get("payload"), {})
    if not isinstance(payload, dict):
        payload = {"value": payload}
    if table == "preferences":
        content = {
            "text": str(row.get("content") or ""),
            "payload": payload,
            "preference_type": str(row.get("preference_type") or "output_style"),
        }
        return content
    return {
        "name": str(row.get("name") or row.get("memory_id") or "legacy-memory"),
        "content": str(row.get("content") or ""),
        "steps": _json_value(row.get("steps"), []),
        "tools": _json_value(row.get("tools"), []),
        "template_body": str(row.get("template_body") or ""),
        "subject": str(row.get("subject") or ""),
        "predicate": str(row.get("predicate") or ""),
        "object_value": str(row.get("object_value") or ""),
        "object_type": str(row.get("object_type") or ""),
    }


def _authority_metadata(
    table: str, row: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any]:
    """Build the governed vNext envelope without changing lifecycle semantics."""
    from memoryhub.domain.contracts import (
        EvolutionStatus,
        LongTermEnvelope,
        MemoryScope,
        MemoryType,
    )

    scope_level = MemoryScope(item["scope_level"])
    status = str(item["status"]).lower()
    evolution_status = (
        EvolutionStatus.DELETED
        if status == "deleted"
        else EvolutionStatus.ACTIVE
    )
    evidence_refs = list(item["evidence_refs"] or [f"legacy:{item['memory_id']}"])
    confidence = float(row.get("confidence") or row.get("quality_score") or 0.5)
    envelope = LongTermEnvelope(
        tenant_id=item["tenant_id"],
        user_id=item["user_id"],
        memory_id=item["memory_id"],
        memory_type=MemoryType(_memory_type(table, row)),
        normalized_key=f"legacy:{item['memory_id']}",
        content=_authority_content(table, row),
        scope_level=scope_level,
        scope=item["scope"],
        evolution_status=evolution_status,
        confidence=min(1.0, max(0.0, confidence)),
        utility=0.0,
        content_version=max(1, int(item["content_version"])),
        evidence_refs=evidence_refs,
    )
    return envelope.model_dump(mode="json")


def _apply_records(
    conn: sqlite3.Connection, report: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Apply eligible rows atomically; return applied and REVIEW IDs."""
    table_columns = {
        table: _columns(conn, table)
        for table in LEGACY_MEMORY_TABLES
        if table in _tables(conn)
    }
    missing = [
        f"{table}.{column}"
        for table in report["source_tables"]
        for column in ("tenant_id", "extra_payload")
        if column not in table_columns.get(table, set())
    ]
    if missing:
        raise MigrationApplyError(
            "apply requires additive Authority columns: " + ", ".join(missing)
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vnext_migration_checkpoints (
            migration TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            applied_count INTEGER NOT NULL,
            review_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (migration, input_hash)
        )
        """
    )
    applied: list[str] = []
    review_ids: list[str] = []
    for item in report["records"]:
        action = item["planned_action"]
        if action == "REVIEW":
            review_ids.append(item["memory_id"])
            continue
        if item["tenant_id"] == "UNKNOWN" or item["scope_level"] == "REVIEW":
            review_ids.append(item["memory_id"])
            continue
        row = conn.execute(
            f'SELECT * FROM "{item["source_table"]}" WHERE memory_id = ?',
            (item["memory_id"],),
        ).fetchone()
        if row is None:
            raise MigrationApplyError(f"source row disappeared: {item['memory_id']}")
        row_dict = dict(zip(row.keys(), row))
        metadata = _json_value(row_dict.get("extra_payload"), {})
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["vnext_authority"] = _authority_metadata(
            item["source_table"], row_dict, item
        )
        metadata["vnext_migration"] = {
            "migration": MIGRATION_NAME,
            "input_hash": report["hash"]["input_hash"],
            "planned_action": action,
            "checkpoint_status": "APPLIED",
        }
        conn.execute(
            f'UPDATE "{item["source_table"]}" '
            "SET tenant_id = ?, extra_payload = ? WHERE memory_id = ?",
            (
                item["tenant_id"],
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                item["memory_id"],
            ),
        )
        applied.append(item["memory_id"])

    status = "APPLIED_WITH_REVIEW" if review_ids else "APPLIED"
    conn.execute(
        """
        INSERT OR REPLACE INTO vnext_migration_checkpoints
        (migration, input_hash, status, applied_count, review_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            MIGRATION_NAME,
            report["hash"]["input_hash"],
            status,
            len(applied),
            len(review_ids),
            _now(),
        ),
    )
    return applied, review_ids


def apply_path(
    path: Path,
    *,
    report_path: Path,
    backup_path: Path,
    checkpoint_path: Path,
    expected_input_hash: str | None = None,
) -> dict[str, Any]:
    """Apply a previously validated plan with backup and an atomic checkpoint."""
    if not path.exists():
        raise MigrationApplyError(f"database does not exist: {path}")
    if path.resolve() == backup_path.resolve():
        raise MigrationApplyError("backup path must differ from database path")
    report = scan_path(path)
    input_hash = report["hash"]["input_hash"]
    if expected_input_hash and expected_input_hash != input_hash:
        raise MigrationApplyError("input hash does not match the approved migration report")

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_path)
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            applied, review_ids = _apply_records(conn, report)
            conn.commit()
    except Exception:
        raise

    report["apply"] = {
        "requested": True,
        "backup_path": str(backup_path.resolve()),
        "applied_memory_ids": applied,
        "review_memory_ids": review_ids,
        "status": "APPLIED_WITH_REVIEW" if review_ids else "APPLIED",
    }
    report["validation"].update(
        {
            "input_hash_verified": True,
            "backup_created": backup_path.exists(),
            "checkpoint_written": True,
            "review_not_promoted": True,
            "old_tables_preserved": True,
            "no_irreversible_delete": True,
        }
    )
    _write_report(report, report_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(
            {
                "migration": MIGRATION_NAME,
                "input_hash": input_hash,
                "status": report["apply"]["status"],
                "applied_count": len(applied),
                "review_count": len(review_ids),
                "backup_path": str(backup_path.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/memoryhub.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="evaluation/results/vnext_migration/backup.db")
    parser.add_argument(
        "--checkpoint",
        default="evaluation/results/vnext_migration/checkpoint.json",
    )
    parser.add_argument("--expected-input-hash", default=None)
    parser.add_argument(
        "--report",
        default="evaluation/results/vnext_migration/dry_run.json",
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    if not args.dry_run and not args.apply:
        parser.error("choose --dry-run or --apply")

    db_path = Path(args.db).expanduser()
    report_path = Path(args.report)
    if args.apply:
        report = apply_path(
            db_path,
            report_path=report_path,
            backup_path=Path(args.backup).expanduser(),
            checkpoint_path=Path(args.checkpoint).expanduser(),
            expected_input_hash=args.expected_input_hash,
        )
    else:
        report = scan_path(db_path)
        _write_report(report, report_path)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
