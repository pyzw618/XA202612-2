"""Offline evaluation helpers for knowledge merge thresholds."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from memoryhub.adapter.schemas import KnowledgeMemory
from memoryhub.config import KnowledgeMergeConfig
from memoryhub.core.knowledge.updater import KnowledgeUpdater


def evaluate_cases(path: str | Path, config: KnowledgeMergeConfig | None = None) -> dict:
    cases = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    updater = KnowledgeUpdater(
        write_service=SimpleNamespace(know_repo=None, upsert_memory=lambda memory: None),
        merge_config=config,
    )
    counts = {"equivalent": 0, "ambiguous": 0, "distinct": 0, "total": 0}
    rows = []
    for case in cases:
        left = KnowledgeMemory(**case["left"])
        right = KnowledgeMemory(**case["right"])
        score = updater._similarity(left, right)
        if score >= updater.config.equivalent_threshold:
            predicted = "equivalent"
        elif score >= updater.config.conflict_threshold:
            predicted = "ambiguous"
        else:
            predicted = "distinct"
        counts["total"] += 1
        counts[predicted] += 1
        rows.append({"label": case["label"], "predicted": predicted, "score": score})
    return {"counts": counts, "cases": rows}
