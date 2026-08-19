#!/usr/bin/env python3
"""Idempotently migrate legacy evidence/version data into remem authority tables.

Usage:
  python scripts/migrate_memory_provenance.py --db data/memoryhub.db --dry-run
  python scripts/migrate_memory_provenance.py --db data/memoryhub.db \
      --report report.json --rollback-sql rollback.sql
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MIGRATION_NAME = "main_to_remem_provenance_v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()


def loads(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def bootstrap(db_path: str) -> None:
    from memoryhub.storage.database import Database

    db = Database(db_path)
    db.init_schema()
    db.close()


def checkpoint_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS memory_migration_checkpoint (
        migration_name TEXT NOT NULL, source_name TEXT NOT NULL, status TEXT NOT NULL,
        detail_hash TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (migration_name, source_name))""")


def legacy_root(rows: list[sqlite3.Row], has_root: bool) -> dict[str, str]:
    parent = {str(row["memory_id"]): str(row["parent_id"] or "") for row in rows}
    explicit = (
        {str(row["memory_id"]): str(row["root_id"] or "") for row in rows} if has_root else {}
    )
    roots: dict[str, str] = {}
    for memory_id in parent:
        current, seen = memory_id, set()
        while parent.get(current) and current not in seen and not explicit.get(current):
            seen.add(current)
            current = parent[current]
        roots[memory_id] = explicit.get(current) or current
    return roots


def lineage_id(memory_id: str, memory_type: str, version: int, root_id: str) -> str:
    return (
        "lineage_"
        + digest(
            {
                "migration": MIGRATION_NAME,
                "memory_id": memory_id,
                "memory_type": memory_type,
                "version": version,
                "root": root_id,
            }
        )[:48]
    )


def evidence_id(memory_id: str, event_id: str, source_hash: str) -> str:
    return (
        "evidence_"
        + digest(
            {
                "migration": MIGRATION_NAME,
                "memory_id": memory_id,
                "event_id": event_id,
                "source_hash": source_hash,
            }
        )[:48]
    )


def put_lineage(conn: sqlite3.Connection, item: dict[str, Any]) -> bool:
    return (
        conn.execute(
            """INSERT OR IGNORE INTO memory_lineage
        (lineage_id,memory_id,memory_type,parent_memory_id,root_memory_id,semantic_version,evidence_revision,transition_action,created_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                item["lineage_id"],
                item["memory_id"],
                item["memory_type"],
                item["parent_memory_id"],
                item["root_memory_id"],
                item["semantic_version"],
                1,
                item["transition_action"],
                item["created_at"],
            ),
        ).rowcount
        > 0
    )


def put_evidence(conn: sqlite3.Connection, item: dict[str, Any]) -> bool:
    return (
        conn.execute(
            """INSERT OR IGNORE INTO memory_evidence
        (evidence_id,memory_id,memory_type,event_id,source_hash,source_type,excerpt,occurred_at,quality_score,safety_audit_id)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                item["evidence_id"],
                item["memory_id"],
                item["memory_type"],
                item["event_id"],
                item["source_hash"],
                item["source_type"],
                item["excerpt"],
                item["occurred_at"],
                item["quality_score"],
                item["safety_audit_id"],
            ),
        ).rowcount
        > 0
    )


def migrate_domain(
    conn: sqlite3.Connection,
    table: str,
    memory_type: str,
    has_root: bool,
    dry_run: bool,
    counts: Counter,
    undo: dict[str, list[str]],
    owners: dict[str, Counter],
) -> None:
    if not exists(conn, table):
        return
    root_column = "root_id," if has_root else ""
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    extra_column = "extra_payload" if "extra_payload" in columns else "''"
    rows = conn.execute(
        f"SELECT memory_id,user_id,version,parent_id,{root_column} evidences,created_at, "
        f"{extra_column} AS extra_payload FROM {table}"
    ).fetchall()
    roots = legacy_root(rows, has_root)
    for row in rows:
        memory_id, user_id = str(row["memory_id"]), str(row["user_id"] or "default")
        version, parent_id, root_id = (
            max(1, int(row["version"] or 1)),
            str(row["parent_id"] or "") or None,
            roots[memory_id],
        )
        lineage = {
            "lineage_id": lineage_id(memory_id, memory_type, version, root_id),
            "memory_id": memory_id,
            "memory_type": memory_type,
            "parent_memory_id": parent_id,
            "root_memory_id": root_id,
            "semantic_version": version,
            "transition_action": "new" if parent_id is None else "supersede",
            "created_at": str(row["created_at"] or now()),
        }
        counts[f"{memory_type}.lineage.source"] += 1
        owners[memory_type][user_id] += 1
        if dry_run:
            counts[f"{memory_type}.lineage.planned"] += 1
        elif put_lineage(conn, lineage):
            counts[f"{memory_type}.lineage.inserted"] += 1
            undo["lineage"].append(lineage["lineage_id"])
        else:
            counts[f"{memory_type}.lineage.existing"] += 1
        audit_id = str(loads(row["extra_payload"], {}).get("safety", {}).get("audit_id", "") or "")
        for index, evidence in enumerate(loads(row["evidences"], []), 1):
            if not isinstance(evidence, dict):
                counts[f"{memory_type}.evidence.invalid"] += 1
                continue
            event_id = str(evidence.get("event_id") or f"legacy:{memory_id}:{index}")
            excerpt, source_type = (
                str(evidence.get("content") or ""),
                str(evidence.get("source_type") or "tool_result"),
            )
            source_hash = str(
                evidence.get("source_hash")
                or digest(
                    {
                        "memory_id": memory_id,
                        "event_id": event_id,
                        "source_type": source_type,
                        "excerpt": excerpt,
                        "timestamp": evidence.get("timestamp", ""),
                    }
                )
            )
            item = {
                "evidence_id": evidence_id(memory_id, event_id, source_hash),
                "memory_id": memory_id,
                "memory_type": memory_type,
                "event_id": event_id,
                "source_hash": source_hash,
                "source_type": source_type,
                "excerpt": excerpt[:1000],
                "occurred_at": str(evidence.get("timestamp") or now()),
                "quality_score": max(0.0, min(1.0, float(evidence.get("weight", 1.0) or 1.0))),
                "safety_audit_id": audit_id or None,
            }
            counts[f"{memory_type}.evidence.source"] += 1
            if dry_run:
                counts[f"{memory_type}.evidence.planned"] += 1
            elif put_evidence(conn, item):
                counts[f"{memory_type}.evidence.inserted"] += 1
                undo["evidence"].append(item["evidence_id"])
            else:
                counts[f"{memory_type}.evidence.existing"] += 1


def target_owner_counts(conn: sqlite3.Connection) -> dict[str, Counter]:
    result: dict[str, Counter] = defaultdict(Counter)
    for memory_type, table, id_column in (
        ("preference", "preferences", "memory_id"),
        ("knowledge", "knowledge", "memory_id"),
    ):
        if not exists(conn, table):
            continue
        sql = (
            f"SELECT source.user_id AS user_id, COUNT(*) AS count "
            f"FROM memory_lineage target JOIN {table} source "
            f"ON source.{id_column} = target.memory_id "
            "WHERE target.memory_type = ? GROUP BY source.user_id"
        )
        for row in conn.execute(sql, (memory_type,)):
            result[memory_type][str(row["user_id"])] = int(row["count"])
    return result


def write_rollback(path: Path, undo: dict[str, list[str]]) -> None:
    def statement(table: str, column: str, ids: list[str]) -> str:
        if not ids:
            return f"-- No {table} rows were inserted by this run."
        values = ",\n    ".join("'" + item.replace("'", "''") + "'" for item in ids)
        return f"DELETE FROM {table} WHERE {column} IN (\n    {values}\n);"

    path.write_text(
        "\n".join(
            [
                "-- Generated rollback for " + MIGRATION_NAME,
                "BEGIN;",
                statement("memory_evidence", "evidence_id", undo["evidence"]),
                statement("memory_lineage", "lineage_id", undo["lineage"]),
                "DELETE FROM memory_migration_checkpoint "
                f"WHERE migration_name = '{MIGRATION_NAME}';",
                "COMMIT;",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default="")
    parser.add_argument("--rollback-sql", default="")
    args = parser.parse_args()
    db_path = str(Path(args.db).expanduser().resolve())
    bootstrap(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    counts, undo, owners = Counter(), {"lineage": [], "evidence": []}, defaultdict(Counter)
    try:
        checkpoint_schema(conn)
        migrate_domain(conn, "preferences", "preference", True, args.dry_run, counts, undo, owners)
        migrate_domain(conn, "knowledge", "knowledge", False, args.dry_run, counts, undo, owners)
        if args.dry_run:
            conn.rollback()
        else:
            conn.execute(
                "INSERT OR REPLACE INTO memory_migration_checkpoint "
                "(migration_name, source_name, status, detail_hash, updated_at) "
                "VALUES (?, 'complete', 'completed', ?, ?)",
                (MIGRATION_NAME, digest(dict(counts)), now()),
            )
            conn.commit()
        target = target_owner_counts(conn)
        if args.dry_run:
            target = owners
        owner_match = {
            kind: dict(owners[kind]) == dict(target[kind])
            for kind in ("preference", "knowledge")
        }
        report = {
            "migration": MIGRATION_NAME,
            "database": db_path,
            "dry_run": args.dry_run,
            "generated_at": now(),
            "counters": dict(sorted(counts.items())),
            "source_owner_counts": {kind: dict(owners[kind]) for kind in owners},
            "target_lineage_owner_counts": {kind: dict(target[kind]) for kind in target},
            "validation": {
                "owner_scope_match": owner_match,
                "owner_scope_valid": all(owner_match.values()),
                "inserted_hash": digest(undo),
            },
        }
        report_path = (
            Path(args.report)
            if args.report
            else Path(db_path).with_suffix(".migration-report.json")
        )
        rollback_path = (
            Path(args.rollback_sql)
            if args.rollback_sql
            else Path(db_path).with_suffix(".migration-rollback.sql")
        )
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_rollback(rollback_path, undo)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["validation"]["owner_scope_valid"] else 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
