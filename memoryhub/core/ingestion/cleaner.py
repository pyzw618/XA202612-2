"""
数据清洗模块

负责对原始输入数据进行字段校验、去重、格式规范化。
"""

from memoryhub.adapter.schemas import MemoryEvent, SensitiveLevel


class DataCleaner:
    """数据清洗器"""

    def clean(self, raw_data: dict) -> dict:
        """
        清洗单条原始数据

        数据流: 原始数据 → clean → 清洗后数据 → normalize

        参数:
            raw_data: 原始数据字典

        返回:
            清洗后的数据字典，移除无效字段、规范化格式

        处理逻辑:
            1. 字段校验：检查必填字段是否存在
            2. 类型校验：确保字段类型正确
            3. 去除冗余空格和特殊字符
            4. 补全缺失的可选字段默认值
        """
        raise NotImplementedError

    def deduplicate(self, events: list[MemoryEvent]) -> list[MemoryEvent]:
        """
        批量去重

        参数:
            events: 事件列表

        返回:
            去重后的事件列表

        去重策略:
            - 基于 event_id 去重
            - 基于 source_hash 识别清洗后内容相同的重复事件
        """
        raise NotImplementedError

    def validate_event(self, event: MemoryEvent) -> tuple[bool, str]:
        """
        校验单条事件是否合法

        参数:
            event: MemoryEvent 实例

        返回:
            (is_valid, error_message)
        """
        raise NotImplementedError
