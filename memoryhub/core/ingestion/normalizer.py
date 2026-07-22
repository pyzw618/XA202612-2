"""
数据标准化模块

负责将不同来源的原始数据统一转化为 MemoryEvent 格式。
"""

from memoryhub.adapter.schemas import MemoryEvent, SourceType


class DataNormalizer:
    """数据标准化器"""

    # 各数据源的字段映射表
    FIELD_MAPPINGS: dict[str, dict] = {
        "tool_result": {
            "tool_name": "payload.tool_name",
            "input": "payload.input",
            "output": "payload.output",
            "status": "payload.status",
        },
        "user_behavior": {
            "action": "payload.action",
            "target": "payload.target",
            "value": "payload.value",
        },
        "manual_config": {
            "key": "payload.key",
            "value": "payload.value",
        },
    }

    def normalize(self, raw_data: dict, source_type: str = "") -> MemoryEvent:
        """
        将原始数据标准化为 MemoryEvent

        数据流: 清洗后数据 → normalize → MemoryEvent → 质量评分

        参数:
            raw_data: 清洗后的原始数据字典
            source_type: 来源大类；为空时根据原始字段推断

        返回:
            标准化的 MemoryEvent 实例

        处理逻辑:
            1. 将来源别名归一为 source_type
            2. 提取或推断 event_type
            3. 构造标准 payload 和 text
            4. 识别 scene 和 task_type
            5. 将 occurred_at 统一为 UTC 并生成 source_hash
        """
        raise NotImplementedError

    def _detect_source_type(self, raw_data: dict) -> SourceType:
        """从原始数据中推断来源大类。"""
        raise NotImplementedError

    def _detect_event_type(self, raw_data: dict) -> str:
        """从原始数据中推断来源内的具体事件类型。"""
        raise NotImplementedError

    def _detect_scene(self, raw_data: dict) -> tuple[str, str]:
        """
        识别场景和任务类型

        返回:
            (scene, task_type)，如 ("office", "office.weekly_report")
        """
        raise NotImplementedError

    def batch_normalize(
        self, raw_data_list: list[dict], source_type: str = ""
    ) -> list[MemoryEvent]:
        """批量标准化"""
        raise NotImplementedError
