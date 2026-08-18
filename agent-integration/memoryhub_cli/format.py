"""Small output helpers shared by CLI tests and command handlers."""

from __future__ import annotations

import json
from typing import Any


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def context_text(value: dict[str, Any], max_chars: int = 0) -> str:
    text = str(value.get("context") or value.get("context_text") or "")
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n...(truncated)"
    return text


def search_text(value: dict[str, Any], *, quiet: bool = False) -> str:
    if quiet:
        return "\n".join(
            "\t".join(
                [
                    str(item.get("memory_id", "")),
                    str(item.get("memory_type", "")),
                    str(item.get("score", "")),
                    str(item.get("content", "")),
                ]
            )
            for item in value.get("results", [])
        )
    lines: list[str] = []
    for index, item in enumerate(value.get("results", []), 1):
        lines.append(
            f"[{index}] {item.get('memory_id', '')} "
            f"({item.get('memory_type', '')}, score {float(item.get('score', 0) or 0):.2f}) "
            f"{item.get('content', '')}"
        )
    lines.append(f"({value.get('total_count', len(value.get('results', [])))} results, {value.get('latency_ms', 0)} ms)")
    return "\n".join(lines)


def generic_text(value: Any, *, quiet: bool = False) -> str:
    if isinstance(value, dict):
        if quiet:
            for key in ("memory_id", "record_id", "status", "accepted", "requeued", "imported"):
                if key in value:
                    return str(value[key])
        preferred = ["status", "memory_id", "record_id", "deleted_count", "accepted", "rejected", "event_ids"]
        parts = [f"{key}={value[key]}" for key in preferred if key in value]
        if parts:
            return " ".join(parts)
    return str(value)
