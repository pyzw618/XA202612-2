"""Query Understanding and 7-class Intent Router.

The router is intentionally rule-based and deterministic so that retrieval
behaviour is explainable and reproducible.  A optional lightweight LLM scorer
may be layered on top, but the rule engine always provides a fail-closed
fallback and the final reason string.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType, RetrievalIntent


@dataclass(frozen=True, slots=True)
class RoutedIntent:
    """Interpreted retrieval intent with explainable targets."""

    intent: RetrievalIntent
    confidence: float = 0.0
    target_layers: list[LifecycleLayer] = field(default_factory=list)
    target_types: list[MemoryType] = field(default_factory=list)
    reason: str = ""
    mixed_intents: list[tuple[RetrievalIntent, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")


class IntentRouter:
    """Rule-based 7-class router with optional LLM scoring and degrade-to-MIXED.

    The router never raises for ordinary queries; ambiguous or empty inputs are
    returned as ``MIXED`` with low confidence and the broadest safe target set.
    """

    # Confidence bands: the caller can override the threshold if evaluation
    # shows a different operating point is needed.
    HIGH_CONFIDENCE_THRESHOLD: float = 0.70
    MIXED_THRESHOLD: float = 0.40

    _INTENT_RULES: dict[RetrievalIntent, list[str]] = {
        RetrievalIntent.CURRENT_STATE: [
            r"当前(?:的)?(?:任务|步骤|状态|目标)(?:是(?:什么|啥))?",

            r"现在(?:该|要|需要)做(?:什么|啥)",
            r"(?:current|ongoing)\s+(?:task|step|goal|state)(?:\s+is)?",
            r"what['\u2019]s?\s+(?:next|my\s+current)",
            r"^(?:todo|待办|下一步)\b",
        ],
        RetrievalIntent.TASK_HISTORY: [
            r"(?:任务|这个任务).*?(?:历史|做过什么|进展)",
            r"(?:之前|上次|以前)(?:做|处理|执行)过",
            r"^(?:task|episode|session)\s+history\b",
            r"^what\s+(?:did|have)\s+i\s+(?:done|worked\s+on)",
        ],
        RetrievalIntent.PREFERENCE: [
            r"(?:偏好|喜欢|总是|通常|默认)(?:用|使用|选|选择)",
            r"^(?:prefer|like\s+to|always|default)\s+(?:use|choose|want)",
            r"(?:format|style|样式|格式|排版)(?:偏好|设置|选择)?",
            r"(?:用|使用)\s*(?:docx|markdown|pdf|word|excel|ppt)\b",
        ],
        RetrievalIntent.SEMANTIC_FACT: [
            r"^(?:什么是|什么是|怎么|如何|为什么|在哪里|是谁)",
            r"^(?:what|who|where|when|why|how)\b.*\?",
            r"^(?:define|explain|meaning\s+of)\b",
        ],
        RetrievalIntent.PROCEDURE: [
            r"(?:步骤|流程|过程|procedure|workflow|steps)",
            r"^(?:how\s+to|step\s+by\s+step)\b",
            r"^(?:怎么|如何)操作",
        ],
        RetrievalIntent.EXPERIENCE: [
            r"(?:类似|相似|相同|之前遇到|曾经).*?(?:情况|问题|案例|经验)",
            r"^(?:similar\s+case|past\s+experience|previous\s+incident)\b",
            r"^(?:经验|案例|教训)",
        ],
    }

    _LAYER_TARGETS: dict[RetrievalIntent, list[LifecycleLayer]] = {
        RetrievalIntent.CURRENT_STATE: [LifecycleLayer.WORKING],
        RetrievalIntent.TASK_HISTORY: [LifecycleLayer.EPISODE],
        RetrievalIntent.PREFERENCE: [LifecycleLayer.LONG_TERM],
        RetrievalIntent.SEMANTIC_FACT: [LifecycleLayer.LONG_TERM],
        RetrievalIntent.PROCEDURE: [LifecycleLayer.LONG_TERM],
        RetrievalIntent.EXPERIENCE: [LifecycleLayer.LONG_TERM],
    }

    _TYPE_TARGETS: dict[RetrievalIntent, list[MemoryType]] = {
        RetrievalIntent.CURRENT_STATE: [],
        RetrievalIntent.TASK_HISTORY: [],
        RetrievalIntent.PREFERENCE: [MemoryType.PREFERENCE],
        RetrievalIntent.SEMANTIC_FACT: [MemoryType.SEMANTIC],
        RetrievalIntent.PROCEDURE: [MemoryType.PROCEDURAL],
        RetrievalIntent.EXPERIENCE: [MemoryType.EPISODIC],
    }

    def __init__(
        self,
        *,
        llm_scorer: Callable[[str], tuple[RetrievalIntent, float]] | None = None,
        high_confidence: float | None = None,
        mixed_threshold: float | None = None,
    ) -> None:
        self.llm_scorer = llm_scorer
        self.high_confidence = high_confidence or self.HIGH_CONFIDENCE_THRESHOLD
        self.mixed_threshold = mixed_threshold or self.MIXED_THRESHOLD
        self._compiled: dict[RetrievalIntent, list[re.Pattern[str]]] = {
            intent: [re.compile(p, re.IGNORECASE) for p in patterns]
            for intent, patterns in self._INTENT_RULES.items()
        }

    def route(
        self,
        query: str,
        *,
        task_id: str = "",
        current_goal: str = "",
        current_step: str = "",
        active_constraints: list[str] | None = None,
        intent_hint: RetrievalIntent | None = None,
        scope_level: MemoryScope | None = None,
    ) -> RoutedIntent:
        """Score the query and return an explainable intent decision."""
        scores = self._rule_scores(query, current_goal=current_goal, current_step=current_step)

        if intent_hint is not None:
            # A caller-supplied hint is strong evidence; use it as the primary
            # intent while still exposing the rule scores for diagnostics.
            return self._build(
                intent_hint,
                1.0,
                f"intent_hint={intent_hint.value} overrides rule scores",
            )

        if self.llm_scorer is not None:
            try:
                llm_intent, llm_confidence = self.llm_scorer(query)
                if llm_confidence > self.high_confidence:
                    scores[llm_intent] = max(scores.get(llm_intent, 0.0), llm_confidence)
            except Exception:
                # Fail-closed: rule scores remain authoritative.
                pass

        if scope_level is MemoryScope.TASK and task_id and not query:
            scores[RetrievalIntent.CURRENT_STATE] = max(
                scores.get(RetrievalIntent.CURRENT_STATE, 0.0), self.high_confidence
            )

        if not query.strip() and task_id:
            # Empty query with a task context is a current-state request.
            return self._build(
                RetrievalIntent.CURRENT_STATE,
                1.0,
                "empty query with task_id implies current state",
            )

        return self._resolve_intent(scores, "rule-based query understanding")

    def _rule_scores(
        self,
        query: str,
        *,
        current_goal: str = "",
        current_step: str = "",
    ) -> dict[RetrievalIntent, float]:
        """Return raw rule scores for each of the six non-MIXED intents."""
        text = f"{query} {current_goal} {current_step}".strip().lower()
        scores: dict[RetrievalIntent, float] = {}
        for intent, patterns in self._compiled.items():
            matches = sum(1 for pattern in patterns if pattern.search(text))
            # Normalise by pattern count so no intent dominates merely by having
            # more patterns.  Zero matches produce zero score; one strong match
            # crosses the high-confidence band; additional matches add clarity.
            score = min(1.0, 0.75 + 0.12 * matches) if matches else 0.0
            scores[intent] = score
        return scores

    def _resolve_intent(
        self,
        scores: dict[RetrievalIntent, float],
        reason: str,
    ) -> RoutedIntent:
        sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if not sorted_scores or max((s for _, s in scores.items()), default=0.0) == 0.0:
            return self._mixed(
                scores,
                reason="no intent signal; default to MIXED",
                confidence=0.0,
            )

        top_intent, top_score = sorted_scores[0]
        second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
        if top_score >= self.high_confidence and second_score < self.high_confidence:
            # Clear single intent: runner-up is below the high-confidence band.
            return self._build(top_intent, top_score, f"{reason}; dominant pattern")

        if top_score >= self.high_confidence and second_score >= self.high_confidence:
            # Two or more confident intents; only resolve if the leader is well ahead.
            if top_score - second_score >= 0.15:
                return self._build(top_intent, top_score, f"{reason}; leading intent")
            return self._mixed(
                scores,
                reason=f"{reason}; top intents {top_intent.value} and runner-up are close",
            )

        if top_score >= self.mixed_threshold:
            # Ambiguous but some signal; emit MIXED with the ranked sub-intents.
            return self._mixed(scores, reason=f"{reason}; no dominant intent")

        return self._mixed(
            scores,
            reason=f"{reason}; confidence below threshold",
            confidence=top_score,
        )

    def _mixed(
        self,
        scores: dict[RetrievalIntent, float],
        *,
        reason: str,
        confidence: float | None = None,
    ) -> RoutedIntent:
        sorted_scores = sorted(
            ((intent, score) for intent, score in scores.items() if score > 0),
            key=lambda item: item[1],
            reverse=True,
        )
        mixed_confidence = confidence if confidence is not None else 0.5
        # MIXED targets the union of the top sub-intents so retrieval can still
        # proceed; budget/rerank later stages narrow the result set.
        top_intents = [intent for intent, _ in sorted_scores[:3]]
        layers = list(
            dict.fromkeys(
                layer
                for intent in top_intents
                for layer in self._LAYER_TARGETS.get(intent, [])
            )
        )
        types = list(
            dict.fromkeys(
                memory_type
                for intent in top_intents
                for memory_type in self._TYPE_TARGETS.get(intent, [])
            )
        )
        if not layers:
            layers = [LifecycleLayer.WORKING, LifecycleLayer.EPISODE, LifecycleLayer.LONG_TERM]
        return RoutedIntent(
            intent=RetrievalIntent.MIXED,
            confidence=mixed_confidence,
            target_layers=layers,
            target_types=types or list(MemoryType),
            reason=reason,
            mixed_intents=sorted_scores,
        )

    def _build(
        self,
        intent: RetrievalIntent,
        confidence: float,
        reason: str,
    ) -> RoutedIntent:
        return RoutedIntent(
            intent=intent,
            confidence=round(confidence, 4),
            target_layers=list(self._LAYER_TARGETS.get(intent, [])),
            target_types=list(self._TYPE_TARGETS.get(intent, [])),
            reason=f"{reason}; intent={intent.value}",
        )

    @classmethod
    def supported_intents(cls) -> list[RetrievalIntent]:
        return list(cls._INTENT_RULES) + [RetrievalIntent.MIXED]


__all__ = ["IntentRouter", "RoutedIntent"]
