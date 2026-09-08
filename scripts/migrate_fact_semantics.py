"""Idempotently backfill semantic bindings for legacy Knowledge FACT rows.

The command is read-only by default.  Pass ``--apply`` to create entity,
predicate and binding metadata; Knowledge rows and their IDs are never moved.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoryhub.storage.database import Database, FactSemanticRepository, KnowledgeRepository
from memoryhub.core.fact import FactSemanticService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅扫描并输出报告（默认模式）",
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run are mutually exclusive")

    # A dry run must not create a database, schema, ontology rows or bindings.
    # Read the existing SQLite file through its read-only URI instead.
    if not args.apply:
        path = Path(args.db_path)
        if not path.exists():
            print({"facts": 0, "bound": 0, "unresolved": 0,
                   "mode": "dry-run", "reason": "database_not_found"})
            return 0
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        try:
            where = "WHERE status = 'active' AND knowledge_type = 'fact'"
            params: tuple[str, ...] = ()
            if args.user_id:
                where += " AND user_id = ?"
                params = (args.user_id,)
            try:
                rows = connection.execute(
                    f"SELECT subject, predicate, object_value, extra_payload FROM knowledge {where}",
                    params,
                ).fetchall()
            except sqlite3.Error as exc:
                print({"facts": 0, "bound": 0, "unresolved": 0,
                       "mode": "dry-run", "reason": "database_schema_unavailable",
                       "error": type(exc).__name__})
                return 0
        finally:
            connection.close()
        bound = unresolved = missing = 0
        for subject, predicate, object_value, payload in rows:
            try:
                metadata = json.loads(payload or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            semantic = metadata.get("fact_semantic") or {}
            if all(semantic.get(key) for key in ("subject_id", "predicate_id", "object_id")):
                bound += 1
            elif not all(str(value or "").strip() for value in (subject, predicate, object_value)):
                missing += 1
            else:
                unresolved += 1
        print({"facts": len(rows), "bound": bound, "unresolved": unresolved,
               "missing_fields": missing, "mode": "dry-run"})
        return 0

    db = Database(args.db_path)
    db.init_schema()
    knowledge = KnowledgeRepository(db)
    semantic = FactSemanticService(
        knowledge_repo=knowledge, semantic_repo=FactSemanticRepository(db)
    )
    rows = knowledge.list_all(status="active", user_id=args.user_id)
    facts = [item for item in rows
             if getattr(item.knowledge_type, "value", str(item.knowledge_type)) == "fact"]
    bound = 0
    unresolved = 0
    for memory in facts:
        if args.apply:
            if semantic.ensure_memory_binding(memory) is not None:
                bound += 1
            else:
                unresolved += 1
        else:
            unresolved += int(not bool((memory.extra_payload or {}).get("fact_semantic")))
    print({"facts": len(facts), "bound": bound, "unresolved": unresolved,
           "mode": "apply" if args.apply else "dry-run"})
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
