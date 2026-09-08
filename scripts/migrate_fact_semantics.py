"""Idempotently backfill semantic bindings for legacy Knowledge FACT rows.

The command is read-only by default.  Pass ``--apply`` to create entity,
predicate and binding metadata; Knowledge rows and their IDs are never moved.
"""

from __future__ import annotations

import argparse

from memoryhub.storage.database import Database, FactSemanticRepository, KnowledgeRepository
from memoryhub.core.fact import FactSemanticService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

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
