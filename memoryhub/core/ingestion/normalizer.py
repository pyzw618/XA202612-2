"""
数据标准化模块

负责将不同来源的原始数据统一转化为 MemoryEvent 格式。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
    ToolCallStatus,
    canonical_sha256,
)
from memoryhub.core.ingestion.quality import QualityScorer


class DataNormalizer:
    """数据标准化器"""

    # 各数据源的字段映射表
    FIELD_MAPPINGS: dict[str, dict] = {
        "tool_result": {
            "call_id": "tool_calls[].call_id",
            "tool_name": "tool_calls[].tool_name",
            "input": "tool_calls[].arguments",
            "output": "tool_calls[].result",
            "status": "tool_calls[].status",
        },
        "user_behavior": {
            "action": "payload.action",
            "target": "payload.target",
            "value": "payload.value",
        },
        "manual_config": {
            "key": "payload.key",
            "value": "payload.value",
        },
    }

    def __init__(self, quality_scorer: QualityScorer | None = None):
        self.quality_scorer = quality_scorer or QualityScorer()

    def normalize(self, raw_data: dict, source_type: str = "") -> MemoryEvent:
        """
        将原始数据标准化为 MemoryEvent

        数据流: 清洗后数据 → normalize → MemoryEvent → 质量评分

        参数:
            raw_data: 清洗后的原始数据字典
            source_type: 来源大类；为空时根据原始字段推断

        返回:
            标准化的 MemoryEvent 实例

        处理逻辑:
            1. 将来源别名归一为 source_type
            2. 提取或推断 event_type
            3. 构造标准 payload、tool_calls 和 text
            4. 识别 scene 和 task_type
            5. 将 occurred_at 统一为 UTC 并生成 source_hash
        """
        if not isinstance(raw_data, dict):
            raise TypeError("raw_data must be a dictionary")

        detected_source = (
            SourceType(source_type)
            if source_type
            else self._detect_source_type(raw_data)
        )
        event_type = self._detect_event_type(raw_data)
        scene, task_type = self._detect_scene(raw_data)
        occurred_at = self._normalize_timestamp(
            raw_data.get("occurred_at", raw_data.get("timestamp", ""))
        )
        tool_calls = (
            self._normalize_tool_calls(raw_data)
            if detected_source is SourceType.TOOL_RESULT
            else []
        )
        text = self._extract_text(raw_data)
        payload = self._build_payload(raw_data, detected_source)
        source_hash = canonical_sha256(raw_data)
        event_id = (
            str(raw_data.get("event_id", "")).strip() or f"evt_{source_hash[:16]}"
        )

        draft = MemoryEvent(
            event_id=event_id,
            source_type=detected_source,
            event_type=event_type,
            user_id=str(raw_data.get("user_id", "")).strip(),
            session_id=str(
                raw_data.get("session_id", raw_data.get("task_id", ""))
            ).strip(),
            turn_id=str(raw_data.get("turn_id", "")).strip(),
            scene=scene,
            task_type=task_type,
            occurred_at=occurred_at,
            text=text,
            payload=payload,
            tool_calls=tool_calls,
            schema_version="1.1",
            source_hash=source_hash,
            redactions=[],
            quality=EventQuality(
                score=0.0,
                status=QualityStatus.REVIEW,
                completeness=0.0,
                validity=0.0,
                consistency=0.0,
                freshness=0.0,
                issues=["quality:pending"],
            ),
        )
        quality = self.quality_scorer.score(draft)
        payload_with_quality = draft.model_dump(mode="python")
        payload_with_quality["quality"] = quality.model_dump(mode="python")
        return MemoryEvent.model_validate(payload_with_quality)

    def _detect_source_type(self, raw_data: dict) -> SourceType:
        """从原始数据中推断来源大类。"""
        explicit = raw_data.get("source_type")
        if explicit:
            try:
                return SourceType(str(explicit).strip())
            except ValueError:
                pass

        content = raw_data.get("content")
        if raw_data.get("tool_calls") or (
            isinstance(content, dict)
            and (content.get("tool_calls") or content.get("tool_name"))
        ):
            return SourceType.TOOL_RESULT
        if raw_data.get("source") == "manual" or (
            isinstance(content, dict) and "key" in content and "value" in content
        ):
            return SourceType.MANUAL_CONFIG
        return SourceType.USER_BEHAVIOR

    def _detect_event_type(self, raw_data: dict) -> str:
        """从原始数据中推断来源内的具体事件类型。"""
        explicit = str(raw_data.get("event_type", "")).strip()
        if explicit:
            aliases = {
                "tool_call": "tool_result",
                "user_action": "user_action",
                "feedback": "user_feedback",
            }
            return aliases.get(explicit, explicit)
        source_type = self._detect_source_type(raw_data)
        if source_type is SourceType.TOOL_RESULT:
            return "tool_result"
        if source_type is SourceType.MANUAL_CONFIG:
            return "manual_config"
        return "user_action"

    def _detect_scene(self, raw_data: dict) -> tuple[str, str]:
        """
        识别场景和任务类型

        返回:
            (scene, task_type)，如 ("office", "office.weekly_report")
        """
        scene = str(raw_data.get("scene", "")).strip().lower()
        task_type = (
            str(raw_data.get("task_type", raw_data.get("task", ""))).strip().lower()
        )
        text = self._extract_text(raw_data)

        if not scene:
            if any(word in text for word in ("周报", "报告", "文档")):
                scene = "office"
            elif any(word in text.lower() for word in ("代码", "debug", "编程")):
                scene = "code"
            else:
                scene = "chat"
        if not task_type:
            task_type = "weekly_report" if "周报" in text else "general"
        if "." not in task_type:
            task_type = f"{scene}.{task_type}"
        return scene, task_type

    def batch_normalize(
        self, raw_data_list: list[dict], source_type: str = ""
    ) -> list[MemoryEvent]:
        """批量标准化"""
        return [self.normalize(raw_data, source_type) for raw_data in raw_data_list]

    def _normalize_tool_calls(self, raw_data: dict[str, Any]) -> list[dict[str, Any]]:
        content = raw_data.get("content")
        calls = raw_data.get("tool_calls")
        if calls is None and isinstance(content, dict):
            calls = content.get("tool_calls")
            if calls is None and content.get("tool_name"):
                calls = [content]
        if not isinstance(calls, list):
            return []

        normalized = []
        status_aliases = {
            "ok": ToolCallStatus.SUCCESS.value,
            "completed": ToolCallStatus.SUCCESS.value,
            "failed": ToolCallStatus.ERROR.value,
            "failure": ToolCallStatus.ERROR.value,
        }
        for index, call in enumerate(calls, start=1):
            if not isinstance(call, dict):
                continue
            tool_name = str(call.get("tool_name", call.get("name", ""))).strip()
            if not tool_name:
                continue
            arguments = call.get("arguments", call.get("args", call.get("input", {})))
            if not isinstance(arguments, dict):
                arguments = {"input": arguments}
            result = call.get("result", call.get("output"))
            raw_status = str(call.get("status", "success")).strip().lower()
            status = status_aliases.get(raw_status, raw_status)
            if status not in {item.value for item in ToolCallStatus}:
                status = ToolCallStatus.ERROR.value
            call_seed = {
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result,
                "sequence": index,
            }
            normalized.append(
                {
                    "call_id": str(call.get("call_id", call.get("id", ""))).strip()
                    or f"call_{canonical_sha256(call_seed)[:12]}",
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "status": status,
                    "sequence": index,
                    "error": str(call.get("error", "")).strip(),
                }
            )
        return normalized

    def _build_payload(
        self,
        raw_data: dict[str, Any],
        source_type: SourceType,
    ) -> dict[str, Any]:
        payload = raw_data.get("payload")
        result = dict(payload) if isinstance(payload, dict) else {}
        content = raw_data.get("content")
        if isinstance(content, dict):
            excluded = {
                "answer",
                "final_answer",
                "text",
                "tool_calls",
                "tool_name",
                "input",
                "output",
                "status",
            }
            result.update(
                {key: value for key, value in content.items() if key not in excluded}
            )
        metadata = raw_data.get("metadata")
        if isinstance(metadata, dict) and metadata:
            result["metadata"] = metadata
        source_app = str(raw_data.get("source", "")).strip()
        if source_app:
            result["source_app"] = source_app

        if source_type is SourceType.TOOL_RESULT:
            result.setdefault("response_status", "success")
        elif source_type is SourceType.USER_BEHAVIOR:
            result.setdefault("action", str(raw_data.get("action", "message")))
        elif source_type is SourceType.MANUAL_CONFIG and isinstance(content, dict):
            result.setdefault("key", content.get("key", ""))
            result.setdefault("value", content.get("value"))
        return result

    @staticmethod
    def _extract_text(raw_data: dict[str, Any]) -> str:
        direct = raw_data.get("text")
        if isinstance(direct, str) and direct:
            return direct.strip()
        content = raw_data.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, dict):
            for key in ("answer", "final_answer", "text", "message"):
                value = content.get(key)
                if isinstance(value, str) and value:
                    return value.strip()
        return ""

    @staticmethod
    def _normalize_timestamp(value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(value, tz=timezone.utc)
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                return ""
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
