"""MCP tool definitions and their handlers.

Each tool maps to one or more MemoryHub REST endpoints (see
``memoryhub/adapter/api.py``). Handlers return a short human-readable text
that the LLM consumes.
"""

from __future__ import annotations

from typing import Any, Callable

from .client import MemoryHubClient, MemoryHubError
from .schemas_bridge import (
    ContractError,
    build_knowledge,
    build_memory_event,
    build_preference,
)

_MEMORY_TYPES = ["preference", "knowledge", "fact"]
_TOOL_STATUS = ["success", "error", "timeout", "cancelled", "partial"]
_PREFERENCE_TYPES = [
    "output_style",
    "tool_preference",
    "workflow_preference",
    "safety_preference",
    "scene_preference",
    "format_preference",
    "language_preference",
]
_KNOWLEDGE_TYPES = ["workflow", "case", "template"]
_DECISIONS = ["override", "merge", "coexist", "pending"]
_FEEDBACK_ACTIONS = ["update", "confirm", "reject"]


def _format_write_success(label: str, result: dict[str, Any]) -> str:
    """Expose the complete, non-sensitive safety outcome of a memory write."""

    return (
        f"{label}已写入：status={result.get('status', 'unknown')} "
        f"memory_id={result.get('memory_id', 'unknown')} "
        f"safety_action={result.get('safety_action', 'unknown')} "
        f"audit_id={result.get('audit_id', 'unknown')}"
    )


def _format_write_policy_outcome(label: str, exc: MemoryHubError) -> str | None:
    """Return expected safety decisions as readable business outcomes for MCP clients."""

    if exc.safety_action not in {"reject", "review"}:
        return None
    outcome_status = exc.outcome_status or (
        "rejected" if exc.safety_action == "reject" else "review_required"
    )
    return (
        f"{label}未写入：status={outcome_status} "
        f"safety_action={exc.safety_action} "
        f"audit_id={exc.audit_id or 'unknown'} "
        f"code={exc.code} http_status={exc.status_code or 'unknown'}"
    )


def _str_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    raise ContractError(f"{name} must be a string or list of strings")


def _format_search(response: dict) -> str:
    lines: list[str] = []
    prefs = response.get("preferences") or []
    knows = response.get("knowledge") or []
    facts = response.get("facts") or []
    results = response.get("results") or []

    if prefs:
        lines.append("## 用户偏好")
        for p in prefs:
            lines.append(
                f"- [{p.get('memory_id')}] {p.get('text')} (置信度 {float(p.get('confidence', 0)):.2f}, "
                f"类型 {p.get('preference_type', '')})"
            )
    if knows:
        lines.append("## 相关知识")
        for k in knows:
            lines.append(
                f"- [{k.get('memory_id')}] {k.get('name')}: {k.get('content')} "
                f"(置信度 {float(k.get('confidence', 0)):.2f})"
            )
    if facts:
        lines.append("## 事实")
        for f in facts:
            lines.append(
                f"- [{f.get('fact_id')}] {f.get('subject_id')} {f.get('predicate_id')} "
                f"{f.get('object_value')} (置信度 {float(f.get('confidence', 0)):.2f})"
            )
    if not prefs and not knows and not facts:
        lines.append("（无匹配记忆）")
    elif results and not (prefs or knows or facts):
        lines.append("## 原始检索结果")
        for r in results:
            lines.append(
                f"- [{r.get('memory_id')}] {r.get('memory_type')}: {r.get('content')} "
                f"(score {float(r.get('score', 0)):.3f}, source {r.get('source', '')})"
            )
    lines.append(f"（延迟 {float(response.get('latency_ms', 0)):.1f} ms，共 {response.get('total_count', 0)} 条）")
    return "\n".join(lines)


def _format_memory_list(kind: str, items: list[dict]) -> str:
    if not items:
        return f"（暂无 {kind} 记忆）"
    lines = [f"共 {len(items)} 条 {kind} 记忆："]
    for m in items:
        if kind == "preference":
            lines.append(f"- [{m.get('memory_id')}] {m.get('text')} (置信度 {float(m.get('confidence', 0)):.2f}, {m.get('status')})")
        elif kind == "knowledge":
            lines.append(f"- [{m.get('memory_id')}] {m.get('name')} — {m.get('content')} (置信度 {float(m.get('confidence', 0)):.2f}, {m.get('status')})")
        else:
            lines.append(f"- [{m.get('fact_id')}] {m.get('subject_id')} {m.get('predicate_id')} {m.get('object_value')} ({m.get('status')})")
    return "\n".join(lines)


def _format_memory_detail(m: dict) -> str:
    import json

    return json.dumps(m, ensure_ascii=False, indent=2)


def _format_conflicts(items: list[dict]) -> str:
    if not items:
        return "（无待处理冲突）"
    lines = [f"共 {len(items)} 条冲突记录："]
    for c in items:
        lines.append(
            f"- [{c.get('conflict_id')}] {c.get('memory_type')} 新旧冲突: "
            f"old={c.get('old_content')!r} vs new={c.get('new_content')!r} "
            f"(decision={c.get('decision')})"
        )
    return "\n".join(lines)


class ToolRegistry:
    """Owns the tool list and dispatches ``tools/call`` to handlers."""

    def __init__(self, client: MemoryHubClient, config):
        self.client = client
        self.config = config
        self._tools: list[dict] = []
        self._handlers: dict[str, Callable[[dict], str]] = {}
        self._register()

    # ---- registration ----

    def _add(self, name: str, description: str, properties: dict, required: list[str], handler: Callable[[dict], str]) -> None:
        self._tools.append(
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            }
        )
        self._handlers[name] = handler

    def _register(self) -> None:
        default_user = self.config.user_id

        self._add(
            "memoryhub_health",
            "Check whether the MemoryHub REST service is reachable and report its base URL.",
            {},
            [],
            lambda args: self._wrap_health(),
        )

        self._add(
            "memoryhub_search",
            "Hybrid-retrieve user preferences, reusable knowledge and facts from MemoryHub. "
            "Call this before answering when the question may depend on remembered user "
            "preferences or past workflows.",
            {
                "query": {"type": "string", "description": "检索查询文本（自然语言）"},
                "top_k": {"type": "integer", "description": "返回条数，默认 5", "default": self.config.default_top_k},
                "user_id": {"type": "string", "description": "所属用户，默认取自环境", "default": default_user},
                "memory_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": _MEMORY_TYPES},
                    "description": "过滤记忆类型，默认全部",
                },
                "min_confidence": {"type": "number", "description": "最低置信度 [0,1]，默认 0"},
                "scene": {"type": "string", "description": "场景过滤，如 code / office / chat"},
                "task_type": {"type": "string", "description": "任务类型过滤，如 office.weekly_report"},
                "app": {"type": "string", "description": "来源应用过滤"},
            },
            ["query"],
            lambda args: self._wrap_search(args),
        )

        self._add(
            "memoryhub_get_context",
            "Retrieve a compact, prompt-ready memory summary (already formatted text) for "
            "injecting into the current agent context.",
            {
                "query": {"type": "string", "description": "检索查询文本"},
                "user_id": {"type": "string", "default": default_user},
                "top_k": {"type": "integer", "default": self.config.default_top_k},
                "scene": {"type": "string"},
                "task_type": {"type": "string"},
                "app": {"type": "string"},
            },
            ["query"],
            lambda args: self._wrap_context(args),
        )

        self._add(
            "memoryhub_write_event",
            "Record an agent activity event into MemoryHub. Provide tool_calls (tool_name, "
            "arguments, result, status, sequence) and the final assistant text. MemoryHub "
            "runs safety filtering and extracts preferences / knowledge / facts from it.",
            {
                "event_type": {"type": "string", "description": "事件类型，默认 agent_response / user_action"},
                "text": {"type": "string", "description": "最终回答或摘要文本"},
                "user_id": {"type": "string", "default": default_user},
                "session_id": {"type": "string"},
                "turn_id": {"type": "string"},
                "scene": {"type": "string"},
                "task_type": {"type": "string"},
                "payload": {"type": "object", "description": "结构化扩展信息"},
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_name": {"type": "string"},
                            "arguments": {"type": "object"},
                            "result": {"type": "string", "description": "工具输出（可 JSON 字符串或对象）"},
                            "status": {"type": "string", "enum": _TOOL_STATUS},
                            "sequence": {"type": "integer"},
                            "call_id": {"type": "string"},
                            "error": {"type": "string"},
                        },
                    },
                },
            },
            [],
            lambda args: self._wrap_write_event(args),
        )

        self._add(
            "memoryhub_write_preference",
            "Explicitly persist a user preference (e.g. '始终用 Markdown 生成周报'). Use "
            "this when the user states a preference that should persist.",
            {
                "text": {"type": "string", "description": "偏好自然语言描述"},
                "user_id": {"type": "string", "default": default_user},
                "preference_type": {"type": "string", "enum": _PREFERENCE_TYPES, "default": "output_style"},
                "scene": {"type": "string"},
                "task_type": {"type": "string"},
                "app": {"type": "string", "default": "opencode"},
                "is_global": {"type": "boolean", "description": "是否跨场景全局生效", "default": False},
                "confidence": {"type": "number", "description": "置信度 [0,1]", "default": 0.5},
            },
            ["text"],
            lambda args: self._wrap_write_preference(args),
        )

        self._add(
            "memoryhub_write_knowledge",
            "Explicitly persist reusable knowledge: a workflow (steps + tools), a case, or a "
            "template. Use this for procedures learned in this session.",
            {
                "name": {"type": "string", "description": "知识名称，如 '项目周报生成流程'"},
                "user_id": {"type": "string", "default": default_user},
                "knowledge_type": {"type": "string", "enum": _KNOWLEDGE_TYPES, "default": "workflow"},
                "content": {"type": "string", "description": "知识描述"},
                "steps": {"type": "array", "items": {"type": "string"}, "description": "工作流步骤（workflow 必填）"},
                "tools": {"type": "array", "items": {"type": "string"}, "description": "工具链（workflow 必填）"},
                "template_body": {"type": "string", "description": "模板正文（template 类型必填）"},
                "scene": {"type": "string"},
                "task_type": {"type": "string"},
                "app": {"type": "string", "default": "opencode"},
                "confidence": {"type": "number", "default": 0.0},
            },
            ["name"],
            lambda args: self._wrap_write_knowledge(args),
        )

        self._add(
            "memoryhub_forget",
            "Precisely forget memories. Either give a natural-language instruction (e.g. "
            "'忘掉我关于周报格式的偏好') and/or explicit memory IDs.",
            {
                "instruction": {"type": "string", "description": "自然语言遗忘指令"},
                "user_id": {"type": "string", "default": default_user},
                "target_memory_ids": {"type": "array", "items": {"type": "string"}},
                "cascade": {"type": "boolean", "description": "是否级联删除向量/证据索引", "default": True},
                "scene": {"type": "string", "description": "按场景范围遗忘"},
                "task_type": {"type": "string"},
            },
            [],
            lambda args: self._wrap_forget(args),
        )

        self._add(
            "memoryhub_list_memories",
            "List stored memories of a given type (preference / knowledge / fact), optionally "
            "filtered by scene.",
            {
                "memory_type": {"type": "string", "enum": _MEMORY_TYPES + ["all"], "default": "all"},
                "user_id": {"type": "string", "default": default_user},
                "scene": {"type": "string"},
                "status": {"type": "string", "description": "记忆状态，默认 active"},
            },
            [],
            lambda args: self._wrap_list_memories(args),
        )

        self._add(
            "memoryhub_get_memory",
            "Get one memory's full detail (including payload, evidences, versions) by ID.",
            {
                "memory_id": {"type": "string", "description": "记忆 ID（pref_*/know_*/fact 的 fact_id）"},
                "memory_type": {"type": "string", "enum": _MEMORY_TYPES, "description": "记忆类型提示"},
                "user_id": {"type": "string", "default": default_user},
            },
            ["memory_id"],
            lambda args: self._wrap_get_memory(args),
        )

        self._add(
            "memoryhub_feedback",
            "Apply user feedback to a memory: update its text, confirm (knowledge reuse) or "
            "reject (archive).",
            {
                "memory_id": {"type": "string"},
                "action": {"type": "string", "enum": _FEEDBACK_ACTIONS},
                "feedback_text": {"type": "string", "description": "update 时的更新文本"},
                "user_id": {"type": "string", "default": default_user},
            },
            ["memory_id", "action"],
            lambda args: self._wrap_feedback(args),
        )

        self._add(
            "memoryhub_list_conflicts",
            "List conflict records pending resolution between old and new memories.",
            {
                "user_id": {"type": "string", "default": default_user},
                "status": {"type": "string", "default": "pending"},
            },
            [],
            lambda args: self._wrap_list_conflicts(args),
        )

        self._add(
            "memoryhub_resolve_conflict",
            "Resolve a conflict record with a decision (override / merge / coexist / pending).",
            {
                "conflict_id": {"type": "string"},
                "decision": {"type": "string", "enum": _DECISIONS},
                "reason": {"type": "string", "description": "解决原因"},
                "result_id": {"type": "string", "description": "处理后产生的新记忆 ID（如有）"},
                "user_id": {"type": "string", "default": default_user},
            },
            ["conflict_id", "decision"],
            lambda args: self._wrap_resolve_conflict(args),
        )

    # ---- MCP surface ----

    def list(self) -> list[dict]:
        return list(self._tools)

    def call(self, name: str, arguments: dict) -> str:
        if name not in self._handlers:
            raise ContractError(f"unknown tool: {name}")
        return self._handlers[name](dict(arguments or {}))

    # ---- helpers ----

    def _search_payload(self, args: dict) -> dict:
        return {
            "user_id": str(args.get("user_id") or self.config.user_id),
            "query": str(args.get("query") or "").strip(),
            "top_k": int(args.get("top_k") or self.config.default_top_k),
            "memory_types": _str_list(args.get("memory_types"), "memory_types"),
            "min_confidence": float(args.get("min_confidence") or 0.0),
            "context": {
                "scene": str(args.get("scene") or ""),
                "task_type": str(args.get("task_type") or ""),
                "app": str(args.get("app") or ""),
            },
        }

    def _wrap_health(self) -> str:
        info = self.client.health()
        if info["reachable"]:
            return (
                f"MemoryHub 服务可达（{info['api_url']}，延迟 {info['latency_ms']} ms）。"
                f"\n可直接调用 memoryhub_search 检索、memoryhub_write_event 写入记忆。"
            )
        return f"MemoryHub 服务不可达：{info['error']}"

    def _wrap_search(self, args: dict) -> str:
        payload = self._search_payload(args)
        if not payload["query"]:
            raise ContractError("query must not be empty")
        response = self.client.search(payload)
        return _format_search(response)

    def _wrap_context(self, args: dict) -> str:
        payload = self._search_payload(args)
        if not payload["query"]:
            raise ContractError("query must not be empty")
        response = self.client.get_context(payload)
        return str(response.get("context_text") or "（无匹配记忆上下文）")

    def _wrap_write_event(self, args: dict) -> str:
        event = build_memory_event(
            event_type=str(args.get("event_type") or ""),
            text=str(args.get("text") or ""),
            user_id=str(args.get("user_id") or self.config.user_id),
            session_id=str(args.get("session_id") or ""),
            turn_id=str(args.get("turn_id") or ""),
            scene=str(args.get("scene") or ""),
            task_type=str(args.get("task_type") or ""),
            payload=args.get("payload") or None,
            tool_calls=args.get("tool_calls") or None,
        )
        result = self.client.write_events([event])
        return (
            f"事件写入完成：accepted={result.get('accepted')} rejected={result.get('rejected')} "
            f"event_ids={result.get('event_ids')} extraction_failures={result.get('extraction_failures')} "
            f"retry_tasks_enqueued={result.get('retry_tasks_enqueued')}"
        )

    def _wrap_write_preference(self, args: dict) -> str:
        memory = build_preference(
            text=str(args.get("text") or ""),
            user_id=str(args.get("user_id") or self.config.user_id),
            preference_type=str(args.get("preference_type") or "output_style"),
            scene=str(args.get("scene") or ""),
            task_type=str(args.get("task_type") or ""),
            app=str(args.get("app") or "opencode"),
            is_global=bool(args.get("is_global")),
            confidence=float(args.get("confidence") or 0.5),
        )
        try:
            result = self.client.write_preference(memory)
        except MemoryHubError as exc:
            outcome = _format_write_policy_outcome("偏好", exc)
            if outcome is not None:
                return outcome
            raise
        return _format_write_success("偏好", result)

    def _wrap_write_knowledge(self, args: dict) -> str:
        memory = build_knowledge(
            name=str(args.get("name") or ""),
            user_id=str(args.get("user_id") or self.config.user_id),
            knowledge_type=str(args.get("knowledge_type") or "workflow"),
            content=str(args.get("content") or ""),
            steps=_str_list(args.get("steps"), "steps"),
            tools=_str_list(args.get("tools"), "tools"),
            template_body=str(args.get("template_body") or ""),
            scene=str(args.get("scene") or ""),
            task_type=str(args.get("task_type") or ""),
            app=str(args.get("app") or "opencode"),
            confidence=float(args.get("confidence") or 0.0),
        )
        try:
            result = self.client.write_knowledge(memory)
        except MemoryHubError as exc:
            outcome = _format_write_policy_outcome("知识", exc)
            if outcome is not None:
                return outcome
            raise
        return _format_write_success("知识", result)

    def _wrap_forget(self, args: dict) -> str:
        scope = {}
        if args.get("scene") or args.get("task_type"):
            scope = {
                "scene": str(args.get("scene") or ""),
                "task_type": str(args.get("task_type") or ""),
                "app": "",
            }
        result = self.client.forget(
            {
                "user_id": str(args.get("user_id") or self.config.user_id),
                "instruction": str(args.get("instruction") or ""),
                "target_memory_ids": _str_list(args.get("target_memory_ids"), "target_memory_ids"),
                "cascade": bool(args.get("cascade", True)),
                "target_scope": scope or None,
            }
        )
        return (
            f"遗忘完成：record_id={result.get('record_id')} "
            f"deleted={result.get('deleted_count')} deleted_ids={result.get('deleted_ids')}"
        )

    def _wrap_list_memories(self, args: dict) -> str:
        user_id = str(args.get("user_id") or self.config.user_id)
        scene = str(args.get("scene") or "")
        memory_type = str(args.get("memory_type") or "all")
        status = str(args.get("status") or "active")
        parts: list[str] = []
        if memory_type in ("all", "preference"):
            parts.append("偏好：" + _format_memory_list("preference", self.client.list_preferences(user_id, scene, status)))
        if memory_type in ("all", "knowledge"):
            parts.append("知识：" + _format_memory_list("knowledge", self.client.list_knowledge(user_id, scene)))
        if memory_type in ("all", "fact"):
            parts.append("事实：" + _format_memory_list("fact", self.client.list_facts(user_id, status)))
        return "\n\n".join(parts)

    def _wrap_get_memory(self, args: dict) -> str:
        memory_id = str(args.get("memory_id") or "")
        user_id = str(args.get("user_id") or self.config.user_id)
        memory_type = str(args.get("memory_type") or "")
        if memory_id.startswith("know_") or memory_type == "knowledge":
            return _format_memory_detail(self.client.get_knowledge(memory_id, user_id))
        if memory_id.startswith("fact") or memory_type == "fact":
            return _format_memory_detail(self.client.get_fact(memory_id, user_id))
        return _format_memory_detail(self.client.get_preference(memory_id, user_id))

    def _wrap_feedback(self, args: dict) -> str:
        result = self.client.feedback(
            {
                "user_id": str(args.get("user_id") or self.config.user_id),
                "memory_id": str(args.get("memory_id") or ""),
                "feedback_text": str(args.get("feedback_text") or ""),
                "action": str(args.get("action") or "update"),
            }
        )
        return f"反馈已应用：action={result.get('action')} status={result.get('status')}"

    def _wrap_list_conflicts(self, args: dict) -> str:
        user_id = str(args.get("user_id") or self.config.user_id)
        status = str(args.get("status") or "pending")
        return _format_conflicts(self.client.list_conflicts(user_id, status))

    def _wrap_resolve_conflict(self, args: dict) -> str:
        result = self.client.resolve_conflict(
            str(args.get("conflict_id") or ""),
            {
                "user_id": str(args.get("user_id") or self.config.user_id),
                "decision": str(args.get("decision") or ""),
                "reason": str(args.get("reason") or ""),
                "result_id": str(args.get("result_id") or ""),
            },
        )
        return f"冲突已解决：conflict_id={result.get('conflict_id')} decision={result.get('decision')}"


def handle_tool_error(exc: Exception) -> str:
    """Turn an exception into a safe, useful tool error message."""
    if isinstance(exc, MemoryHubError):
        fields = [f"[memoryhub error {exc.code}]", exc.message]
        if exc.status_code is not None:
            fields.append(f"http_status={exc.status_code}")
        if exc.outcome_status:
            fields.append(f"status={exc.outcome_status}")
        if exc.safety_action:
            fields.append(f"safety_action={exc.safety_action}")
        if exc.audit_id:
            fields.append(f"audit_id={exc.audit_id}")
        return " ".join(fields)
    if isinstance(exc, ContractError):
        return f"[invalid input] {exc}"
    return f"[memoryhub error] unexpected failure: {type(exc).__name__}"
