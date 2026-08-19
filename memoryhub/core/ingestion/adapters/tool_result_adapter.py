"""ToolResultAdapter：把"工具名 + 原始结果"结构化适配为 MemoryEvent（赛题要求1，I-7）。

把服务端 `EventNormalizer.normalize_tool_result` 提升为对外入口（REFACTOR_PLAN_V2
§4.1.1），供 `POST /api/memory/sources/tool_result` 与 OS Agent 工具轨迹接入层复用。
"""

from __future__ import annotations

from typing import Any

from memoryhub.adapter.schemas import MemoryEvent
from memoryhub.core.ingestion.normalizer import EventNormalizer


class ToolResultAdapter:
    """工具执行结果源适配器：原始结果 dict → 结构化 MemoryEvent。"""

    def __init__(self, normalizer: EventNormalizer | None = None) -> None:
        self.normalizer = normalizer or EventNormalizer()

    def to_event(self, tool_name: str, result: dict[str, Any]) -> MemoryEvent:
        """校验并结构化为 MemoryEvent。

        Args:
            tool_name: 工具名（必填，长度 ≥1）。
            result: 工具返回的原始结果对象（必须为 dict）。

        Returns:
            结构化的 Schema 1.1 MemoryEvent（source_type=TOOL_RESULT）。

        Raises:
            ValueError: 工具名为空或 result 非 dict。
        """
        if not tool_name or not str(tool_name).strip():
            raise ValueError("tool_name is required")
        return self.normalizer.normalize_tool_result(tool_name, result)
