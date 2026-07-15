"""
数据质量评分模块

对标准化后的 MemoryEvent 进行质量评分，低质量事件限制进入长期记忆。
"""

from memoryhub.adapter.schemas import MemoryEvent


class QualityScorer:
    """数据质量评分器"""

    # 各因子权重
    WEIGHTS = {
        "completeness": 0.25,
        "source_reliability": 0.25,
        "execution_success": 0.20,
        "user_feedback_strength": 0.20,
        "parse_confidence": 0.10,
    }

    def score(self, event: MemoryEvent) -> float:
        """
        计算单条事件的质量评分

        数据流: MemoryEvent → score → 更新 event.quality_score

        参数:
            event: 标准化后的 MemoryEvent

        返回:
            质量评分 [0.0, 1.0]

        计算公式:
            QualityScore = Σ(weight_i × factor_i)

        各因子说明:
            - completeness: 事件字段是否完整
            - source_reliability: 来源是否可信 (tool_call > user_feedback > behavior)
            - execution_success: 工具调用是否成功
            - user_feedback_strength: 是否有明确用户反馈
            - parse_confidence: 系统解析置信度
        """
        raise NotImplementedError

    def _score_completeness(self, event: MemoryEvent) -> float:
        """评估字段完整度"""
        raise NotImplementedError

    def _score_source_reliability(self, event: MemoryEvent) -> float:
        """评估来源可靠度"""
        raise NotImplementedError

    def _score_execution_success(self, event: MemoryEvent) -> float:
        """评估执行成功度"""
        raise NotImplementedError

    def _score_feedback_strength(self, event: MemoryEvent) -> float:
        """评估反馈强度"""
        raise NotImplementedError

    def _score_parse_confidence(self, event: MemoryEvent) -> float:
        """评估解析置信度"""
        raise NotImplementedError

    def should_enter_long_term(self, event: MemoryEvent) -> bool:
        """
        判断事件是否应进入长期记忆

        规则: quality_score >= 0.6 才允许进入长期记忆
        """
        raise NotImplementedError
