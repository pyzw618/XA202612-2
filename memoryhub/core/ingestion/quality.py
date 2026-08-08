"""
数据质量评分模块

对标准化后的 MemoryEvent 进行质量评分，低质量事件限制进入长期记忆。
"""

from __future__ import annotations

from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
)


class QualityScorer:
    """数据质量评分器"""

    # 各因子权重
    WEIGHTS = {
        "completeness": 0.40,
        "validity": 0.30,
        "consistency": 0.20,
        "freshness": 0.10,
    }

    def __init__(self, reference_time: datetime | None = None):
        self.reference_time = reference_time

    def score(self, event: MemoryEvent) -> EventQuality:
        """
        计算单条事件的质量评分

        数据流: MemoryEvent → score → 生成 event.quality

        参数:
            event: 标准化后的 MemoryEvent

        返回:
            包含总分、状态、分项分数和问题列表的 EventQuality

        计算公式:
            score = 0.40 * completeness + 0.30 * validity
                  + 0.20 * consistency + 0.10 * freshness

        各因子说明:
            - completeness: 事件字段是否完整
            - validity: 来源、事件类型和时间是否合法
            - consistency: 来源类型与 tool_calls/payload 字段是否一致
            - freshness: 事件相对参考时间的新鲜度
        """
        completeness = self._score_completeness(event)
        validity = self._score_validity(event)
        consistency = self._score_consistency(event)
        freshness = self._score_freshness(event)
        total = round(
            self.WEIGHTS["completeness"] * completeness
            + self.WEIGHTS["validity"] * validity
            + self.WEIGHTS["consistency"] * consistency
            + self.WEIGHTS["freshness"] * freshness,
            4,
        )

        issues: list[str] = []
        if not event.user_id:
            issues.append("completeness:missing_user_id")
        if not event.occurred_at:
            issues.append("validity:missing_occurred_at")
        if completeness < 0.8:
            issues.append("completeness:below_threshold")
        if validity < 0.8:
            issues.append("validity:below_threshold")
        if consistency < 0.8:
            issues.append("consistency:source_payload_mismatch")
        if freshness < 0.6:
            issues.append("freshness:stale_event")

        missing_identity_and_time = not event.user_id and not event.occurred_at
        if total < 0.6 or missing_identity_and_time:
            status = QualityStatus.REJECTED
        elif total < 0.8 or not event.user_id or not event.occurred_at:
            status = QualityStatus.REVIEW
        else:
            status = QualityStatus.ACCEPTED

        return EventQuality(
            score=total,
            status=status,
            completeness=round(completeness, 4),
            validity=round(validity, 4),
            consistency=round(consistency, 4),
            freshness=round(freshness, 4),
            issues=list(dict.fromkeys(issues)),
        )

    def _score_completeness(self, event: MemoryEvent) -> float:
        """评估字段完整度"""
        checks = (
            (bool(event.event_id), 0.10),
            (bool(event.user_id), 0.20),
            (bool(event.occurred_at), 0.20),
            (bool(event.event_type), 0.10),
            (bool(event.session_id), 0.05),
            (bool(event.scene), 0.10),
            (bool(event.task_type), 0.10),
            (bool(event.text or event.payload or event.tool_calls), 0.15),
        )
        return sum(weight for present, weight in checks if present)

    def _score_validity(self, event: MemoryEvent) -> float:
        """评估字段合法性。"""
        score = 0.2
        if event.event_type:
            score += 0.2
        if event.occurred_at:
            try:
                datetime.strptime(event.occurred_at, "%Y-%m-%dT%H:%M:%SZ")
                score += 0.3
            except ValueError:
                pass
        if len(event.source_hash) == 64:
            score += 0.2
        if event.schema_version in {"1.0", "1.1"}:
            score += 0.1
        return min(score, 1.0)

    def _score_consistency(self, event: MemoryEvent) -> float:
        """评估来源与 payload 的一致性。"""
        if event.source_type is SourceType.TOOL_RESULT:
            score = 0.5 if event.tool_calls else 0.0
            if event.event_type == "agent_response":
                score += 0.2 if event.turn_id else 0.0
                score += 0.2 if event.text else 0.0
            else:
                score += 0.4
            if event.payload:
                score += 0.1
            return min(score, 1.0)
        if event.source_type is SourceType.USER_BEHAVIOR:
            if event.tool_calls:
                return 0.0
            expected = {"action", "target", "value", "role", "text"}
            return 1.0 if expected & set(event.payload) else 0.6
        if event.source_type is SourceType.MANUAL_CONFIG:
            if event.tool_calls:
                return 0.0
            return 1.0 if {"key", "value"} & set(event.payload) else 0.5
        return 0.0

    def _score_freshness(self, event: MemoryEvent) -> float:
        """评估事件新鲜度。"""
        if not event.occurred_at:
            return 0.0
        occurred_at = datetime.strptime(
            event.occurred_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        now = self.reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        age_seconds = (now.astimezone(timezone.utc) - occurred_at).total_seconds()
        if age_seconds < -300:
            return 0.5
        age_days = max(age_seconds, 0.0) / 86_400
        if age_days <= 1:
            return 1.0
        if age_days <= 7:
            return 0.8
        if age_days <= 30:
            return 0.6
        if age_days <= 365:
            return 0.3
        return 0.1

    def should_enter_long_term(self, event: MemoryEvent) -> bool:
        """
        判断事件是否应进入长期记忆

        规则: 只有 quality.status == "accepted" 才进入下游记忆链路。
        review 进入复核队列，rejected 仅保留审计记录。
        """
        return event.quality.status is QualityStatus.ACCEPTED
