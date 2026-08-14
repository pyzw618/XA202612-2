"""
数据清洗模块

负责对原始输入数据进行字段校验、去重、格式规范化。
"""

from memoryhub.adapter.schemas import MemoryEvent


class DataCleaner:
    """数据清洗器"""

    _required_fields = {"event_id", "source_type", "event_type"}

    def clean(self, raw_data: dict) -> dict:
        """
        清洗单条原始数据

        数据流: 原始数据 → clean → 清洗后数据 → normalize
        """
        cleaned = {}

        # 复制已知字段并去除首尾空白
        for key, value in raw_data.items():
            if isinstance(value, str):
                cleaned[key] = value.strip()
            else:
                cleaned[key] = value

        # 补全缺失的可选字段默认值
        cleaned.setdefault("user_id", "default")
        cleaned.setdefault("session_id", "")
        cleaned.setdefault("scene", "")
        cleaned.setdefault("task_type", "")
        cleaned.setdefault("text", "")
        cleaned.setdefault("payload", {})
        cleaned.setdefault("tool_calls", [])
        cleaned.setdefault("occurred_at", "")
        if not isinstance(cleaned["payload"], dict):
            raise ValueError("payload must be an object")
        if not isinstance(cleaned["tool_calls"], list):
            raise ValueError("tool_calls must be a list")
        if not isinstance(cleaned["text"], str):
            raise ValueError("text must be a string")
        if len(cleaned["text"]) > 100_000:
            raise ValueError("text exceeds 100000 characters")
        if len(cleaned["tool_calls"]) > 100:
            raise ValueError("tool_calls exceeds 100 entries")

        return cleaned

    def deduplicate(self, events: list[MemoryEvent]) -> list[MemoryEvent]:
        """
        批量去重：基于 event_id 去重，保留首次出现的事件。
        """
        seen: set[str] = set()
        deduplicated: list[MemoryEvent] = []
        for event in events:
            if event.event_id not in seen:
                seen.add(event.event_id)
                deduplicated.append(event)
        return deduplicated

    def validate_event(self, event: MemoryEvent) -> tuple[bool, str]:
        """
        校验单条事件是否合法。
        返回 (is_valid, error_message)。
        """
        if not event.event_id or not event.event_id.strip():
            return False, "event_id is required"
        if not event.event_type or not event.event_type.strip():
            return False, "event_type is required"
        try:
            _ = event.source_type
        except Exception:
            return False, "invalid source_type"
        return True, ""
