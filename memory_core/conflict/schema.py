from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


ConflictLabel = Literal["conflict", "consistent", "unrelated"]
MemoryAction = Literal["replace_old", "merge", "keep_both", "ignore", "needs_review"]


@dataclass
class KnowledgeItem:
    """A structured memory record.

    The detector can work with raw text only, but accuracy is much better when
    upstream extraction supplies entity/attribute/scope metadata.
    """

    text: str
    id: str = ""
    entity: str = ""
    attribute: str = ""
    value: str = ""
    scope: str = ""
    source: str = ""
    timestamp: str = ""
    confidence: float = 1.0
    meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeItem":
        known = {
            "text",
            "id",
            "entity",
            "attribute",
            "value",
            "scope",
            "source",
            "timestamp",
            "confidence",
            "meta",
        }
        meta = dict(data.get("meta") or {})
        for key, value in data.items():
            if key not in known:
                meta[key] = value
        return cls(
            text=str(data.get("text", "")),
            id=str(data.get("id", "")),
            entity=str(data.get("entity", "")),
            attribute=str(data.get("attribute", "")),
            value=str(data.get("value", "")),
            scope=str(data.get("scope", "")),
            source=str(data.get("source", "")),
            timestamp=str(data.get("timestamp", "")),
            confidence=float(data.get("confidence", 1.0)),
            meta=meta,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "entity": self.entity,
            "attribute": self.attribute,
            "value": self.value,
            "scope": self.scope,
            "source": self.source,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "meta": self.meta,
        }


@dataclass
class ConflictResult:
    label: ConflictLabel
    action: MemoryAction
    confidence: float
    conflict_type: str = ""
    reasons: List[str] = field(default_factory=list)
    old_id: Optional[str] = None
    new_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "action": self.action,
            "confidence": round(self.confidence, 4),
            "conflict_type": self.conflict_type,
            "reasons": self.reasons,
            "old_id": self.old_id,
            "new_id": self.new_id,
        }
