"""
数据标准化模块

负责将不同来源的原始数据统一转化为 MemoryEvent 格式。
"""

from memoryhub.adapter.schemas import MemoryEvent, SourceType


class EventNormalizer:
    """事件标准化器 — 将各来源字段映射到统一 MemoryEvent 格式"""

    _TYPE_MAP = {
        "tool": SourceType.TOOL_RESULT,
        "chat": SourceType.USER_BEHAVIOR,
        "feedback": SourceType.USER_BEHAVIOR,
        "system": SourceType.TOOL_RESULT,
    }

    def normalize(self, cleaned: dict) -> MemoryEvent:
        """将清洗后的 dict 标准化为 MemoryEvent 对象"""
        from datetime import datetime, timezone

        source_type = self._TYPE_MAP.get(
            str(cleaned.get("source_type", "")).lower(),
            SourceType.TOOL_RESULT,
        )

        occurred_at = cleaned.get("occurred_at", "")
        if not occurred_at:
            occurred_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        return MemoryEvent(
            event_id=cleaned.get("event_id", ""),
            source_type=source_type,
            event_type=cleaned.get("event_type", ""),
            user_id=cleaned.get("user_id", "default"),
            session_id=cleaned.get("session_id", ""),
            scene=cleaned.get("scene", ""),
            task_type=cleaned.get("task_type", ""),
            text=cleaned.get("text", ""),
            payload=cleaned.get("payload", {}),
            occurred_at=occurred_at,
        )

    def normalize_batch(self, cleaned_list: list[dict]) -> list[MemoryEvent]:
        """批量标准化"""
        return [self.normalize(entry) for entry in cleaned_list]

    def normalize_tool_result(self, tool_name: str, result: dict) -> MemoryEvent:
        """从工具调用结果构造标准事件"""
        import uuid
        return MemoryEvent(
            event_id=f"tool_{uuid.uuid4().hex[:12]}",
            source_type=SourceType.TOOL_RESULT,
            event_type=tool_name,
            text=str(result.get("output", result)),
            payload=result,
        )
