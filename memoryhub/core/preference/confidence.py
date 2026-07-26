"""
偏好置信度计算模块

根据证据数量、来源类型、时间衰减以及冲突决策（ConflictDecision）计算偏好置信度。
"""

import math
from datetime import datetime, timezone
from memoryhub.adapter.schemas import (
    PreferenceMemory,
    MemoryEvent,
    SourceType,
    Evidence,
    ConflictDecision,
)


def parse_occurred_at(occurred_at: str | None) -> datetime:
    """时间解析辅助函数"""
    if occurred_at:
        try:
            return datetime.strptime(occurred_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class ConfidenceCalculator:
    """偏好置信度计算器"""

    SOURCE_WEIGHTS = {
        SourceType.USER_BEHAVIOR: 1.0,     # 用户显式行为/直接反馈
        SourceType.MANUAL_CONFIG: 0.95,    # 手动配置
        SourceType.TOOL_RESULT: 0.6,       # 工具执行产生的隐式偏好
        SourceType.ASSISTANT_LOG: 0.4,     # 单次模型推论/日志
    }

    def calculate(self, preference: PreferenceMemory) -> float:
        """计算综合置信度"""
        if not preference.evidences:
            return 0.0

        timestamps = [e.timestamp for e in preference.evidences]
        sources = [e.source_type for e in preference.evidences]

        f_count = self._factor_evidence_count(len(preference.evidences))
        f_source = self._factor_source_type(sources)
        f_time = self._factor_time_decay(timestamps)
        f_consistency = self._factor_consistency(preference)

        # 基础得分计算
        raw_score = f_source * f_time * f_consistency * (1.0 + 0.15 * f_count)

        # 负向惩罚项：仅针对发生过 ConflictDecision.OVERRIDE 覆写的证据做强类型扣分
        neg_penalty = sum(
            0.25 * e.weight
            for e in preference.evidences
            if e.decision == ConflictDecision.OVERRIDE
        )

        # S型 Sigmoid 平滑并扣除惩罚项
        final_confidence = (1.0 / (1.0 + math.exp(-3.0 * (raw_score - 0.5)))) - neg_penalty
        preference.confidence = max(0.0, min(1.0, final_confidence))

        return preference.confidence

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

    def update_confidence(self, preference: PreferenceMemory, new_event: MemoryEvent) -> float:
        """增量更新置信度"""
        epsilon_t = 0.0
        status = str(new_event.payload.get("status", "")).upper()
        user_action = str(new_event.payload.get("user_action", "")).upper()

        # 解析冲突决策 ConflictDecision
        conflict_decision = None
        if user_action == "OVERRIDE" or status in ["USER_REJECT", "REJECT"]:
            conflict_decision = ConflictDecision.OVERRIDE
            epsilon_t += 0.8
        elif user_action == "MERGE":
            conflict_decision = ConflictDecision.MERGE

        dt = parse_occurred_at(new_event.occurred_at)
        event_id = getattr(new_event, "event_id", "") or ""

        # 构造搭载 ConflictDecision 的 Evidence
        new_evidence = Evidence(
            event_id=event_id,
            content=f"[{new_event.event_type.upper()}] Status:{status} Action:{user_action}",
            source_type=new_event.source_type,
            timestamp=dt,
            weight=max(0.1, 1.0 - epsilon_t),
            decision=conflict_decision,
        )

        preference.evidences.append(new_evidence)

        return self.calculate(preference)