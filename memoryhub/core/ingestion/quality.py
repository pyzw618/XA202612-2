"""
数据质量评分模块

对标准化后的 MemoryEvent 进行质量评分，低质量事件限制进入长期记忆。
"""

from memoryhub.adapter.schemas import EventQuality, MemoryEvent


class QualityScorer:
    """数据质量评分器"""

    # 各因子权重
    WEIGHTS = {
        "completeness": 0.40,
        "validity": 0.30,
        "consistency": 0.20,
        "freshness": 0.10,
    }

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
            - consistency: 来源类型与 payload 字段是否一致
            - freshness: 事件相对参考时间的新鲜度
        """
        raise NotImplementedError

    def _score_completeness(self, event: MemoryEvent) -> float:
        """评估字段完整度"""
        raise NotImplementedError

    def _score_validity(self, event: MemoryEvent) -> float:
        """评估字段合法性。"""
        raise NotImplementedError

    def _score_consistency(self, event: MemoryEvent) -> float:
        """评估来源与 payload 的一致性。"""
        raise NotImplementedError

    def _score_freshness(self, event: MemoryEvent) -> float:
        """评估事件新鲜度。"""
        raise NotImplementedError

    def should_enter_long_term(self, event: MemoryEvent) -> bool:
        """
        判断事件是否应进入长期记忆

        规则: 只有 quality.status == "accepted" 才进入下游记忆链路。
        review 进入复核队列，rejected 仅保留审计记录。
        """
        raise NotImplementedError
