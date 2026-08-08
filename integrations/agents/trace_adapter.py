"""Convert LangChain/LangGraph messages into MemoryEvent 1.1 payloads."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _source_hash(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _quality() -> dict[str, Any]:
    return {
        "score": 1.0,
        "status": "accepted",
        "completeness": 1.0,
        "validity": 1.0,
        "consistency": 1.0,
        "freshness": 1.0,
        "issues": [],
    }


def build_user_event(
    user_input: str,
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    scene: str,
    task_type: str,
) -> dict[str, Any]:
    payload = {
        "action": "message",
        "role": "user",
        "app": "qwen_langgraph_agent",
    }
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "scene": scene,
        "task_type": task_type,
        "occurred_at": _utc_now(),
        "text": user_input,
        "payload": payload,
        "tool_calls": [],
        "schema_version": "1.1",
        "redactions": [],
        "quality": _quality(),
    }
    event["source_hash"] = _source_hash(event)
    return event


def build_agent_event(
    messages: Iterable[Any],
    *,
    user_id: str,
    session_id: str,
    turn_id: str,
    scene: str,
    task_type: str,
    model: str,
) -> dict[str, Any] | None:
    message_list = list(messages)
    results = _tool_results(message_list)
    tool_calls: list[dict[str, Any]] = []
    sequence = 1

    for message in message_list:
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:12]}")
            result = results.get(call_id, {})
            tool_calls.append(
                {
                    "call_id": call_id,
                    "tool_name": str(call.get("name", "unknown_tool")),
                    "arguments": call.get("args") or {},
                    "result": result.get("content"),
                    "status": result.get("status", "success"),
                    "sequence": sequence,
                    "error": result.get("error", ""),
                }
            )
            sequence += 1

    if not tool_calls:
        return None

    final_answer = extract_final_answer(message_list)
    event = {
        "event_id": f"evt_{uuid.uuid4().hex[:16]}",
        "source_type": "tool_result",
        "event_type": "agent_response",
        "user_id": user_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "scene": scene,
        "task_type": task_type,
        "occurred_at": _utc_now(),
        "text": final_answer or "Agent 已完成工具调用。",
        "payload": {
            "response_status": "success",
            "provider": "dashscope",
            "model": model,
        },
        "tool_calls": tool_calls,
        "schema_version": "1.1",
        "redactions": [],
        "quality": _quality(),
    }
    event["source_hash"] = _source_hash(event)
    return event


def extract_final_answer(messages: Iterable[Any]) -> str:
    for message in reversed(list(messages)):
        message_type = getattr(message, "type", "")
        if message_type in {"ai", "assistant"} and not (
            getattr(message, "tool_calls", None) or []
        ):
            content = getattr(message, "content", "")
            return _content_to_text(content)
    return ""


def _tool_results(messages: list[Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for message in messages:
        call_id = getattr(message, "tool_call_id", None)
        if not call_id:
            continue
        raw_content = getattr(message, "content", None)
        status = getattr(message, "status", "success") or "success"
        if status not in {"success", "error", "timeout", "cancelled", "partial"}:
            status = "success"
        results[str(call_id)] = {
            "content": _parse_content(raw_content),
            "status": status,
            "error": _content_to_text(raw_content) if status == "error" else "",
        }
    return results


def _parse_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")
