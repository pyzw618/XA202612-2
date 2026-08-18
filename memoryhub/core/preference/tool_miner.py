"""ToolPreferenceMiner：从任务轨迹确定性挖掘"该任务/场景偏好使用某工具"偏好。

REFACTOR_PLAN_V2 §4.2.1：赛题要求(2)点名的"工具选择偏好提取不精准"痛点。
纯统计规则（无 LLM）：同一 (scene, task_type) 内某工具使用次数/成功率达标且为最常用
→ 产出 PreferenceMemory(TOOL_PREFERENCE)。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from memoryhub.adapter.schemas import (
    Evidence,
    PreferenceMemory,
    SceneScope,
    ToolCallStatus,
)

logger = logging.getLogger(__name__)

_USABLE_STATUSES = {ToolCallStatus.SUCCESS.value, ToolCallStatus.PARTIAL.value}


class ToolPreferenceMiner:
    """工具选择偏好挖掘器（确定性优先，无 LLM）。"""

    def __init__(self, min_frequency: int = 3, min_success_rate: float = 0.7):
        self.min_frequency = max(1, int(min_frequency))
        self.min_success_rate = float(min_success_rate)

    def mine(self, events, user_id: str = "default") -> list[PreferenceMemory]:
        """从事件列表（轨迹）挖掘工具选择偏好。返回去重后的 PreferenceMemory 列表。"""
        stats: dict[tuple, dict] = defaultdict(lambda: {"use": 0, "success": 0})
        evidence_by_key: dict[tuple, list[Evidence]] = defaultdict(list)

        for event in events:
            scene = getattr(event, "scene", "") or ""
            task_type = getattr(event, "task_type", "") or ""
            event_id = str(getattr(event, "event_id", "") or "")
            for call in list(getattr(event, "tool_calls", []) or []):
                raw_status = getattr(call, "status", "")
                if hasattr(raw_status, "value"):
                    raw_status = raw_status.value
                status = str(raw_status or "").lower()
                if status not in _USABLE_STATUSES:
                    continue
                tool = str(getattr(call, "tool_name", "") or "").strip()
                if not tool:
                    continue
                key = (scene, task_type, tool)
                stats[key]["use"] += 1
                if status == ToolCallStatus.SUCCESS.value:
                    stats[key]["success"] += 1
                evidence_by_key[key].append(
                    Evidence(
                        event_id=event_id,
                        evidence_id=f"{event_id}:{getattr(call, 'call_id', '')}",
                        content=(
                            f"工具 {tool} 返回: "
                            + json.dumps(getattr(call, "result", ""), ensure_ascii=False)[:500]
                        ),
                        source_id=str(getattr(call, "call_id", "") or event_id),
                        source_type="tool_result",
                    )
                )

        # 每个 (scene, task_type) 取使用最多的工具
        task_best: dict[tuple, tuple[str, dict, list]] = {}
        for (scene, task_type, tool), s in stats.items():
            tkey = (scene, task_type)
            if tkey not in task_best or s["use"] > task_best[tkey][1]["use"]:
                task_best[tkey] = (tool, s, evidence_by_key[(scene, task_type, tool)])

        result: list[PreferenceMemory] = []
        for (scene, task_type), (tool, s, evidences) in task_best.items():
            if s["use"] < self.min_frequency:
                continue
            success_rate = s["success"] / s["use"]
            if success_rate < self.min_success_rate:
                continue
            confidence = min(0.95, 0.6 + 0.1 * s["use"] + 0.2 * success_rate)
            result.append(
                PreferenceMemory(
                    user_id=user_id,
                    preference_type="tool_preference",
                    text=f"在{task_type or '当前'}任务中偏好使用 {tool} 工具",
                    payload={
                        "action": "use_tool",
                        "tool": tool,
                        "task_type": task_type,
                    },
                    scope=SceneScope(scene=scene, task_type=task_type),
                    confidence=round(confidence, 4),
                    quality_score=1.0,
                    extract_source="tool_preference_miner",
                    evidences=evidences,
                    tags=["工具", tool],
                )
            )
            logger.info(
                "tool preference mined: user=%s scene=%s task=%s tool=%s use=%d success_rate=%.2f",
                user_id, scene, task_type, tool, s["use"], success_rate,
            )
        return result
