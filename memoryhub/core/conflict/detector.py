"""Deterministic conflict detection for preference and knowledge memories.

注意：生产写入链路实际使用的是 ``core/preference/updater.py`` 与
``core/knowledge/updater.py`` 内的冲突检测；本模块是并行的确定性实现，
目前仅被测试引用，两者判定规则存在差异（例如本模块的兜底判定额外要求
token 重合度，见 ``_semantic_contradiction``）。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from memoryhub.adapter.schemas import ConflictRecord, KnowledgeMemory, PreferenceMemory


class ConflictDetector:
    """Detect owner- and scope-local semantic conflicts without requiring an LLM."""

    def __init__(self, llm_client=None, *, similarity_threshold: float = 0.55) -> None:
        self.llm_client = llm_client
        self.similarity_threshold = max(0.0, min(1.0, similarity_threshold))

    def check_preference(
        self, new_pref: PreferenceMemory, existing: list[PreferenceMemory]
    ) -> ConflictRecord | None:
        candidates = self._find_similar_preferences(new_pref, existing)
        new_target = str(new_pref.payload.get("target", "")).strip()
        new_value = str(new_pref.payload.get("value", "")).strip()
        for old in candidates:
            old_target = str(old.payload.get("target", "")).strip()
            old_value = str(old.payload.get("value", "")).strip()
            structured_conflict = bool(
                new_target and old_target == new_target and new_value != old_value
            )
            fallback_conflict = (
                not new_target
                and not old_target
                and self._semantic_contradiction(self._text(old), self._text(new_pref))
            )
            if structured_conflict or fallback_conflict:
                return ConflictRecord(
                    user_id=new_pref.user_id,
                    old_memory_id=old.memory_id,
                    new_memory_id=new_pref.memory_id,
                    memory_type="preference",
                    old_content=self._text(old),
                    new_content=self._text(new_pref),
                    conflict_field="text/payload",
                    reason="same preference type and overlapping scope with contradictory values",
                )
        return None

    def check_knowledge(
        self, new_know: KnowledgeMemory, existing: list[KnowledgeMemory]
    ) -> ConflictRecord | None:
        new_type = str(
            getattr(new_know.knowledge_type, "value", new_know.knowledge_type)
        )
        new_text = " ".join([new_know.name, new_know.content, *new_know.steps])
        for old in existing:
            if old.user_id != new_know.user_id:
                continue
            old_type = str(getattr(old.knowledge_type, "value", old.knowledge_type))
            if old_type != new_type or not self._is_same_scope(
                old.scope, new_know.scope
            ):
                continue
            old_text = " ".join([old.name, old.content, *old.steps])
            similarity = self._similarity(old_text, new_text)
            if (
                similarity >= self.similarity_threshold
                and self._semantic_contradiction(old_text, new_text)
            ):
                return ConflictRecord(
                    user_id=new_know.user_id,
                    old_memory_id=old.memory_id,
                    new_memory_id=new_know.memory_id,
                    memory_type="knowledge",
                    old_content=old_text,
                    new_content=new_text,
                    conflict_field="content/steps",
                    reason=(
                        "same knowledge scope with contradictory procedure "
                        f"(similarity={similarity:.3f})"
                    ),
                )
        return None

    def _is_same_scope(self, scope_a, scope_b) -> bool:
        for field in ("scene", "task_type", "app"):
            left = getattr(scope_a, field, "")
            right = getattr(scope_b, field, "")
            if left and right and left not in ("*", right) and right not in ("*", left):
                return False
        return True

    def _semantic_contradiction(self, text_a: str, text_b: str) -> bool:
        a = self._tokens(text_a)
        b = self._tokens(text_b)
        if not a or not b:
            return False
        if a == b:
            return False
        neg_a = self._has_negation(text_a)
        neg_b = self._has_negation(text_b)
        shared = len(a & b) / max(1, len(a | b))
        return shared >= self.similarity_threshold and neg_a != neg_b

    def _find_similar_preferences(
        self, pref: PreferenceMemory, candidates: list[PreferenceMemory]
    ) -> list[PreferenceMemory]:
        result = []
        for candidate in candidates:
            if candidate.user_id != pref.user_id:
                continue
            if candidate.preference_type != pref.preference_type:
                continue
            if (
                self._is_same_scope(candidate.scope, pref.scope)
                or candidate.is_global
                or pref.is_global
            ):
                result.append(candidate)
        return result

    @staticmethod
    def _text(memory) -> str:
        payload = getattr(memory, "payload", {}) or {}
        return " ".join([str(getattr(memory, "text", "")), str(payload)])

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return set(re.findall(r"[0-9a-zA-Z一-龥]{2,}", cls._normalize(text)))

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        return SequenceMatcher(
            None, cls._normalize(left), cls._normalize(right)
        ).ratio()

    @staticmethod
    def _has_negation(text: str) -> bool:
        return bool(
            re.search(r"\b(?:not|never|no|禁止|不要|不能|不应|拒绝|否)\b", text.lower())
        )
