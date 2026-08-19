"""BehaviorAdapter：把用户行为序列适配为 USER_BEHAVIOR MemoryEvent（赛题要求1，I-7）。

用户行为数据（会话交互序列：消息 / 选中项 / 纠错 / 确认信号）是偏好挖掘的重要
输入（REFACTOR_PLAN_V2 §4.1.1）。本适配器把一次行为打成 ``USER_BEHAVIOR`` 事件，
携带 ``behavior_type``（如 selection / correction / confirm），供偏好提取使用。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus, SourceType


class BehaviorAdapter:
    """用户行为源适配器：行为记录 → 结构化 USER_BEHAVIOR MemoryEvent。"""

    VALID_BEHAVIOR_TYPES = {"selection", "correction", "confirm", "message", "cancel"}

    def to_event(
        self,
        behavior: dict[str, Any],
        *,
        behavior_type: str = "message",
        user_id: str = "default",
    ) -> MemoryEvent:
        """把一条用户行为记录结构化为 MemoryEvent。

        Args:
            behavior: 行为原始数据（至少含 ``text`` 或 ``payload``）。
            behavior_type: 行为类型（selection/correction/confirm/message/cancel）。
            user_id: 归属用户。

        Returns:
            source_type=USER_BEHAVIOR 的 Schema 1.1 MemoryEvent。

        Raises:
            ValueError: behavior 非 dict、类型非法或缺少可索引文本。
        """
        if not isinstance(behavior, dict):
            raise ValueError("behavior must be an object")
        if behavior_type not in self.VALID_BEHAVIOR_TYPES:
            raise ValueError(f"invalid behavior_type: {behavior_type!r}")

        text = str(behavior.get("text") or behavior.get("content") or "").strip()
        payload = dict(behavior.get("payload") or {})
        payload.setdefault("behavior_type", behavior_type)
        if not text and not payload:
            raise ValueError("behavior must provide 'text' or non-empty 'payload'")

        occurred_at = str(
            behavior.get("occurred_at") or _utc_now()
        )
        session_id = str(behavior.get("session_id") or "")
        scene = str(behavior.get("scene") or "")
        task_type = str(behavior.get("task_type") or "")

        stable_material = {
            "user_id": user_id,
            "session_id": session_id,
            "behavior_type": behavior_type,
            "text": text,
            "occurred_at": occurred_at,
            "scene": scene,
            "task_type": task_type,
        }
        source_hash = hashlib.sha256(
            json.dumps(
                stable_material, ensure_ascii=False, sort_keys=True, default=str
            ).encode("utf-8")
        ).hexdigest()
        event_id = str(
            behavior.get("event_id") or f"behavior_{source_hash[:24]}"
        )

        raw = {
            "event_id": event_id,
            "source_type": SourceType.USER_BEHAVIOR,
            "event_type": behavior_type,
            "user_id": user_id,
            "session_id": session_id,
            "turn_id": str(behavior.get("turn_id") or ""),
            "scene": scene,
            "task_type": task_type,
            "occurred_at": occurred_at,
            "text": text,
            "payload": payload,
            "schema_version": "1.1",
            "source_hash": source_hash,
            "redactions": [],
            "quality": {
                "score": 1.0,
                "status": QualityStatus.ACCEPTED.value,
                "completeness": 1.0,
                "validity": 1.0,
                "consistency": 1.0,
                "freshness": 1.0,
                "issues": [],
            },
        }
        return MemoryEvent.model_validate(raw)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
