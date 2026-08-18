#!/usr/bin/env python3
"""将存量 facts 表迁移为 knowledge(FACT)（REFACTOR_PLAN_V2 §4.8.8）。

facts/entities/predicates 与 knowledge 表共存于同一 SQLite 文件（app.py 用同一 db_path）。
迁移规则：
  - subject/predicate 解析为规范名（entities/predicates 表，回退原始 ID）
  - 产出 KnowledgeMemory(knowledge_type=FACT)，经 KnowledgeUpdater 写入（复用 §4.8.5 冲突 matcher）
  - memory_id 派生自原 fact_id → 幂等：重跑同事实被去重/强化，不产生新行

用法:
    python scripts/migrate_facts_to_knowledge.py --db data/memoryhub.db
    python scripts/migrate_facts_to_knowledge.py --db data/memoryhub.db --dry-run
    python scripts/migrate_facts_to_knowledge.py --db data/memoryhub.db --user u1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

try:  # Windows GBK 控制台输出中文需显式 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.adapter.schemas import (  # noqa: E402
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
)
from memoryhub.core.fact.store import FactStore  # noqa: E402
from memoryhub.core.knowledge.updater import KnowledgeUpdater  # noqa: E402
from memoryhub.core.memory_write import MemoryWriteService  # noqa: E402
from memoryhub.storage.database import (  # noqa: E402
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)


def _canonical_entity(store: FactStore, entity_id: str) -> tuple[str, str]:
    ent = store.get_entity(entity_id)
    if ent is not None:
        return ent.canonical_name, ent.entity_type
    return entity_id, "Other"


def _canonical_predicate(store: FactStore, pred_id: str) -> tuple[str, bool]:
    pred = store.get_predicate(pred_id)
    if pred is not None:
        return pred.canonical_name, bool(pred.single_value)
    return pred_id, True


def _fact_evidences(store: FactStore, fact_id: str, user_id: str) -> list[Evidence]:
    out: list[Evidence] = []
    for row in store.list_fact_evidence(fact_id, user_id):
        out.append(
            Evidence(
                event_id=str(row.get("event_id") or ""),
                evidence_id=str(row.get("evidence_id") or ""),
                content=str(row.get("source_text") or ""),
                source_id=str(row.get("source_id") or ""),
                source_type=str(row.get("source_type") or "tool_result"),
            )
        )
    return out


def migrate(db_path: str, *, user: str = "", dry_run: bool = False) -> dict:
    store = FactStore(db_path)
    database = Database(db_path)
    database.init_schema()
    pref_repo = PreferenceRepository(database)
    know_repo = KnowledgeRepository(database)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    updater = KnowledgeUpdater(write_service=writer)

    facts = store.list_facts(status="active", user_id=user or None, limit=100000)
    planned = 0
    written = 0
    skipped = 0
    for fact in facts:
        subj, obj_type = _canonical_entity(store, fact.subject_id)
        pred, single_value = _canonical_predicate(store, fact.predicate_id)
        object_type = "Other"
        if fact.object_id and fact.object_id.startswith("entity:"):
            _n, object_type = _canonical_entity(store, fact.object_id)
        memory = KnowledgeMemory(
            memory_id=f"factmig_{hashlib.sha256(fact.fact_id.encode()).hexdigest()[:8]}",
            user_id=fact.user_id,
            knowledge_type=KnowledgeType.FACT,
            subject=subj,
            predicate=pred,
            object_value=fact.object_value,
            object_type=object_type,
            single_value=single_value,
            content=f"{subj} {pred} {fact.object_value}".strip(),
            confidence=float(fact.confidence),
            evidences=_fact_evidences(store, fact.fact_id, fact.user_id),
        )
        planned += 1
        if dry_run:
            continue
        try:
            updater.add(memory)
            written += 1
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            print(f"[SKIP] {fact.fact_id}: {exc}")

    store.close()
    database.close()
    return {
        "planned": planned,
        "written": written,
        "skipped": skipped,
        "dry_run": bool(dry_run),
        "user": user or "(all)",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="memoryhub.db 路径（facts 与 knowledge 同库）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--user", default="", help="仅迁移指定 user（默认全部）")
    parser.add_argument("--report", action="store_true", help="输出 migrate_facts_report.json")
    args = parser.parse_args()

    report = migrate(args.db, user=args.user, dry_run=args.dry_run)
    print(
        f"迁移报告: planned={report['planned']} written={report['written']} "
        f"skipped={report['skipped']} dry_run={report['dry_run']} user={report['user']}"
    )
    if args.report:
        with open("migrate_facts_report.json", "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
