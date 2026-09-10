"""Deterministic confidence scoring for extracted and evolved knowledge."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from memoryhub.adapter.schemas import ConflictDecision
from memoryhub.core.memory.confidence import (
    ConfidenceFactors,
    UnifiedConfidenceCalculator,
)


@dataclass(frozen=True, slots=True)
class KnowledgeConfidenceFactors:
    event_quality: float
    completion: float
    structure: float
    evidence: float
    outcome: float
    consistency: float

    def normalized(self) -> "KnowledgeConfidenceFactors":
        return KnowledgeConfidenceFactors(
            *(
                _clamp(value)
                for value in (
                    self.event_quality,
                    self.completion,
                    self.structure,
                    self.evidence,
                    self.outcome,
                    self.consistency,
                )
            )
        )


class KnowledgeConfidenceCalculator:
    """Score quality without allowing one strong factor to hide a weak chain."""

    _WEIGHTS = (0.28, 0.20, 0.20, 0.14, 0.10, 0.08)

    def score(
        self, factors: KnowledgeConfidenceFactors, *, ceiling: float = 0.97
    ) -> float:
        """Compatibility facade over the shared four-factor confidence formula."""
        values = factors.normalized()
        shared = ConfidenceFactors(
            source=min(1.0, 0.60 + 0.25 * values.completion + 0.15 * values.outcome),
            quality=(values.event_quality + values.structure + values.consistency)
            / 3.0,
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                1 if values.evidence < 0.55 else (2 if values.evidence < 0.80 else 3)
            ),
            freshness=values.outcome,
        )
        return min(
            ceiling,
            UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge"),
        )

    def from_memory(self, memory: Any) -> float:
        """Recompute one knowledge record's confidence from the record itself.

        写路径唯一入口：请求体 / raw payload 里的 confidence 一律视为占位值。
        输入只有记忆自身的证据链、复用计数与类型化结构完整度，因此同一条记录
        无论由哪个调用方写入，落库值都可复现，且不同记录之间真正可比。
        """
        evidences = list(getattr(memory, "evidences", []) or [])
        weights = [
            1.0 if (raw := getattr(item, "weight", 1.0)) is None else _clamp(raw)
            for item in evidences
        ]
        # 事件质量取证据链平均权重：与偏好侧一致，避免单条强证据掩盖弱链。
        event_quality = sum(weights) / len(weights) if weights else 0.0

        total = max(0, int(getattr(memory, "total_count", 0) or 0))
        successes = min(max(0, int(getattr(memory, "success_count", 0) or 0)), total)
        # 未复用过的记录 = 0.5；随成功复用次数上升，与 merge_score 同源。
        reliability = (successes + 1.0) / (total + 2.0)

        completion = 1.0 if self._has_content(memory) else 0.5
        shared = ConfidenceFactors(
            source=min(1.0, 0.60 + 0.25 * completion + 0.15 * reliability),
            quality=(
                event_quality
                + self._structure_from_memory(memory)
                + self._consistency(evidences)
            )
            / 3.0,
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                len(evidences)
            ),
            freshness=reliability,
        )
        return min(
            0.97,
            UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge"),
        )

    @staticmethod
    def _has_content(memory: Any) -> bool:
        return any(
            str(getattr(memory, field, "") or "").strip()
            for field in ("name", "content", "template_body")
        )

    @staticmethod
    def _structure_from_memory(memory: Any) -> float:
        """类型化结构完整度：workflow/case 看步骤与工具，template 看正文，fact 看 S/P/O。"""
        kind = str(getattr(getattr(memory, "knowledge_type", ""), "value", ""))
        steps = len(getattr(memory, "steps", []) or [])
        tools = len(getattr(memory, "tools", []) or [])
        if kind == "template":
            body = len(str(getattr(memory, "template_body", "") or "").strip())
            return min(1.0, 0.45 + 0.30 * min(1.0, body / 240.0) + 0.05 * tools)
        if kind == "fact":
            filled = (
                bool(str(getattr(memory, "subject", "") or "").strip()),
                bool(str(getattr(memory, "predicate", "") or "").strip()),
                bool(str(getattr(memory, "object_value", "") or "").strip()),
            )
            return min(
                1.0,
                0.50 + 0.20 * int(filled[0]) + 0.15 * int(filled[1]) + 0.15 * int(filled[2]),
            )
        return min(1.0, 0.45 + 0.10 * steps + 0.05 * tools)

    @staticmethod
    def _consistency(evidences: list[Any]) -> float:
        """非 OVERRIDE 证据占比（与偏好侧 _factor_consistency 同源，但保持 [0,1] 量纲）。"""
        if not evidences:
            return 1.0
        positive = sum(
            1
            for item in evidences
            if getattr(item, "decision", None) != ConflictDecision.OVERRIDE
        )
        return positive / len(evidences)

    def merge_score(
        self,
        *,
        existing_confidence: float,
        incoming_confidence: float,
        success_count: int,
        total_count: int,
        evidence_count: int,
    ) -> float:
        total = max(0, int(total_count))
        successes = min(max(0, int(success_count)), total)
        reliability = (successes + 1.0) / (total + 2.0)
        shared = ConfidenceFactors(
            source=max(_clamp(existing_confidence), _clamp(incoming_confidence)),
            quality=0.65 * _clamp(existing_confidence)
            + 0.35 * _clamp(incoming_confidence),
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                max(total, int(evidence_count))
            ),
            freshness=reliability,
        )
        return UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge")

    def template_score(
        self, case_confidence: float, *, step_count: int, evidence_count: int
    ) -> float:
        shared = ConfidenceFactors(
            source=_clamp(case_confidence),
            quality=min(1.0, 0.45 + 0.08 * max(0, step_count)),
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                evidence_count
            ),
            freshness=1.0,
        )
        return max(
            0.35,
            UnifiedConfidenceCalculator().calculate(shared, memory_type="knowledge"),
        )


def _clamp(value: float, *, lower: float = 0.0, upper: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return lower
    if not math.isfinite(numeric):
        return lower
    return max(lower, min(upper, numeric))
