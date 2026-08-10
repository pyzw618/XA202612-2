"""Build and validate MemoryHub payloads with the real Pydantic contracts.

Imports ``memoryhub.adapter.schemas`` from the repo so every event written
through the MCP server is validated against the same rules the REST API
enforces (tool_call ordering, ``occurred_at`` format, ``agent_response``
requirements, ``source_hash`` shape, ...). If the repo is unavailable the
bridge degrades to a manual, best-effort constructor.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


class ContractError(ValueError):
    """A MemoryHub schema contract check failed (message is user-facing)."""


_MEMORYHUB_IMPORTED = False


def ensure_memoryhub(repo_root: str) -> None:
    """Add the repo to ``sys.path`` so ``memoryhub.adapter.schemas`` resolves."""
    global _MEMORYHUB_IMPORTED
    if _MEMORYHUB_IMPORTED:
        return
    import importlib.util
    import sys

    try:
        if importlib.util.find_spec("memoryhub.adapter.schemas") is not None:
            _MEMORYHUB_IMPORTED = True
            return
    except (ImportError, AttributeError):
        pass

    if repo_root and repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        import memoryhub.adapter.schemas  # noqa: F401
        _MEMORYHUB_IMPORTED = True
    except ImportError:
        _MEMORYHUB_IMPORTED = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _source_hash(seed: dict) -> str:
    canonical = json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _default_quality() -> dict:
    return {
        "score": 1.0,
        "status": "accepted",
        "completeness": 1.0,
        "validity": 1.0,
        "consistency": 1.0,
        "freshness": 1.0,
        "issues": [],
    }


def build_memory_event(
    *,
    event_type: str,
    text: str = "",
    user_id: str = "default",
    session_id: str = "",
    turn_id: str = "",
    scene: str = "",
    task_type: str = "",
    occurred_at: str = "",
    payload: dict | None = None,
    tool_calls: list[dict] | None = None,
) -> dict:
    """Construct a validated ``MemoryEvent`` payload ready for ``POST /events``.

    ``tool_calls`` entries accept ``tool_name``, ``arguments``, ``result``,
    ``status`` (success/error/timeout/cancelled/partial), ``sequence`` and
    optional ``call_id``/``error``.
    """
    calls = list(tool_calls or [])
    has_calls = bool(calls)

    prepared_calls: list[dict] = []
    for index, call in enumerate(calls, start=1):
        if not isinstance(call, dict) or not call.get("tool_name"):
            raise ContractError(f"tool_calls[{index}] must be an object with a non-empty tool_name")
        prepared_calls.append(
            {
                "call_id": call.get("call_id") or f"call_{uuid.uuid4().hex[:12]}",
                "tool_name": call["tool_name"],
                "arguments": call.get("arguments") or {},
                "result": call.get("result"),
                "status": call.get("status") or "success",
                "sequence": call.get("sequence") or index,
                "error": call.get("error") or "",
            }
        )

    if not event_type.strip():
        event_type = "agent_response" if has_calls else "user_action"

    seed_fields = {
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "source_type": "tool_result" if has_calls else "user_behavior",
        "event_type": event_type,
        "user_id": user_id or "default",
        "session_id": session_id,
        "turn_id": turn_id,
        "scene": scene,
        "task_type": task_type,
        "occurred_at": occurred_at or _utc_now(),
        "text": text,
        "payload": payload if payload is not None else ({} if has_calls else {"action": "agent_activity"}),
        "tool_calls": prepared_calls,
    }
    event = {
        **seed_fields,
        "schema_version": "1.1",
        "source_hash": _source_hash(seed_fields),
        "redactions": [],
        "quality": _default_quality(),
    }

    if _MEMORYHUB_IMPORTED:
        from memoryhub.adapter.schemas import MemoryEvent

        try:
            validated = MemoryEvent.model_validate(event)
        except Exception as exc:  # pydantic ValidationError
            raise ContractError(f"MemoryEvent contract violation: {exc}") from exc
        return validated.model_dump(mode="json")
    return event


def build_preference(
    *,
    text: str,
    user_id: str = "default",
    preference_type: str = "output_style",
    scene: str = "",
    task_type: str = "",
    app: str = "opencode",
    is_global: bool = False,
    confidence: float = 0.5,
) -> dict:
    """Construct a ``PreferenceMemory`` payload for ``POST /memories/preference``."""
    if not text.strip():
        raise ContractError("preference text must not be empty")
    memory = {
        "user_id": user_id or "default",
        "preference_type": preference_type,
        "text": text,
        "scope": {"scene": scene, "task_type": task_type, "app": app},
        "is_global": bool(is_global),
        "confidence": float(confidence),
    }
    if _MEMORYHUB_IMPORTED:
        from memoryhub.adapter.schemas import PreferenceMemory

        try:
            validated = PreferenceMemory.model_validate(memory)
        except Exception as exc:
            raise ContractError(f"PreferenceMemory contract violation: {exc}") from exc
        return validated.model_dump(mode="json")
    return memory


def build_knowledge(
    *,
    name: str,
    user_id: str = "default",
    knowledge_type: str = "workflow",
    content: str = "",
    steps: list[str] | None = None,
    tools: list[str] | None = None,
    template_body: str = "",
    scene: str = "",
    task_type: str = "",
    app: str = "opencode",
    confidence: float = 0.0,
) -> dict:
    """Construct a ``KnowledgeMemory`` payload for ``POST /memories/knowledge``."""
    if not name.strip():
        raise ContractError("knowledge name must not be empty")
    memory = {
        "user_id": user_id or "default",
        "knowledge_type": knowledge_type,
        "name": name,
        "content": content,
        "steps": list(steps or []),
        "tools": list(tools or []),
        "template_body": template_body,
        "scope": {"scene": scene, "task_type": task_type, "app": app},
        "confidence": float(confidence),
    }
    if _MEMORYHUB_IMPORTED:
        from memoryhub.adapter.schemas import KnowledgeMemory

        try:
            validated = KnowledgeMemory.model_validate(memory)
        except Exception as exc:
            raise ContractError(f"KnowledgeMemory contract violation: {exc}") from exc
        return validated.model_dump(mode="json")
    return memory
