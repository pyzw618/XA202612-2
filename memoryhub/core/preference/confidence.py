"""
偏好置信度计算模块

根据证据数量、来源类型、时间衰减以及冲突决策（ConflictDecision）计算偏好置信度。
"""

import math
from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    ConflictDecision,
    Evidence,
    MemoryEvent,
    PreferenceMemory,
    SourceType,
)
from memoryhub.core.memory.confidence import (
    ConfidenceFactors,
    UnifiedConfidenceCalculator,
)
from memoryhub.core.memory.evidence import EvidenceMerger


def parse_occurred_at(occurred_at: str | None) -> datetime:
    """时间解析辅助函数"""
    if occurred_at:
        try:
            return datetime.strptime(occurred_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class ConfidenceCalculator:
    """偏好置信度计算器"""

    SOURCE_WEIGHTS = {
        SourceType.USER_BEHAVIOR: 1.0,  # 用户显式行为/直接反馈
        SourceType.MANUAL_CONFIG: 0.95,  # 手动配置
        SourceType.TOOL_RESULT: 0.6,  # 工具执行产生的隐式偏好
    }

    def calculate(self, preference: PreferenceMemory) -> float:
        """Compatibility facade over the shared four-factor confidence formula."""
        preference.evidences = EvidenceMerger().normalize_and_merge(
            preference.evidences
        )
        if not preference.evidences:
            preference.confidence = self._baseline_confidence(preference)
            return preference.confidence

        timestamps = [e.timestamp for e in preference.evidences]
        sources = [e.source_type for e in preference.evidences]
        evidence_quality = sum(
            float(getattr(e, "weight", 1.0)) for e in preference.evidences
        ) / len(preference.evidences)
        factors = ConfidenceFactors(
            source=self._factor_source_type(sources),
            quality=min(
                1.0, max(0.0, evidence_quality * self._factor_consistency(preference))
            ),
            support=UnifiedConfidenceCalculator.support_from_evidence_count(
                len(preference.evidences)
            ),
            freshness=self._factor_time_decay(timestamps),
        )
        preference.confidence = UnifiedConfidenceCalculator().calculate(
            factors, memory_type="preference"
        )
        return preference.confidence

    def update_confidence(
        self,
        preference: PreferenceMemory,
        new_event: MemoryEvent | None = None,
    ) -> float:
        """增量更新偏好置信度。

        当传入 new_event 时，先追加一条对应证据（若 event_id 尚未在证据链中），
        再基于完整证据链重算置信度，从而保证"新增证据"必然反映到置信度变化。

        未传 new_event 时等价于按当前证据链全量重算。
        """
        if new_event is not None:
            existing_ids = {e.event_id for e in preference.evidences}
            if new_event.event_id not in existing_ids:
                preference.evidences.append(
                    Evidence(
                        event_id=new_event.event_id,
                        content=(
                            f"[{new_event.event_type.upper()}] "
                            f"Source:{new_event.source_type.value} "
                            f"Quality:{getattr(new_event.quality, 'score', 0.0):.2f}"
                        ),
                        source_type=new_event.source_type,
                        timestamp=parse_occurred_at(new_event.occurred_at),
                        weight=getattr(new_event.quality, "score", 1.0),
                        decision=None,
                    )
                )
        return self.calculate(preference)

    def _baseline_confidence(self, preference: PreferenceMemory) -> float:
        """无证据时的置信度基线：显式反馈置信度高，隐式推断置信度低。

        structured_agent_event（结构化代理事件）通常带 quality_score：
        用 0.55 + 0.35 * quality_score 派生基线，避免无证据时被打成恒定 0.5。
        """
        if preference.extract_source == "explicit_feedback":
            return 0.8
        if preference.extract_source == "implicit_inference":
            return 0.5
        if preference.extract_source == "structured_agent_event":
            try:
                quality = float(getattr(preference, "quality_score", 0.5) or 0.0)
            except (TypeError, ValueError):
                quality = 0.0
            quality = max(0.0, min(1.0, quality))
            return round(min(0.95, 0.55 + 0.35 * quality), 4)
        return 0.5

    def _factor_evidence_count(self, evidence_count: int) -> float:
        if evidence_count <= 0:
            return 0.0
        return math.log(1 + evidence_count)

    def _factor_source_type(self, sources: list[SourceType]) -> float:
        max_weight = 0.4
        for s in sources:
            weight = self.SOURCE_WEIGHTS.get(s, 0.4)
            if weight > max_weight:
                max_weight = weight
        return max_weight

    def _factor_time_decay(self, timestamps: list[datetime]) -> float:
        if not timestamps:
            return 1.0

        now = datetime.now(timezone.utc)
        half_life_days = 14.0
        total_decay = 0.0

        for t in timestamps:
            t_utc = t.replace(tzinfo=timezone.utc) if not t.tzinfo else t
            diff_days = (now - t_utc).total_seconds() / 86400.0
            decay = math.exp(-max(0.0, diff_days) / half_life_days)
            total_decay += decay

        return total_decay / len(timestamps)

    def _factor_consistency(self, preference: PreferenceMemory) -> float:
        """评估偏好的历史交互一致性（基于非 OVERRIDE 冲突记录的占比）"""
        total_count = len(preference.evidences)
        if total_count == 0:
            return 1.0

        # 没有触发强制 OVERRIDE 覆写的证据视为正向/一致履约
        positive_count = sum(
            1 for e in preference.evidences if e.decision != ConflictDecision.OVERRIDE
        )
        consistency_ratio = positive_count / total_count

        return 1.2 if consistency_ratio >= 0.8 else (0.5 + 0.5 * consistency_ratio)
