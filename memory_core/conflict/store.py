from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List

from .detector import KnowledgeConflictDetector
from .normalizer import char_jaccard, normalize_text
from .schema import ConflictResult, KnowledgeItem


@dataclass
class StoredMemory:
    item: KnowledgeItem
    active: bool = True
    superseded_by: str = ""


@dataclass
class AddReport:
    new_item: KnowledgeItem
    conflicts: List[ConflictResult] = field(default_factory=list)
    merged: List[str] = field(default_factory=list)
    kept: bool = True

    def to_dict(self) -> dict:
        return {
            "new_item": self.new_item.to_dict(),
            "conflicts": [result.to_dict() for result in self.conflicts],
            "merged": self.merged,
            "kept": self.kept,
        }


class MemoryStore:
    """Small in-memory store for conflict-resolution experiments."""

    def __init__(self, detector: KnowledgeConflictDetector | None = None) -> None:
        self.detector = detector or KnowledgeConflictDetector()
        self._items: Dict[str, StoredMemory] = {}

    def add(self, item: KnowledgeItem | dict, auto_replace: bool = True) -> AddReport:
        new_item = KnowledgeItem.from_dict(item) if isinstance(item, dict) else item
        if not new_item.id:
            new_item.id = f"mem_{uuid.uuid4().hex[:10]}"
        report = AddReport(new_item=new_item)
        for stored in list(self._items.values()):
            if not stored.active:
                continue
            result = self.detector.detect(stored.item, new_item)
            if result.label == "conflict":
                report.conflicts.append(result)
                if auto_replace and result.action == "replace_old":
                    stored.active = False
                    stored.superseded_by = new_item.id
            elif result.label == "consistent":
                report.merged.append(stored.item.id)
        self._items[new_item.id] = StoredMemory(item=new_item)
        return report

    def forget(self, query: str, threshold: float = 0.25) -> List[str]:
        """Forget active memories that match a natural-language query."""

        forgotten: List[str] = []
        q = normalize_text(query)
        for memory_id, stored in self._items.items():
            if not stored.active:
                continue
            score = char_jaccard(q, stored.item.text)
            if q in normalize_text(stored.item.text) or score >= threshold:
                stored.active = False
                stored.superseded_by = "__forgotten__"
                forgotten.append(memory_id)
        return forgotten

    def active_items(self) -> Iterable[KnowledgeItem]:
        for stored in self._items.values():
            if stored.active:
                yield stored.item

    def all_items(self) -> Iterable[StoredMemory]:
        return self._items.values()

    def save_jsonl(self, path: str | Path) -> None:
        output = Path(path)
        with output.open("w", encoding="utf-8") as f:
            for stored in self._items.values():
                row = stored.item.to_dict()
                row["active"] = stored.active
                row["superseded_by"] = stored.superseded_by
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
