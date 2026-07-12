from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .normalizer import (
    char_jaccard,
    extract_attribute,
    extract_bool_polarity,
    extract_dates,
    extract_entity,
    extract_numeric_values,
    extract_scope,
    extract_symbolic_values,
    has_update_intent,
    normalize_text,
    scopes_compatible,
)
from .schema import ConflictResult, KnowledgeItem


@dataclass
class _NormalizedKnowledge:
    item: KnowledgeItem
    entity: str
    attribute: str
    scope: str
    dates: List[str]
    numbers: list
    polarity: object
    symbols: List[str]
    text: str


class KnowledgeConflictDetector:
    """Hybrid conflict detector for old-new memory updates.

    This is a lightweight baseline meant for edge deployment. It combines
    structured metadata, Chinese keyword extraction, numeric/date comparison,
    status polarity checks, and update-intent rules.
    """

    def __init__(self, same_topic_threshold: float = 0.18) -> None:
        self.same_topic_threshold = same_topic_threshold

    def detect(self, old: KnowledgeItem | dict, new: KnowledgeItem | dict) -> ConflictResult:
        old_item = KnowledgeItem.from_dict(old) if isinstance(old, dict) else old
        new_item = KnowledgeItem.from_dict(new) if isinstance(new, dict) else new
        old_n = self._normalize(old_item)
        new_n = self._normalize(new_item)

        if not self._same_topic(old_n, new_n):
            return ConflictResult(
                label="unrelated",
                action="keep_both",
                confidence=0.92,
                conflict_type="topic_mismatch",
                reasons=[
                    f"主题或属性不同: old=({old_n.entity}/{old_n.attribute}), "
                    f"new=({new_n.entity}/{new_n.attribute})"
                ],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        if not scopes_compatible(old_n.scope, new_n.scope):
            return ConflictResult(
                label="unrelated",
                action="keep_both",
                confidence=0.86,
                conflict_type="scope_mismatch",
                reasons=[f"适用场景不同: old={old_n.scope}, new={new_n.scope}"],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        same_text = normalize_text(old_item.text) == normalize_text(new_item.text)
        same_explicit_value = bool(old_item.value and new_item.value and old_item.value == new_item.value)
        if same_text or same_explicit_value:
            return ConflictResult(
                label="consistent",
                action="merge",
                confidence=0.97,
                conflict_type="same_fact",
                reasons=["文本或结构化值完全一致"],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        checks = [
            self._date_conflict(old_n, new_n),
            self._numeric_conflict(old_n, new_n),
            self._polarity_conflict(old_n, new_n),
            self._symbolic_conflict(old_n, new_n),
        ]
        conflicts = [check for check in checks if check is not None]
        if conflicts:
            conflict_type, reason, confidence = max(conflicts, key=lambda item: item[2])
            return ConflictResult(
                label="conflict",
                action="replace_old" if has_update_intent(new_item.text) or confidence >= 0.82 else "needs_review",
                confidence=confidence,
                conflict_type=conflict_type,
                reasons=[reason],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        if has_update_intent(new_item.text) and self._overlaps(old_n, new_n):
            return ConflictResult(
                label="conflict",
                action="replace_old",
                confidence=0.78,
                conflict_type="explicit_revision",
                reasons=["新知识包含改为/更新为/不再等修订意图，且与旧知识主题重叠"],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        if self._supports(old_n, new_n):
            return ConflictResult(
                label="consistent",
                action="merge",
                confidence=0.83,
                conflict_type="supporting_fact",
                reasons=["新旧知识主题一致，且未发现日期、数值、状态或枚举冲突"],
                old_id=old_item.id or None,
                new_id=new_item.id or None,
            )

        return ConflictResult(
            label="unrelated",
            action="keep_both",
            confidence=0.72,
            conflict_type="weak_overlap",
            reasons=["仅有弱文本重叠，未达到同一事实判定标准"],
            old_id=old_item.id or None,
            new_id=new_item.id or None,
        )

    def _normalize(self, item: KnowledgeItem) -> _NormalizedKnowledge:
        text = item.text
        return _NormalizedKnowledge(
            item=item,
            entity=item.entity or extract_entity(text),
            attribute=item.attribute or extract_attribute(text),
            scope=item.scope or extract_scope(text),
            dates=extract_dates(text),
            numbers=extract_numeric_values(item.value or text),
            polarity=extract_bool_polarity(text),
            symbols=extract_symbolic_values(item.value or text),
            text=normalize_text(text),
        )

    def _same_topic(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> bool:
        if old.entity and new.entity and old.entity != new.entity:
            if old.attribute and new.attribute and old.attribute == new.attribute:
                return char_jaccard(old.item.text, new.item.text) >= 0.32
            return False
        if old.attribute and new.attribute and old.attribute != new.attribute:
            return char_jaccard(old.item.text, new.item.text) >= 0.45
        if old.entity and new.entity:
            return True
        if old.attribute and new.attribute:
            return True
        return char_jaccard(old.item.text, new.item.text) >= self.same_topic_threshold

    def _overlaps(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> bool:
        return self._same_topic(old, new) or char_jaccard(old.item.text, new.item.text) >= 0.28

    def _supports(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> bool:
        if old.attribute and new.attribute and old.attribute == new.attribute:
            return True
        if old.entity and new.entity and old.entity == new.entity:
            return char_jaccard(old.item.text, new.item.text) >= 0.24
        return char_jaccard(old.item.text, new.item.text) >= 0.36

    def _date_conflict(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> Tuple[str, str, float] | None:
        if not old.dates or not new.dates:
            return None
        if set(old.dates) == set(new.dates):
            return None
        return (
            "date_conflict",
            f"同一主题日期不同: old={old.dates}, new={new.dates}",
            0.91,
        )

    def _numeric_conflict(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> Tuple[str, str, float] | None:
        if not old.numbers or not new.numbers:
            return None
        if old.dates and new.dates and set(old.dates) == set(new.dates):
            return None
        for left in old.numbers:
            for right in new.numbers:
                if left.normalized_unit() != right.normalized_unit():
                    continue
                if abs(left.normalized_value() - right.normalized_value()) < 1e-9:
                    continue
                if self._number_relevant(old.attribute, new.attribute):
                    return (
                        "numeric_conflict",
                        f"同一指标数值或约束不同: old={left.raw}, new={right.raw}",
                        0.88,
                    )
        return None

    def _number_relevant(self, old_attr: str, new_attr: str) -> bool:
        numeric_attrs = {
            "response_latency",
            "recall_rate",
            "accuracy",
            "deadline",
            "version",
            "support_status",
            "count_limit",
        }
        return old_attr in numeric_attrs or new_attr in numeric_attrs

    def _polarity_conflict(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> Tuple[str, str, float] | None:
        if old.polarity is None or new.polarity is None:
            return None
        if old.polarity == new.polarity:
            return None
        return (
            "polarity_conflict",
            f"状态极性相反: old={old.polarity}, new={new.polarity}",
            0.9,
        )

    def _symbolic_conflict(self, old: _NormalizedKnowledge, new: _NormalizedKnowledge) -> Tuple[str, str, float] | None:
        if not old.symbols or not new.symbols:
            return None
        old_set = set(old.symbols)
        new_set = set(new.symbols)
        if old_set == new_set or old_set.issubset(new_set) or new_set.issubset(old_set):
            return None
        if self._symbol_groups_conflict(old_set, new_set):
            return (
                "symbolic_value_conflict",
                f"同一属性枚举值不同: old={sorted(old_set)}, new={sorted(new_set)}",
                0.84,
            )
        return None

    def _symbol_groups_conflict(self, old_set: set[str], new_set: set[str]) -> bool:
        groups = [
            {"端侧", "云端", "本地"},
            {"SQLite", "PostgreSQL", "Milvus", "Chroma"},
            {"BM25", "FAISS", "HNSW", "向量检索", "关键词检索", "混合检索"},
            {"表格", "Markdown", "JSON", "中文", "英文", "简洁", "详细"},
            {"V10", "V11"},
            {"API模型", "本地模型"},
        ]
        for group in groups:
            if old_set & group and new_set & group and (old_set & group) != (new_set & group):
                return True
        return False
