"""Small, dependency-light builders for MCP write arguments."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _quality() -> dict[str, Any]:
    return {"score": 1.0, "status": "accepted", "completeness": 1.0, "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []}


def build_memory_event(args: dict[str, Any], *, user_id: str, project_root: str = "") -> dict[str, Any]:
    event = dict(args.get("event") or {})
    if not event:
        event = {
            "event_id": f"evt_mcp_{_hash({str(args.get('session_id', '')), str(args.get('turn_id', '')), str(args.get('text', ''))})[:16]}",
            "source_type": str(args.get("source_type") or "user_behavior"),
            "event_type": str(args.get("event_type") or "agent_summary"),
            "user_id": str(args.get("user_id") or user_id),
            "session_id": str(args.get("session_id") or ""),
            "turn_id": str(args.get("turn_id") or ""),
            "scene": str(args.get("scene") or ""),
            "task_type": str(args.get("task_type") or ""),
            "occurred_at": str(args.get("occurred_at") or _utc_now()),
            "text": str(args.get("text") or ""),
            "payload": dict(args.get("payload") or {}),
            "tool_calls": list(args.get("tool_calls") or []),
            "schema_version": "1.1",
            "redactions": [],
            "quality": _quality(),
        }
    event.setdefault("user_id", user_id)
    event.setdefault("occurred_at", _utc_now())
    event.setdefault("schema_version", "1.1")
    event.setdefault("redactions", [])
    event.setdefault("quality", _quality())
    payload = dict(event.get("payload") or {})
    if project_root:
        payload.setdefault("project_root", project_root)
        payload.setdefault("project_name", Path(project_root).name)
    event["payload"] = payload
    seed = {key: value for key, value in event.items() if key not in {"source_hash", "quality"}}
    event["source_hash"] = _hash(seed)
    return event
