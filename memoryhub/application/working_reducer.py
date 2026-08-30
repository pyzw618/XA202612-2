"""Deterministic reduction of canonical Agent events into Working State patches."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from memoryhub.domain.contracts import (
    MemoryEventContract,
    WorkingPatch,
    WorkingPatchOperation,
    WorkingSnapshot,
)
from memoryhub.domain.working import apply_operations


class WorkingStateReducer:
    """Translate known event and tool-trace facts into compact task state.

    The reducer deliberately handles only deterministic, high-frequency Agent
    events.  It keeps tool output out of Working State and records concise
    action/result summaries instead.
    """

    _LIST_FIELDS = (
        "pending_steps",
        "completed_steps",
        "constraints",
        "active_entities",
        "blockers",
        "recent_findings",
        "recent_failures",
    )
    _TEXT_FIELDS = ("current_step", "next_action")
    _SUCCESS = frozenset({"success", "succeeded", "completed", "ok", "passed"})
    _FAILURE = frozenset({"error", "failed", "failure", "cancelled", "canceled"})
    _READ_NAMES = frozenset({"read", "read_file", "cat", "view", "view_file"})
    _WRITE_NAMES = frozenset({"write", "write_file", "edit", "patch", "apply_patch"})
    _SEARCH_NAMES = frozenset({"search", "grep", "glob", "find"})
    _TEST_MARKERS = ("test", "pytest", "unittest", "mvn test", "gradle test")

    def initial_snapshot(self, event: MemoryEventContract) -> WorkingSnapshot:
        """Build the first task snapshot from one accepted canonical event."""

        payload = event.payload or {}
        state: dict[str, Any] = {
            "current_goal": self._first_text(
                payload, "current_goal", "goal", "instruction", "text"
            )
            or event.event_type,
            "current_step": "",
            "pending_steps": [],
            "completed_steps": [],
            "constraints": [],
            "active_entities": [],
            "blockers": [],
            "recent_findings": [],
            "recent_failures": [],
            "next_action": "",
        }
        application = apply_operations(state, self.operations(event, state))
        reduced = application.state
        return WorkingSnapshot(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            task_id=event.task_id,
            session_id=event.session_id,
            current_goal=str(reduced["current_goal"]),
            current_step=str(reduced["current_step"]),
            pending_steps=self._as_strings(reduced["pending_steps"]),
            completed_steps=self._as_strings(reduced["completed_steps"]),
            constraints=self._as_strings(reduced["constraints"]),
            active_entities=self._as_strings(reduced["active_entities"]),
            blockers=self._as_strings(reduced["blockers"]),
            recent_findings=self._as_strings(reduced["recent_findings"]),
            recent_failures=self._as_strings(reduced["recent_failures"]),
            next_action=str(reduced["next_action"]),
        )

    def patch(
        self,
        event: MemoryEventContract,
        current_state: Mapping[str, Any],
        *,
        base_version: int,
    ) -> WorkingPatch | None:
        """Return a patch for an existing state, or ``None`` for a no-op."""

        operations = self.operations(event, current_state)
        if not operations:
            return None
        return WorkingPatch(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            task_id=event.task_id,
            base_version=base_version,
            operations=operations,
            event_refs=[event.event_id],
            reason="canonical_tool_trace_reduction",
        )

    def operations(
        self,
        event: MemoryEventContract,
        current_state: Mapping[str, Any],
    ) -> list[WorkingPatchOperation]:
        """Produce field operations without performing storage or model work."""

        payload = event.payload or {}
        operations = self._payload_operations(payload)
        operations.extend(self._tool_operations(payload, current_state))
        operations.extend(self._terminal_operations(event, current_state))
        return operations

    def _payload_operations(self, payload: Mapping[str, Any]) -> list[WorkingPatchOperation]:
        operations: list[WorkingPatchOperation] = []
        for field in self._TEXT_FIELDS:
            if field in payload:
                operations.append(
                    WorkingPatchOperation(
                        op="replace",
                        path=f"/{field}",
                        value=str(payload[field] or ""),
                        source="event",
                    )
                )
        for field in self._LIST_FIELDS:
            if field in payload:
                operations.append(
                    WorkingPatchOperation(
                        op="replace",
                        path=f"/{field}",
                        value=self._as_strings(payload[field]),
                        source="event",
                    )
                )
        return operations

    def _tool_operations(
        self,
        payload: Mapping[str, Any],
        current_state: Mapping[str, Any],
    ) -> list[WorkingPatchOperation]:
        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return []

        completed: list[str] = []
        findings: list[str] = []
        failures: list[str] = []
        active_entities: list[str] = []
        blockers = self._as_strings(current_state.get("blockers"))
        resolved_keys: set[str] = set()
        failed_blocks: list[tuple[str, str]] = []
        current_step = ""
        next_action = ""

        for raw_call in calls:
            if not isinstance(raw_call, Mapping):
                continue
            name = self._tool_name(raw_call)
            if not name:
                continue
            target = self._target(raw_call)
            if target and name in self._READ_NAMES | self._WRITE_NAMES:
                active_entities.append(target)
            key = f"{name}:{target}".lower()
            status = str(raw_call.get("status") or "").strip().lower()
            if status in self._FAILURE:
                action = self._action(name, target, succeeded=False)
                failure = f"{action}: {self._failure_reason(raw_call)}"
                failures.append(failure)
                failed_blocks.append((key, f"{name}: {target}"))
                current_step = f"Resolve failure: {action}"
                next_action = f"Investigate {action.lower()}"
            elif status in self._SUCCESS:
                action = self._action(name, target, succeeded=True)
                completed.append(action)
                findings.append(f"Succeeded: {action}")
                resolved_keys.add(key)
                current_step = action
                next_action = "Verify remaining task steps"

        if not completed and not failures:
            return []

        blockers = [
            item for item in blockers if self._blocker_key(item) not in resolved_keys
        ]
        for key, blocker in failed_blocks:
            if key not in resolved_keys and blocker not in blockers:
                blockers.append(blocker)

        operations: list[WorkingPatchOperation] = []
        if completed:
            operations.append(self._list_operation("completed_steps", completed))
            operations.append(self._list_operation("recent_findings", findings))
        if active_entities:
            operations.append(self._list_operation("active_entities", active_entities))
        if failures:
            operations.append(self._list_operation("recent_failures", failures))
        if blockers != self._as_strings(current_state.get("blockers")) or failed_blocks:
            operations.append(
                WorkingPatchOperation(
                    op="replace", path="/blockers", value=blockers, source="tool"
                )
            )
        operations.extend(
            [
                WorkingPatchOperation(
                    op="replace", path="/current_step", value=current_step, source="tool"
                ),
                WorkingPatchOperation(
                    op="replace", path="/next_action", value=next_action, source="tool"
                ),
            ]
        )
        return operations

    def _terminal_operations(
        self,
        event: MemoryEventContract,
        current_state: Mapping[str, Any],
    ) -> list[WorkingPatchOperation]:
        payload = event.payload or {}
        marker = str(payload.get("boundary") or "").strip().upper()
        event_type = event.event_type.strip().lower()
        is_complete = marker in {"COMPLETE", "DONE", "FINISH"} or event_type in {
            "task_complete",
            "task_completed",
        }
        is_failed = marker in {"FAILED", "FAIL", "ERROR"} or event_type in {
            "task_failed",
            "task_failure",
        }
        if not is_complete and not is_failed:
            return []
        if is_complete:
            return [
                self._list_operation("completed_steps", ["Task completed"]),
                WorkingPatchOperation(
                    op="replace", path="/current_step", value="Task completed", source="tool"
                ),
                WorkingPatchOperation(op="replace", path="/next_action", value="", source="tool"),
                WorkingPatchOperation(op="replace", path="/blockers", value=[], source="tool"),
            ]
        reason = self._first_text(payload, "error", "error_summary", "message") or "Task failed"
        return [
            self._list_operation("recent_failures", [reason]),
            WorkingPatchOperation(
                op="replace", path="/blockers", value=[reason], source="tool"
            ),
            WorkingPatchOperation(
                op="replace", path="/current_step", value="Task failed", source="tool"
            ),
            WorkingPatchOperation(
                op="replace",
                path="/next_action",
                value="Review the task failure",
                source="tool",
            ),
        ]

    @staticmethod
    def _list_operation(field: str, value: list[str]) -> WorkingPatchOperation:
        return WorkingPatchOperation(op="replace", path=f"/{field}", value=value, source="tool")

    def _action(self, name: str, target: str, *, succeeded: bool) -> str:
        display = target or name
        if name in self._READ_NAMES:
            return f"Read {display}"
        if name in self._WRITE_NAMES:
            return f"Updated {display}"
        if name in self._SEARCH_NAMES:
            return f"Searched {display}"
        if name == "test" or any(marker in display.lower() for marker in self._TEST_MARKERS):
            return f"Test {'passed' if succeeded else 'failed'}: {display}"
        if name in {"bash", "command", "run", "shell", "execute"}:
            return f"Command {'succeeded' if succeeded else 'failed'}: {display}"
        return f"{'Completed' if succeeded else 'Failed'} {name}: {display}"

    @staticmethod
    def _tool_name(raw_call: Mapping[str, Any]) -> str:
        return str(raw_call.get("tool_name") or raw_call.get("name") or "").strip().lower()

    def _target(self, raw_call: Mapping[str, Any]) -> str:
        arguments = raw_call.get("arguments")
        if not isinstance(arguments, Mapping):
            arguments = {}
        for key in ("path", "file_path", "file", "filename", "command", "cmd", "query", "pattern"):
            value = arguments.get(key)
            if value not in (None, ""):
                return self._compact(value)
        return self._compact(raw_call.get("target") or "")

    def _failure_reason(self, raw_call: Mapping[str, Any]) -> str:
        return self._compact(
            raw_call.get("error")
            or raw_call.get("result")
            or raw_call.get("output")
            or "unknown error"
        )

    @staticmethod
    def _blocker_key(value: str) -> str:
        tool, _, target = value.partition(":")
        return f"{tool.strip()}:{target.strip()}".lower()

    @staticmethod
    def _as_strings(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if value not in (None, "") else []

    @staticmethod
    def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _compact(value: Any, *, max_chars: int = 160) -> str:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if len(text) > max_chars else text


__all__ = ["WorkingStateReducer"]
