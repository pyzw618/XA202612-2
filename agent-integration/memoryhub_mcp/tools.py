"""The deliberately small MCP tool surface; everything else is CLI-first."""

from __future__ import annotations

import json
from typing import Any, Callable

from memoryhub_client import MemoryHubClient, MemoryHubError

from .config import McpConfig
from .schemas_bridge import build_memory_event


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _error(exc: Exception) -> str:
    if isinstance(exc, MemoryHubError):
        return _json({"error": exc.as_dict()})
    return _json({"error": {"code": "memoryhub.mcp.error", "message": str(exc)}})


class ToolRegistry:
    """Register only high-frequency tools; low-frequency operations stay in CLI."""

    def __init__(self, client: MemoryHubClient, config: McpConfig) -> None:
        self.client = client
        self.config = config
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._tools: list[dict[str, Any]] = []
        self._register()

    def _add(self, name: str, description: str, properties: dict[str, Any], required: list[str], handler) -> None:
        self._tools.append({"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": True}})
        self._handlers[name] = handler

    def _register(self) -> None:
        common = {"user_id": {"type": "string", "default": self.config.user_id}, "scene": {"type": "string"}, "task_type": {"type": "string"}, "project_id": {"type": "string"}}
        self._add("memoryhub_health", "Check whether the MemoryHub service is reachable.", {}, [], lambda _: self.client.health())
        self._add("memoryhub_search", "Search preference, knowledge and fact memories.", {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}, "level": {"type": "string", "enum": ["short", "mid", "long", ""]}, **common}, ["query"], self._search)
        self._add("memoryhub_get_context", "Get prompt-ready memory context for the current task.", {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}, "level": {"type": "string", "enum": ["short", "mid", "long", ""]}, **common}, ["query"], self._context)
        self._add("memoryhub_write_event", "Write one or more canonical MemoryEvent records.", {"event": {"type": "object"}, "events": {"type": "array"}, "text": {"type": "string"}, "event_type": {"type": "string"}, "session_id": {"type": "string"}, "turn_id": {"type": "string"}}, [], self._write_event)
        self._add("memoryhub_resume_task", "Resume a task by task_id using the vNext resume endpoint.", {"task_id": {"type": "string"}, "resume_token": {"type": "string"}, "expected_version": {"type": "integer"}, **common}, ["task_id"], self._resume_task)
        self._add("memoryhub_remember", "Explicitly remember a preference or knowledge item.", {"text": {"type": "string"}, "memory_type": {"type": "string", "enum": ["preference", "workflow", "case", "template", "fact", "knowledge", "knowledge:fact"]}, "name": {"type": "string"}, **common}, ["text"], self._remember)
        self._add("memoryhub_forget", "Preview or execute precise forgetting; preview is the safe default.", {"instruction": {"type": "string"}, "preview": {"type": "boolean", "default": True}, "confirm": {"type": "boolean", "default": False}, "cascade": {"type": "boolean", "default": True}, "user_id": common["user_id"]}, ["instruction"], self._forget)
        self._add("memoryhub_feedback", "Confirm, reject or update a memory after use.", {"memory_id": {"type": "string"}, "action": {"type": "string", "enum": ["confirm", "reject", "update"]}, "feedback_text": {"type": "string"}, "user_id": common["user_id"]}, ["memory_id", "action"], self._feedback)
        self._add("memoryhub_vnext_feedback", "Record attributed vNext usage or task feedback.", {"retrieval_id": {"type": "string"}, "memory_ids": {"type": "array", "items": {"type": "string"}}, "feedback_id": {"type": "string"}, "feedback_type": {"type": "string", "enum": ["EXPLICIT_POSITIVE", "EXPLICIT_NEGATIVE", "TASK_SUCCESS", "TASK_FAILURE", "PARTIAL_SUCCESS", "USER_CORRECTION", "USER_CONFIRMATION", "UNKNOWN"]}, "outcome": {"type": "string"}, "project_id": {"type": "string"}, "task_id": {"type": "string"}, "session_id": {"type": "string"}, **common}, ["retrieval_id", "feedback_id", "feedback_type"], self._vnext_feedback)
        self._add("memoryhub_knowledge_fact_propose", "Submit fact triples through the knowledge compatibility endpoint.", {"triples": {"type": "array"}, "source_id": {"type": "string"}, "scope": {"type": "string"}, "project_id": common["project_id"]}, ["triples"], self._fact_propose)
        self._add("memoryhub_decide_facts", "Resolve a pending fact conflict or entity decision.", {"memory_id": {"type": "string"}, "action": {"type": "string", "enum": ["replace", "keep_old", "merge", "coexist", "select_existing", "create_new", "reject"]}, "subject": {"type": "string"}, "predicate": {"type": "string"}, "object_value": {"type": "string"}, "subject_id": {"type": "string"}, "predicate_id": {"type": "string"}, "object_id": {"type": "string"}, "scope": {"type": "string", "enum": ["global", "project"]}, "project_id": {"type": "string"}, "create_new_subject": {"type": "boolean"}, "create_new_predicate": {"type": "boolean"}, "create_new_object": {"type": "boolean"}, "expected_version": {"type": "integer"}, "reason": {"type": "string"}, "user_id": common["user_id"]}, ["memory_id", "action"], self._fact_decide)

    def list(self) -> list[dict[str, Any]]:
        return list(self._tools)

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name not in self._handlers:
            return _json({"error": {"code": "memoryhub.mcp.unknown_tool", "message": name}})
        try:
            return _json(self._handlers[name](dict(args or {})))
        except Exception as exc:  # noqa: BLE001
            return _error(exc)

    def _payload(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.build_search_payload(user_id=str(args.get("user_id") or self.config.user_id), query=str(args.get("query") or ""), top_k=int(args.get("top_k") or 5), scene=str(args.get("scene") or ""), task_type=str(args.get("task_type") or ""), app="memoryhub-mcp", project_id=str(args.get("project_id") or ""), level=str(args.get("level") or ""), session_id=str(args.get("session_id") or ""))

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.search(self._payload(args))

    def _context(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.get_context(self._payload(args))

    def _write_event(self, args: dict[str, Any]) -> dict[str, Any]:
        events = args.get("events")
        if not isinstance(events, list):
            events = [build_memory_event(args, user_id=self.config.user_id, project_root=self.config.project_root)]
        return self.client.write_canonical_events(
            [dict(event) for event in events],
            tenant_id=self.config.tenant_id,
            user_id=self.config.user_id,
        )

    def _resume_task(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.resume_task(
            str(args.get("task_id") or ""),
            tenant_id=self.config.tenant_id,
            user_id=str(args.get("user_id") or self.config.user_id),
            resume_token=str(args.get("resume_token") or ""),
            expected_snapshot_version=args.get("expected_version"),
        )

    def _remember(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.remember(str(args.get("text") or ""), memory_type=str(args.get("memory_type") or "preference"), user_id=str(args.get("user_id") or self.config.user_id), scene=str(args.get("scene") or ""), task_type=str(args.get("task_type") or ""), project_id=str(args.get("project_id") or ""), name=str(args.get("name") or ""))

    def _forget(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = {"user_id": str(args.get("user_id") or self.config.user_id), "instruction": str(args.get("instruction") or ""), "cascade": bool(args.get("cascade", True))}
        if bool(args.get("preview", True)) or not bool(args.get("confirm", False)):
            return self.client.forget_preview(payload)
        return self.client.forget(payload)

    def _feedback(self, args: dict[str, Any]) -> dict[str, Any]:
        return self.client.feedback({"user_id": str(args.get("user_id") or self.config.user_id), "memory_id": str(args.get("memory_id") or ""), "action": str(args.get("action") or "confirm"), "feedback_text": str(args.get("feedback_text") or "")})

    def _vnext_feedback(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "feedback_id": str(args.get("feedback_id") or ""),
            "retrieval_id": str(args.get("retrieval_id") or ""),
            "memory_ids": [str(value) for value in args.get("memory_ids", [])],
            "feedback_type": str(args.get("feedback_type") or "UNKNOWN"),
            "outcome": str(args.get("outcome") or "UNKNOWN"),
            "project_id": str(args.get("project_id") or ""),
            "task_id": str(args.get("task_id") or ""),
            "session_id": str(args.get("session_id") or ""),
            "source": "mcp",
        }
        return self.client.vnext_feedback(
            payload,
            tenant_id=self.config.tenant_id,
            user_id=str(args.get("user_id") or self.config.user_id),
        )

    def _fact_propose(self, args: dict[str, Any]) -> Any:
        return self.client.propose_knowledge_fact(list(args.get("triples") or []), source_id=str(args.get("source_id") or ""), scope_hint=str(args.get("scope") or "global"), project_id=str(args.get("project_id") or "") or None)

    def _fact_decide(self, args: dict[str, Any]) -> Any:
        payload = {key: args[key] for key in ("subject", "predicate", "object_value", "subject_id", "predicate_id", "object_id", "scope", "project_id", "create_new_subject", "create_new_predicate", "create_new_object", "expected_version", "reason") if args.get(key) is not None}
        return self.client.decide_fact(str(args.get("memory_id") or ""), action=str(args.get("action") or ""), user_id=str(args.get("user_id") or self.config.user_id), payload=payload)
