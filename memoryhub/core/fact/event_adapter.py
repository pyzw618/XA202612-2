"""把上游 MemoryEvent 契约转换为纯事实候选。"""

import json
from typing import Any, Optional

from .models import FactCandidate
from .pipeline import FactMemoryPipeline


class FactIngestionAdapter:
    """
    MemoryEvent 对接适配器。

    当前不执行质量门控、安全处理、作用域判断或正式提交。
    """

    _USABLE_STATUSES = {"success", "partial"}

    def __init__(self, pipeline: FactMemoryPipeline):
        self.pipeline = pipeline

    def propose_from_event(self, event: Any) -> list[FactCandidate]:
        event_id = str(getattr(event, "event_id", "")).strip()
        project_id_hint = self._project_id_hint(event)
        base_metadata = self._event_metadata(event)
        candidates: list[FactCandidate] = []

        event_text = str(getattr(event, "text", "") or "").strip()
        if event_text:
            candidates.extend(self.pipeline.propose(
                event_text,
                source_id=f"{event_id}:text" if event_id else "event:text",
                project_id=project_id_hint,
                metadata={**base_metadata, "content_source": "event_text"},
            ))

        for call in list(getattr(event, "tool_calls", []) or []):
            status = self._enum_value(getattr(call, "status", ""))
            if status not in self._USABLE_STATUSES:
                continue

            result = getattr(call, "result", None)
            if result in (None, "", [], {}):
                continue

            call_id = str(getattr(call, "call_id", "")).strip()
            tool_name = str(getattr(call, "tool_name", "")).strip()
            text = self.format_tool_call(call)
            candidates.extend(self.pipeline.propose(
                text,
                source_id=(
                    f"{event_id}:{call_id}"
                    if event_id and call_id
                    else f"{event_id or 'event'}:{tool_name or 'tool'}"
                ),
                project_id=project_id_hint,
                metadata={
                    **base_metadata,
                    "content_source": "tool_result",
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "tool_status": status,
                },
            ))

        return candidates


    def ingest_event(self, event: Any):
        """Propose and commit admitted facts from one already-safe event."""
        project_id = self._project_id_hint(event)
        scope = "project" if project_id else "global"
        user_id = str(getattr(event, "user_id", "") or "default")
        results = []
        for candidate in self.propose_from_event(event):
            if not candidate.admission.should_remember:
                continue
            results.append(self.pipeline.commit(
                candidate,
                scope=scope,
                project_id=project_id,
                user_id=user_id,
            ))
        return results

    @staticmethod
    def format_tool_call(call: Any) -> str:
        tool_name = str(getattr(call, "tool_name", "")).strip()
        arguments = getattr(call, "arguments", {}) or {}
        result = getattr(call, "result", None)
        parts = [f"工具名称：{tool_name or 'unknown'}"]
        if arguments:
            parts.extend((
                "调用参数：",
                FactIngestionAdapter._json_text(arguments),
            ))
        parts.extend((
            "工具返回结果：",
            FactIngestionAdapter._json_text(result),
        ))
        return "\n".join(parts)

    @staticmethod
    def _json_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    @staticmethod
    def _enum_value(value: Any) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip().lower()

    @staticmethod
    def _project_id_hint(event: Any) -> Optional[str]:
        direct = str(getattr(event, "project_id", "") or "").strip()
        if direct:
            return direct
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, dict):
            value = str(payload.get("project_id", "") or "").strip()
            return value or None
        return None

    @staticmethod
    def _event_metadata(event: Any) -> dict:
        quality = getattr(event, "quality", None)
        return {
            "event_id": str(getattr(event, "event_id", "") or ""),
            "user_id": str(getattr(event, "user_id", "") or "default"),
            "source_type": FactIngestionAdapter._enum_value(
                getattr(event, "source_type", "")
            ),
            "event_type": str(getattr(event, "event_type", "") or ""),
            "session_id": str(getattr(event, "session_id", "") or ""),
            "turn_id": str(getattr(event, "turn_id", "") or ""),
            "scene": str(getattr(event, "scene", "") or ""),
            "task_type": str(getattr(event, "task_type", "") or ""),
            "quality_score": getattr(quality, "score", None),
            "quality_status": FactIngestionAdapter._enum_value(
                getattr(quality, "status", "")
            ),
        }
