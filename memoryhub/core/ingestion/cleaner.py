"""
数据清洗模块

负责对原始输入数据进行字段校验、去重、格式规范化。
"""

from memoryhub.adapter.schemas import MemoryEvent


class DataCleaner:
    """数据清洗器"""

    _required_fields = {"event_id", "source_type", "event_type"}

    def __init__(self, safety_config=None) -> None:
        self.max_depth = min(16, int(getattr(safety_config, "max_depth", 16)))
        self.max_text_chars = min(
            100_000, int(getattr(safety_config, "max_field_chars", 100_000))
        )
        self.max_tool_calls = min(
            100, int(getattr(safety_config, "max_candidates", 100))
        )
        self.max_fields = min(
            5_000, int(getattr(safety_config, "max_scanned_fields", 5_000))
        )

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
        if len(cleaned["text"]) > self.max_text_chars:
            raise ValueError("text exceeds configured safety budget")
        if len(cleaned["tool_calls"]) > self.max_tool_calls:
            raise ValueError("tool_calls exceeds configured safety budget")
        self._validate_structure(cleaned["payload"])
        self._validate_structure(cleaned["tool_calls"])
        return cleaned

    def _validate_structure(self, value) -> None:
        pending = [(value, 0)]
        fields = 0
        while pending:
            current, depth = pending.pop()
            if depth > self.max_depth:
                raise ValueError("payload exceeds configured safety depth")
            if isinstance(current, dict):
                fields += len(current)
                pending.extend((item, depth + 1) for item in current.values())
            elif isinstance(current, list):
                fields += len(current)
                pending.extend((item, depth + 1) for item in current)
            if fields > self.max_fields:
                raise ValueError("payload exceeds configured safety field budget")

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
