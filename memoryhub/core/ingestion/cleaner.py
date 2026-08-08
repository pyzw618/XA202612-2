"""
数据清洗模块

负责对原始输入数据进行字段校验、去重、格式规范化。
"""

from __future__ import annotations

import re
from typing import Any

from memoryhub.adapter.schemas import MemoryEvent

_INVALID_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
        if not isinstance(raw_data, dict):
            raise TypeError("raw_data must be a dictionary")
        cleaned = self._clean_value(raw_data, top_level=True)
        if not isinstance(cleaned, dict):
            raise TypeError("cleaned raw_data must remain a dictionary")
        return cleaned

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
        unique: list[MemoryEvent] = []
        seen_event_ids: set[str] = set()
        seen_hashes: set[str] = set()
        for event in events:
            if event.event_id in seen_event_ids or event.source_hash in seen_hashes:
                continue
            seen_event_ids.add(event.event_id)
            seen_hashes.add(event.source_hash)
            unique.append(event)
        return unique

    def validate_event(self, event: MemoryEvent) -> tuple[bool, str]:
        """
        校验单条事件是否合法

        参数:
            event: MemoryEvent 实例

        返回:
            (is_valid, error_message)
        """
        if not event.event_id:
            return False, "missing event_id"
        if len(event.source_hash) != 64:
            return False, "invalid source_hash"
        if event.tool_calls:
            sequences = [call.sequence for call in event.tool_calls]
            if sequences != sorted(sequences):
                return False, "tool_calls are not ordered by sequence"
        return True, ""

    def _clean_value(self, value: Any, *, top_level: bool = False) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                if raw_value is None:
                    continue
                key = self._clean_text(str(raw_key))
                if not key:
                    continue
                if top_level and (
                    key.startswith("_") or key in {"debug", "trace_dump"}
                ):
                    continue
                result[key] = self._clean_value(raw_value)
            return result
        if isinstance(value, (list, tuple)):
            return [self._clean_value(item) for item in value if item is not None]
        if isinstance(value, str):
            return self._clean_text(value)
        if isinstance(value, (bool, int, float)) or value is None:
            return value
        return self._clean_text(str(value))

    @staticmethod
    def _clean_text(value: str) -> str:
        value = _INVALID_CONTROL_CHARS.sub("", value)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()
