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
        "content_version": max(1, int(row.get("version") or 1)),
        "status": status,
        "planned_action": planned_action,
        "evidence_refs": evidence_ids,
        "invalid_reasons": invalid_reasons,
        "review_reasons": review_reasons,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/memoryhub.db")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report",
        default="evaluation/results/vnext_migration/dry_run.json",
    )
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("S0-05 only supports the read-only --dry-run phase")

    report = scan_path(Path(args.db).expanduser())
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
