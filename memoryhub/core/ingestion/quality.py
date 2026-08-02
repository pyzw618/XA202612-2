"""
数据质量评分模块

对标准化后的 MemoryEvent 进行质量评分，低质量事件限制进入长期记忆。
"""

from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus


class QualityScorer:
    """数据质量评分器"""

    MIN_QUALITY_SCORE = 0.2  # 低于此分数的事件将被拒绝

    def score(self, event: MemoryEvent) -> EventQuality:
        """对事件进行质量评分"""
        completeness = self._score_completeness(event)
        validity = self._score_validity(event)
        consistency = self._score_consistency(event)
        freshness = self._score_freshness(event)

        overall = 0.30 * completeness + 0.30 * validity + 0.20 * consistency + 0.20 * freshness

        status = QualityStatus.ACCEPTED if overall >= self.MIN_QUALITY_SCORE else QualityStatus.REJECTED

        return EventQuality(
            score=overall,
            status=status,
            completeness=completeness,
            validity=validity,
            consistency=consistency,
            freshness=freshness,
        )

    def batch_score(self, events: list[MemoryEvent]) -> list[tuple[MemoryEvent, EventQuality]]:
        """批量评分，返回 (event, quality) 对"""
        return [(e, self.score(e)) for e in events]

    def filter_acceptable(self, events: list[MemoryEvent]) -> list[MemoryEvent]:
        """仅返回质量达标的记忆事件"""
        return [e for e in events if self.score(e).status == QualityStatus.ACCEPTED]

    def _score_completeness(self, event: MemoryEvent) -> float:
        """字段完整度评分"""
        scored = 0
        if event.text:
            scored += 0.4
        if event.event_type:
            scored += 0.2
        if event.scene:
            scored += 0.1
        if event.task_type:
            scored += 0.1
        if event.user_id:
            scored += 0.1
        if event.payload:
            scored += 0.1
        return min(scored, 1.0)

    def _score_validity(self, event: MemoryEvent) -> float:
        """数据有效性评分"""
        score = 0.6  # 基础分
        if len(event.text) >= 5:
            score += 0.2
        if len(event.event_type) >= 1:
            score += 0.2
        return min(score, 1.0)

    def _score_consistency(self, event: MemoryEvent) -> float:
        """数据一致性评分"""
        score = 0.5
        if event.text and event.source_type:
            score += 0.3
        if event.scene and event.task_type:
            score += 0.2
        return min(score, 1.0)

    def _score_freshness(self, event: MemoryEvent) -> float:
        """数据新鲜度评分：基于 occurred_at 距今天数"""
        from datetime import datetime, timezone
        try:
            ts = datetime.fromisoformat(event.occurred_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
            return max(0.0, 1.0 - age_days / 90.0)  # 90 天线性衰减
        except Exception:
            return 0.5
