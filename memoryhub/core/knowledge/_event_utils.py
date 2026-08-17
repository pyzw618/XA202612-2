"""
事件处理共享工具 — 被 KnowledgeExtractor 和 WorkflowMiner 共同使用。

避免 ~200 行重复代码。
"""

from datetime import datetime, timezone
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


def get_event_type(event: MemoryEvent | dict) -> str:
    """获取事件类型字符串"""
    if isinstance(event, MemoryEvent):
        event_type = getattr(event, "event_type", "")
        if isinstance(event_type, str) and event_type:
            return event_type.lower()
        source_type = getattr(event, "source_type", None)
        if source_type is SourceType.TOOL_RESULT:
            return "tool_call"
        return "task_trajectory"
    if isinstance(event, dict):
        event_type = str(event.get("event_type", "")).strip().lower()
        if event_type in {"tool_call", "task_trajectory", "user_feedback", "user_behavior", "manual_config"}:
            return event_type
        source_type = str(event.get("source_type", "")).strip().lower()
        if source_type in {"tool_result", "tool_call"}:
            return "tool_call"
        if source_type == "manual_config":
            return "manual_config"
        if source_type == "user_behavior":
            return "user_behavior"
        return "task_trajectory"
    return "task_trajectory"


def event_content(event: MemoryEvent | dict) -> dict:
    """提取事件内容为 dict（payload 或 content）"""
    if isinstance(event, MemoryEvent):
        content = getattr(event, "content", None)
        if isinstance(content, dict):
            return content
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, dict):
            return dict(payload)
        return {}
    if isinstance(event, dict):
        if isinstance(event.get("content"), dict):
            return dict(event.get("content"))
        if isinstance(event.get("payload"), dict):
            return dict(event.get("payload"))
        return {}
    return {}


def event_quality_score(event: MemoryEvent | dict) -> float:
    """提取事件质量评分"""
    if isinstance(event, MemoryEvent):
        quality = getattr(event, "quality", None)
        if quality is not None and hasattr(quality, "score"):
            return float(quality.score)
        return float(getattr(event, "quality_score", 0.5))
    if isinstance(event, dict):
        quality = event.get("quality")
        if isinstance(quality, dict):
            return float(quality.get("score", 0.5))
        return float(event.get("quality_score", 0.5))
    return 0.5


def get_event_field(event: MemoryEvent | dict, field: str, default: str = "") -> str:
    """安全获取事件字段"""
    if isinstance(event, MemoryEvent):
        value = getattr(event, field, None)
        if value not in (None, ""):
            return str(value)
        if field == "source":
            source_type = getattr(event, "source_type", None)
            if source_type is not None:
                return str(source_type)
        return default
    if isinstance(event, dict):
        value = event.get(field)
        if value not in (None, ""):
            return str(value)
        if field == "source":
            value = event.get("source_type")
            if value not in (None, ""):
                return str(value)
        return default
    return default


def event_timestamp(event: MemoryEvent | dict) -> datetime:
    """提取事件时间戳为 datetime（带时区）"""
    if isinstance(event, MemoryEvent):
        value = getattr(event, "timestamp", None)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return datetime.now(timezone.utc)
        if value is not None:
            return value
        occurred_at = getattr(event, "occurred_at", None)
        if isinstance(occurred_at, str):
            try:
                return datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            except Exception:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)
    if isinstance(event, dict):
        occurred_at = event.get("occurred_at") or event.get("timestamp")
        if isinstance(occurred_at, str):
            try:
                return datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            except Exception:
                return datetime.now(timezone.utc)
        return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def evidence_source_type(event: MemoryEvent | dict) -> SourceType:
    """从事件中提取证据来源类型"""
    etype = get_event_type(event)
    if etype == "tool_call":
        return SourceType.TOOL_RESULT
    if etype == "user_behavior":
        return SourceType.USER_BEHAVIOR
    if etype == "manual_config":
        return SourceType.MANUAL_CONFIG
    return SourceType.TOOL_RESULT


def normalize_step(step: Any) -> str:
    """将工作流步骤统一为字符串描述"""
    if isinstance(step, str):
        return step.strip()
    if isinstance(step, dict):
        return step.get("description", step.get("name", str(step)))
    return str(step)
