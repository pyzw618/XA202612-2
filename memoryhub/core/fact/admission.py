"""
事实准入策略。

当前模块只保存客观事实，不保存偏好、愿望、建议、假设和一次性指令。
作用域只记录调用方显式提示；当前策略不会自行决定全局或项目事实。
"""

import re
from typing import Optional

from .models import FactAdmissionDecision, MemoryScope, RawTriple


class FactAdmissionPolicy:
    """可替换的保守规则策略；后续可接入 LLM 分类器而不影响管线接口。"""

    _PREFERENCE_PATTERNS = (
        r"喜欢", r"偏好", r"希望", r"习惯", r"倾向", r"更愿意",
        r"prefer", r"preference", r"would like",
    )
    _HYPOTHETICAL_PATTERNS = (
        r"如果", r"假如", r"可能", r"也许", r"建议", r"最好", r"考虑",
        r"if\b", r"maybe", r"might", r"should",
    )
    _TEMPORARY_PATTERNS = (
        r"这次", r"本次", r"今天先", r"暂时", r"临时", r"先用",
        r"for now", r"this time", r"temporarily",
    )

    @staticmethod
    def _contains(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def evaluate(
        self,
        triple: RawTriple,
        project_id: Optional[str] = None,
        scope_hint: Optional[str] = None,
    ) -> FactAdmissionDecision:
        evidence = triple.evidence or ""
        combined = " ".join((triple.predicate_text, evidence))

        if self._contains(combined, self._PREFERENCE_PATTERNS):
            return FactAdmissionDecision(
                is_fact=False,
                should_remember=False,
                category="preference",
                confidence=0.95,
                reason="检测到偏好或习惯表达；当前模块只保存事实",
            )

        if self._contains(combined, self._HYPOTHETICAL_PATTERNS):
            return FactAdmissionDecision(
                is_fact=False,
                should_remember=False,
                category="hypothetical",
                confidence=0.9,
                reason="检测到假设、建议或不确定表达",
            )

        if self._contains(combined, self._TEMPORARY_PATTERNS):
            return FactAdmissionDecision(
                is_fact=True,
                should_remember=False,
                category="temporary_fact",
                confidence=0.85,
                reason="事实具有明显的一次性或临时语义",
            )

        suggested_scope = None
        if scope_hint is not None:
            if scope_hint not in MemoryScope.choices():
                raise ValueError(f"不支持的 scope_hint: {scope_hint}")
            suggested_scope = scope_hint

        if suggested_scope == MemoryScope.PROJECT.value and not project_id:
            return FactAdmissionDecision(
                is_fact=True,
                should_remember=True,
                suggested_scope=None,
                category="fact",
                confidence=0.7,
                reason="候选事实可能属于项目作用域，但缺少 project_id",
            )

        return FactAdmissionDecision(
            is_fact=True,
            should_remember=True,
            suggested_scope=suggested_scope,
            category="fact",
            confidence=max(0.5, triple.confidence),
            reason="检测到明确陈述的客观事实",
        )
