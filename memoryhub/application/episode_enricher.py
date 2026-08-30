"""Deterministically compact canonical events into Episode history records."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from memoryhub.domain.contracts import MemoryEventContract


class EpisodeEventEnricher:
    """Build bounded, replay-safe Episode payloads from canonical Agent events.

    Episode history keeps task-relevant tool outcomes, not raw tool traces.  The
    source Event remains the authority for the complete accepted payload and is
    linked through ``source_event_id`` on the existing Episode contract.
    """

    _SUCCESS = frozenset({"success", "succeeded", "completed", "ok", "passed"})
    _FAILURE = frozenset({"error", "failed", "failure", "cancelled", "canceled"})
    _READ_NAMES = frozenset({"read", "read_file", "cat", "view", "view_file"})
    _WRITE_NAMES = frozenset({"write", "write_file", "edit", "patch", "apply_patch"})
    _SEARCH_NAMES = frozenset({"search", "grep", "glob", "find"})
    _TEST_MARKERS = ("test", "pytest", "unittest", "mvn test", "gradle test")
    _MAX_ACTIONS = 8
    _MAX_SUMMARY_CHARS = 160

    def enrich(self, event: MemoryEventContract) -> dict[str, Any]:
        """Return a compact semantic representation of one accepted Event."""

        payload = event.payload or {}
        actions = self._tool_actions(payload)
        result: dict[str, Any] = {
            "source_event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
        }
        phase = self._text(payload.get("phase"))
        if phase:
            result["phase"] = phase
            result["state_transition"] = {"phase": phase}

        if actions:
            result["actions"] = actions
            result["summary"] = self._actions_summary(actions)
            total_actions = self._tool_action_count(payload)
            if total_actions > len(actions):
                result["omitted_action_count"] = total_actions - len(actions)
            return result

        marker = self._terminal_marker(event, payload)
        if marker:
            result["action"] = marker
            result["result"] = "FAILURE" if marker == "Task failed" else "SUCCESS"
            result["success"] = marker != "Task failed"
            error = self._first_text(payload, "error", "error_summary", "message")
            if error:
                result["error_summary"] = self._compact(error)
            result["summary"] = marker
            return result

        text = self._first_text(payload, "instruction", "text", "message", "summary")
        if text:
            result["action"] = "Recorded event"
            result["summary"] = self._compact(text)
        else:
            result["summary"] = f"Recorded {event.event_type}"
        return result

    def _tool_actions(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        calls = payload.get("tool_calls")
        if not isinstance(calls, list):
            return []
        actions: list[dict[str, Any]] = []
        for raw_call in calls:
            if len(actions) >= self._MAX_ACTIONS:
                break
            if not isinstance(raw_call, Mapping):
                continue
            name = self._tool_name(raw_call)
            if not name:
                continue
            target = self._target(raw_call)
            status = self._status(raw_call)
            action: dict[str, Any] = {
                "tool_name": name,
                "target": target,
                "action": self._action(name, target, succeeded=status != "FAILURE"),
                "result": status,
                "success": status == "SUCCESS",
            }
            if status == "FAILURE":
                action["error_summary"] = self._failure_reason(raw_call)
            else:
                output = self._output_summary(raw_call)
                if output:
                    action["output_summary"] = output
            actions.append(action)
        return actions

    @staticmethod
    def _tool_action_count(payload: Mapping[str, Any]) -> int:
        calls = payload.get("tool_calls")
        return len(calls) if isinstance(calls, list) else 0

    def _status(self, raw_call: Mapping[str, Any]) -> str:
        value = self._text(raw_call.get("status")).lower()
        if value in self._FAILURE:
            return "FAILURE"
        if value in self._SUCCESS:
            return "SUCCESS"
        return "UNKNOWN"

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

    def _failure_reason(self, raw_call: Mapping[str, Any]) -> str:
        return self._compact(
            raw_call.get("error")
            or raw_call.get("result")
            or raw_call.get("output")
            or "unknown error"
        )

    def _output_summary(self, raw_call: Mapping[str, Any]) -> str:
        return self._compact(
            raw_call.get("summary") or raw_call.get("result") or raw_call.get("output") or ""
        )

    def _actions_summary(self, actions: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"{action['result'].lower()}: {action['action']}" for action in actions
        )[: self._MAX_SUMMARY_CHARS]

    def _terminal_marker(self, event: MemoryEventContract, payload: Mapping[str, Any]) -> str:
        marker = self._text(payload.get("boundary")).upper()
        event_type = event.event_type.strip().lower()
        if marker in {"FAILED", "FAIL", "ERROR"} or event_type in {"task_failed", "task_failure"}:
            return "Task failed"
        if marker in {"COMPLETE", "DONE", "FINISH"} or event_type in {
            "task_complete",
            "task_completed",
        }:
            return "Task completed"
        return ""

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _first_text(self, payload: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = self._text(payload.get(key))
            if value:
                return value
        return ""

    def _compact(self, value: Any) -> str:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        text = re.sub(r"\s+", " ", text).strip()
        return text[: self._MAX_SUMMARY_CHARS]


__all__ = ["EpisodeEventEnricher"]
