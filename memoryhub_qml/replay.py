from __future__ import annotations

import copy
import json
import re
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
TOKEN = re.compile(r"\b(?:sk|Bearer)[-_ A-Za-z0-9]{10,}\b", re.IGNORECASE)
MEMORY_TOOLS = {
    "preference_extract",
    "preference_propose",
    "fact_propose",
    "conflict_detect",
    "template_extract",
}


class ReplayError(ValueError):
    pass


def mask_for_display(value: Any) -> Any:
    if isinstance(value, str):
        return TOKEN.sub(
            "[REDACTED_TOKEN]", PHONE.sub("[REDACTED_PHONE]", EMAIL.sub("[REDACTED_EMAIL]", value))
        )
    if isinstance(value, list):
        return [mask_for_display(item) for item in value]
    if isinstance(value, dict):
        return {str(key): mask_for_display(item) for key, item in value.items()}
    return value


def _normalize_tool_calls(raw_calls: Any, turn_id: str) -> list[dict[str, Any]]:
    if raw_calls is None:
        return []
    if not isinstance(raw_calls, list):
        raise ReplayError(f"回合 {turn_id} 的 tool_calls 必须是数组")

    calls: list[dict[str, Any]] = []
    ids: set[str] = set()
    last_sequence = -1
    for index, raw in enumerate(raw_calls):
        if not isinstance(raw, dict):
            raise ReplayError(f"回合 {turn_id} 的第 {index + 1} 个工具调用必须是对象")
        call_id = str(raw.get("call_id") or f"{turn_id}_call_{index + 1}")
        if call_id in ids:
            raise ReplayError(f"回合 {turn_id} 存在重复 call_id: {call_id}")
        ids.add(call_id)
        try:
            sequence = int(raw.get("sequence", index + 1))
        except (TypeError, ValueError) as exc:
            raise ReplayError(f"回合 {turn_id} 的工具 sequence 必须是整数") from exc
        if sequence <= last_sequence:
            raise ReplayError(f"回合 {turn_id} 的工具 sequence 必须严格递增")
        last_sequence = sequence
        calls.append(
            {
                "call_id": call_id,
                "tool_name": str(raw.get("tool_name") or raw.get("name") or "unknown_tool"),
                "arguments": mask_for_display(raw.get("arguments") or {}),
                "result": mask_for_display(raw.get("result") or {}),
                "status": str(raw.get("status") or "success"),
                "sequence": sequence,
                "latency_ms": int(raw.get("latency_ms") or 0),
                "error": str(mask_for_display(raw.get("error") or "")),
            }
        )
    return calls


def _normalize_turn(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ReplayError(f"第 {index + 1} 个回合必须是对象")
    turn_id = str(raw.get("turn_id") or "").strip()
    if not turn_id:
        raise ReplayError(f"第 {index + 1} 个回合缺少 turn_id")
    events = mask_for_display(raw.get("events") or [])
    if not isinstance(events, list):
        raise ReplayError(f"回合 {turn_id} 的 events 必须是数组")
    event_calls = [
        call for event in events if isinstance(event, dict) for call in event.get("tool_calls", [])
    ]
    return {
        "turn_id": turn_id,
        "user_message": str(mask_for_display(raw.get("user_message") or raw.get("user") or "")),
        "retrieval_query": str(mask_for_display(raw.get("retrieval_query") or "")),
        "assistant_message": str(
            mask_for_display(raw.get("assistant_message") or raw.get("assistant") or "")
        ),
        "occurred_at": str(raw.get("occurred_at") or ""),
        "tool_calls": _normalize_tool_calls(raw.get("tool_calls", event_calls), turn_id),
        "candidate_memories": mask_for_display(raw.get("candidate_memories") or []),
        "used_memory_ids": [str(item) for item in raw.get("used_memory_ids") or []],
        "fact_proposals": mask_for_display(raw.get("fact_proposals") or []),
        "write_summary": [str(item) for item in raw.get("write_summary") or []],
        "latency_ms": int(raw.get("latency_ms") or 0),
        "events": events,
    }


def _turns_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for event in events:
        if not isinstance(event, dict):
            raise ReplayError("events 中的每个事件都必须是对象")
        turn_id = str(event.get("turn_id") or "").strip()
        if not turn_id:
            raise ReplayError(f"事件 {event.get('event_id', '<unknown>')} 缺少 turn_id")
        groups.setdefault(turn_id, []).append(event)

    turns = []
    for index, (turn_id, grouped) in enumerate(groups.items()):
        user_event = next(
            (item for item in grouped if item.get("event_type") == "user_message"), {}
        )
        assistant_event = next(
            (
                item
                for item in reversed(grouped)
                if item.get("event_type") in {"assistant_reply", "agent_response"}
            ),
            {},
        )
        payload = (
            assistant_event.get("payload")
            if isinstance(assistant_event.get("payload"), dict)
            else {}
        )
        turns.append(
            _normalize_turn(
                {
                    "turn_id": turn_id,
                    "user_message": user_event.get("text")
                    or payload.get("user_message")
                    or "导入的用户消息",
                    "assistant_message": assistant_event.get("text") or "",
                    "occurred_at": grouped[0].get("occurred_at") or "",
                    "events": grouped,
                    "tool_calls": [
                        call for event in grouped for call in event.get("tool_calls", [])
                    ],
                    "used_memory_ids": payload.get("used_memory_ids") or [],
                    "candidate_memories": payload.get("candidate_memories") or [],
                    "fact_proposals": payload.get("fact_proposals") or [],
                    "write_summary": payload.get("write_summary") or [],
                    "latency_ms": payload.get("latency_ms") or 0,
                },
                index,
            )
        )
    return turns


def parse_replay(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayError("JSON 顶层必须是对象")
    if value.get("schema_version") not in (None, "conversation-replay/1.0"):
        raise ReplayError("仅支持 conversation-replay/1.0")
    events = mask_for_display(value.get("events") or [])
    if not isinstance(events, list):
        raise ReplayError("events 必须是数组")
    turns_raw = value.get("turns")
    turns = (
        [_normalize_turn(turn, index) for index, turn in enumerate(turns_raw)]
        if isinstance(turns_raw, list)
        else _turns_from_events(events)
    )
    if not turns:
        raise ReplayError("JSON 中没有可执行的 turns 或 events")
    session_id = str(
        value.get("session_id")
        or (events[0].get("session_id") if events else "")
        or f"import_{uuid.uuid4().hex[:8]}"
    )
    return {
        "schema_version": "conversation-replay/1.0",
        "session_id": session_id,
        "title": str(value.get("title") or "导入的 Agent 对话"),
        "source": "json",
        "read_only": False,
        "turns": turns,
        "events": events,
    }


def load_replay(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReplayError(f"JSON 第 {exc.lineno} 行第 {exc.colno} 列格式错误") from exc
    except (OSError, UnicodeError) as exc:
        raise ReplayError(f"无法读取文件：{exc}") from exc
    return parse_replay(value)


def freshen_session(session: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(session)
    run_id = uuid.uuid4().hex[:10]
    session_id = f"{result['session_id']}_{run_id}"
    # 演示适配层：user_id 固定为 demo_user，避免每次载入/重启都生成新用户，
    # 否则此前写入的偏好记忆会挂在旧用户下、偏好页查询不到。
    # event_id/session_id 仍带随机 run_id，保证重复执行不触发事件去重。
    user_id = "demo_user"
    result["session_id"] = session_id
    result["source"] = "sample"
    result["read_only"] = False
    for event in result.get("events", []):
        event["event_id"] = f"{event.get('event_id', 'event')}_{run_id}"
        event["session_id"] = session_id
        event["user_id"] = user_id
    for turn in result.get("turns", []):
        for event in turn.get("events", []):
            event["event_id"] = f"{event.get('event_id', 'event')}_{run_id}"
            event["session_id"] = session_id
            event["user_id"] = user_id
    return result


def external_tool_calls(turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        copy.deepcopy(call)
        for call in turn.get("tool_calls", [])
        if not str(call.get("tool_name", "")).startswith("memory_")
        and str(call.get("tool_name", "")) not in MEMORY_TOOLS
    ]
