"""
偏好置信度计算模块

根据证据数量、来源类型、用户反馈强度等因素计算偏好置信度。
"""

from memoryhub.adapter.schemas import PreferenceMemory, MemoryEvent


class ConfidenceCalculator:
    """偏好置信度计算器"""

    # 来源类型权重
    SOURCE_WEIGHTS = {
        "explicit_feedback": 1.0,     # 用户显式反馈
        "manual_config": 0.95,        # 手动配置
        "repeated_behavior": 0.8,     # 重复行为
        "tool_result": 0.6,           # 工具调用结果
        "single_behavior": 0.4,       # 单次行为
    }

    def calculate(self, preference: PreferenceMemory) -> float:
        """
        计算偏好置信度

        数据流: 偏好候选 → calculate → 更新 confidence 字段

        参数:
            preference: 候选偏好记忆

        返回:
            置信度 [0.0, 1.0]

        计算因子:
            1. 证据数量：证据越多，置信度越高
            2. 来源类型：显式反馈 > 配置 > 行为
            3. 时间衰减：越近的证据权重越高
            4. 一致性：多条证据指向一致时置信度提升
        """
        raise NotImplementedError

    def _factor_evidence_count(self, evidence_count: int) -> float:
        """证据数量因子"""
        raise NotImplementedError

    def _factor_source_type(self, sources: list[str]) -> float:
        """来源类型因子"""
        raise NotImplementedError

    def _factor_time_decay(self, timestamps: list) -> float:
        """时间衰减因子"""
        raise NotImplementedError

    def _factor_consistency(self, preference: PreferenceMemory) -> float:
        """一致性因子"""
        raise NotImplementedError

    def update_confidence(self, preference: PreferenceMemory, new_event: MemoryEvent) -> float:
        """
        增量更新置信度（新证据加入时）

        参数:
            preference: 已有偏好
            new_event: 新增事件

        返回:
            更新后的置信度
        """
        raise NotImplementedError
