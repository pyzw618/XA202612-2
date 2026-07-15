"""
数据标准化模块

负责将不同来源的原始数据统一转化为 MemoryEvent 格式。
"""

from memoryhub.adapter.schemas import MemoryEvent, EventType


class DataNormalizer:
    """数据标准化器"""

    # 各数据源的字段映射表
    FIELD_MAPPINGS: dict[str, dict] = {
        "tool_call": {
            "tool_name": "content.tool_name",
            "input": "content.input",
            "output": "content.output",
            "status": "content.status",
        },
        "user_feedback": {
            "text": "content.text",
            "feedback_type": "content.feedback_type",
        },
        "user_behavior": {
            "action": "content.action",
            "target": "content.target",
            "repeated_count": "content.repeated_count",
        },
        "manual_config": {
            "key": "content.key",
            "value": "content.value",
        },
    }

    def normalize(self, raw_data: dict, source: str = "os_agent") -> MemoryEvent:
        """
        将原始数据标准化为 MemoryEvent

        数据流: 清洗后数据 → normalize → MemoryEvent → 质量评分

        参数:
            raw_data: 清洗后的原始数据字典
            source: 数据来源标识

        返回:
            标准化的 MemoryEvent 实例

        处理逻辑:
            1. 根据 source 类型选择字段映射
            2. 提取 event_type
            3. 构造标准 content 字典
            4. 识别 scene 和 task_type
            5. 填充 timestamp 等元数据
        """
        raise NotImplementedError

    def _detect_event_type(self, raw_data: dict) -> EventType:
        """从原始数据中推断事件类型"""
        raise NotImplementedError

    def _detect_scene(self, raw_data: dict) -> tuple[str, str]:
        """
        识别场景和任务类型

        返回:
            (scene, task_type)，如 ("office", "office.weekly_report")
        """
        raise NotImplementedError

    def batch_normalize(self, raw_data_list: list[dict], source: str = "os_agent") -> list[MemoryEvent]:
        """批量标准化"""
        raise NotImplementedError
