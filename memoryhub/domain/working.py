"""Pure Working State patch, merge, and compression rules.

The application service owns persistence and CAS.  This module deliberately
contains no database code so the same rules can be used by replay and tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from memoryhub.domain.contracts import WorkingPatchOperation

DEFAULT_SOURCE_PRIORITIES: dict[str, int] = {
    "system": 0,
    "model": 20,
    "inferred": 30,
    "tool": 60,
    "user": 90,
    "user_explicit": 100,
}

SEMANTIC_LIST_FIELDS = frozenset(
    {
        "pending_steps",
        "completed_steps",
        "constraints",
        "active_entities",
        "recent_findings",
        "recent_failures",
    }
)


class WorkingPatchError(ValueError):
    """A patch cannot be applied to the structured Working State."""


class WorkingSourceConflict(WorkingPatchError):
    """A lower-priority source attempted to replace a higher-priority field."""


@dataclass(frozen=True, slots=True)
class PatchApplication:
    state: dict[str, Any]
    field_sources: dict[str, str]
    applied_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]


def source_priority(source: str, priorities: Mapping[str, int] | None = None) -> int:
    """Return a deterministic priority; unknown sources fail closed to zero."""

    table = priorities or DEFAULT_SOURCE_PRIORITIES
    return int(table.get(source.strip().lower(), 0))


def _segments(path: str) -> list[str]:
    if not path.startswith("/") or path == "/":
        raise WorkingPatchError("working patch paths must target a named field")
    return [segment.replace("~1", "/").replace("~0", "~") for segment in path[1:].split("/")]


def _get_parent(state: dict[str, Any], path: str, *, create: bool) -> tuple[Any, str]:
    segments = _segments(path)
    current: Any = state
    for segment in segments[:-1]:
        if isinstance(current, dict):
            if segment not in current:
                if not create:
                    raise WorkingPatchError(f"path does not exist: {path}")
                current[segment] = {}
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index >= len(current):
                raise WorkingPatchError(f"list index out of range: {path}")
            current = current[index]
        else:
            raise WorkingPatchError(f"path is not traversable: {path}")
    return current, segments[-1]


def _read(state: dict[str, Any], path: str) -> Any:
    parent, key = _get_parent(state, path, create=False)
    if isinstance(parent, dict) and key in parent:
        return parent[key]
    if isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
        return parent[int(key)]
    raise WorkingPatchError(f"path does not exist: {path}")


def _semantic_merge(old: Any, new: Any, field: str) -> Any:
    if field not in SEMANTIC_LIST_FIELDS or not isinstance(old, list) or not isinstance(new, list):
        return deepcopy(new)
    merged = list(deepcopy(old))
    for item in new:
        if item not in merged:
            merged.append(deepcopy(item))
    return merged


def apply_operations(
    state: Mapping[str, Any],
    operations: Sequence[WorkingPatchOperation],
    *,
    field_sources: Mapping[str, str] | None = None,
    priorities: Mapping[str, int] | None = None,
) -> PatchApplication:
    """Apply field-level operations with source precedence and semantic lists."""

    result = deepcopy(dict(state))
    sources = dict(field_sources or {})
    applied: list[str] = []
    skipped: list[str] = []
    for operation in operations:
        segments = _segments(operation.path)
        field = segments[0]
        source = operation.source.strip().lower()
        incoming_priority = operation.priority
        if incoming_priority is None:
            incoming_priority = source_priority(source, priorities)
        current_source = sources.get(field, "system")
        if field in sources and incoming_priority < source_priority(current_source, priorities):
            skipped.append(operation.path)
            continue

        parent, key = _get_parent(
            result, operation.path, create=operation.op == "add"
        )
        if operation.op in {"add", "replace"}:
            if isinstance(parent, dict):
                old = parent.get(key)
                parent[key] = _semantic_merge(old, operation.value, field)
            elif isinstance(parent, list):
                if key == "-" and operation.op == "add":
                    parent.append(deepcopy(operation.value))
                elif key.isdigit() and int(key) < len(parent):
                    parent[int(key)] = deepcopy(operation.value)
                else:
                    raise WorkingPatchError(f"invalid list target: {operation.path}")
            else:
                raise WorkingPatchError(f"path is not writable: {operation.path}")
        elif operation.op == "remove":
            if isinstance(parent, dict):
                if key not in parent:
                    raise WorkingPatchError(f"path does not exist: {operation.path}")
                del parent[key]
            elif isinstance(parent, list) and key.isdigit() and int(key) < len(parent):
                del parent[int(key)]
            else:
                raise WorkingPatchError(f"invalid remove target: {operation.path}")
        else:  # pragma: no cover - Pydantic rejects unknown operations
            raise WorkingPatchError(f"unsupported patch operation: {operation.op}")
        sources[field] = source
        applied.append(operation.path)
    return PatchApplication(result, sources, tuple(applied), tuple(skipped))


def compress_working_state(
    state: Mapping[str, Any], *, max_items: int = 32, max_chars: int = 2_000
) -> dict[str, Any]:
    """Create a deterministic, structured context-safe Working State summary."""

    if max_items < 1 or max_chars < 64:
        raise ValueError("compression limits are too small")
    known = {
        "current_goal": state.get("current_goal", ""),
        "current_step": state.get("current_step", ""),
        "pending_steps": list(state.get("pending_steps", []) or [])[:max_items],
        "completed_steps": list(state.get("completed_steps", []) or [])[:max_items],
        "constraints": list(state.get("constraints", []) or [])[:max_items],
        "active_entities": list(state.get("active_entities", []) or [])[:max_items],
        "blockers": list(state.get("blockers", []) or [])[:max_items],
        "recent_findings": list(state.get("recent_findings", []) or [])[:max_items],
        "recent_failures": list(state.get("recent_failures", []) or [])[:max_items],
        "next_action": str(state.get("next_action", "") or ""),
    }
    result: dict[str, Any] = {"schema_version": "vnext/working-summary/v1", **known}
    omitted = {
        field: len(state.get(field, []) or []) - len(result[field])
        for field in SEMANTIC_LIST_FIELDS
        if len(state.get(field, []) or []) > len(result[field])
    }
    if omitted:
        result["omitted_items"] = omitted
    while len(str(result)) > max_chars and result["constraints"]:
        result["constraints"].pop()
    while len(str(result)) > max_chars and result["active_entities"]:
        result["active_entities"].pop()
    while len(str(result)) > max_chars and result["recent_findings"]:
        result["recent_findings"].pop()
    while len(str(result)) > max_chars and result["recent_failures"]:
        result["recent_failures"].pop()
    result["compressed"] = len(str(result)) > max_chars
    return result


__all__ = [
    "DEFAULT_SOURCE_PRIORITIES",
    "PatchApplication",
    "SEMANTIC_LIST_FIELDS",
    "WorkingPatchError",
    "WorkingSourceConflict",
    "apply_operations",
    "compress_working_state",
    "source_priority",
]
