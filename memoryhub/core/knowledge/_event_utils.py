"""
事件处理共享工具 — 被 KnowledgeExtractor 和 WorkflowMiner 共同使用。

避免 ~200 行重复代码。
"""

from datetime import datetime
from typing import Any
from memoryhub.adapter.schemas import MemoryEvent, SourceType


def coerce_event(raw: Any) -> MemoryEvent:
    """将可能的 dict/MemoryEvent/其他格式统一转为 MemoryEvent"""
    if isinstance(raw, MemoryEvent):
        return raw
    if isinstance(raw, dict):
        try:
            return MemoryEvent.model_validate(raw)
        except Exception:
            return raw
    return raw


def get_event_type(event: MemoryEvent) -> str:
    """获取事件类型字符串"""
    if isinstance(event, MemoryEvent):
        return event.event_type or ""
    return ""


def event_content(event: MemoryEvent) -> str:
    """提取事件文本内容"""
    if isinstance(event, MemoryEvent):
        text = event.text or ""
        if event.payload:
            import json
            try:
                payload_str = json.dumps(event.payload, ensure_ascii=False)
                text = f"{text} {payload_str}".strip()
            except Exception:
                pass
        return text
    return str(event)


def event_quality_score(event: MemoryEvent) -> float:
    """提取事件质量评分"""
    quality = getattr(event, "quality", None)
    if quality is not None and hasattr(quality, "score"):
        return float(quality.score)
    return 0.5


def get_event_field(event: MemoryEvent, field: str, default=None) -> Any:
    """安全获取事件字段"""
    if isinstance(event, MemoryEvent):
        return getattr(event, field, default)
    if isinstance(event, dict):
        return event.get(field, default)
    return default


def event_timestamp(event: MemoryEvent) -> str:
    """提取事件时间戳"""
    ts = getattr(event, "occurred_at", "")
    return str(ts) if ts else datetime.now().isoformat()


def evidence_source_type(event: MemoryEvent) -> str:
    """从事件中提取证据来源类型"""
    st = getattr(event, "source_type", None)
    if st is not None:
        if hasattr(st, "value"):
            return str(st.value)
        return str(st)
    return "unknown"


def normalize_step(step: Any) -> str:
    """将工作流步骤统一为字符串描述"""
    if isinstance(step, str):
        return step.strip()
    if isinstance(step, dict):
        return step.get("description", step.get("name", str(step)))
    return str(step)
