"""MemoryHub auto-record hook for Claude Code.

Claude Code hooks (``hooks/hooks.json``) call this script with one of three
modes. The script reads the hook JSON payload from stdin, builds ``MemoryEvent``
payloads in the Kylin-MemoryHub ``agent_response`` / ``user_behavior`` contract
and POSTs them to the MemoryHub REST API (``POST /api/memory/events``), where
safety filtering and preference / knowledge / fact extraction run automatically.

Modes
-----
``--accumulate``   PostToolBatch: append the batch's tool-call traces to the
                   per-session pending file. Runs ``async`` so it never blocks
                   Claude Code's agentic loop.
``--flush-turn``   Stop: build one ``agent_response`` event from the pending
                   tool calls + ``last_assistant_message`` and POST it.
``--flush-all``    SessionEnd: drain every leftover pending trace as best-effort
                   summary events.

Robustness
----------
* stdlib only (``urllib``, ``json``, ``hashlib``) so it runs on any Python ≥ 3.8
  without extra dependencies.
* Every failure is logged to stderr and swallowed; the script always exits 0 so
  Claude Code is never blocked or broken by this plugin.
* If the memoryhub repo is importable it validates events against the real
  Pydantic ``MemoryEvent``; otherwise it constructs the payload manually and
  lets the REST server be the authority.

Configuration (environment variables, see README / docs/CLAUDE_INTEGRATION.md)
-----------------------------------------------------------------------------
MEMORYHUB_API_URL            default http://127.0.0.1:8000
MEMORYHUB_USER_ID            default claudecode
MEMORYHUB_AUTO_RECORD        default true  (set to false to disable recording)
MEMORYHUB_SCENE              default code
MEMORYHUB_TASK_TYPE          default coding_task
MEMORYHUB_MAX_RESULT_CHARS   default 4000  (tool result truncation)
MEMORYHUB_RECORD_SUMMARIES   default true  (record turns without tool calls)
MEMORYHUB_RECORD_SUBAGENTS   default false (record subagent tool calls too)
MEMORYHUB_FLUSH_SETTLE_MS    default 300   (wait for async accumulate to land)
CLAUDE_PLUGIN_DATA           set by Claude Code; pending traces live here
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


@dataclass
class HookConfig:
    api_url: str = field(default_factory=lambda: _env("MEMORYHUB_API_URL", "http://127.0.0.1:8000"))
    user_id: str = field(default_factory=lambda: _env("MEMORYHUB_USER_ID", "claudecode"))
    auto_record: bool = field(default_factory=lambda: _env("MEMORYHUB_AUTO_RECORD", "true").lower() != "false")
    scene: str = field(default_factory=lambda: _env("MEMORYHUB_SCENE", "code"))
    task_type: str = field(default_factory=lambda: _env("MEMORYHUB_TASK_TYPE", "coding_task"))
    max_result_chars: int = field(default_factory=lambda: int(_env("MEMORYHUB_MAX_RESULT_CHARS", "4000")))
    record_summaries: bool = field(default_factory=lambda: _env("MEMORYHUB_RECORD_SUMMARIES", "true").lower() != "false")
    record_subagents: bool = field(default_factory=lambda: _env("MEMORYHUB_RECORD_SUBAGENTS", "false").lower() != "false")
    flush_settle_ms: int = field(default_factory=lambda: int(_env("MEMORYHUB_FLUSH_SETTLE_MS", "300")))
    plugin_data: str = field(default_factory=lambda: _env("CLAUDE_PLUGIN_DATA", ""))
    timeout: float = field(default_factory=lambda: float(_env("MEMORYHUB_API_TIMEOUT", "60")))

    def pending_dir(self) -> Path:
        base = Path(self.plugin_data).resolve() if self.plugin_data else Path(temp_dir())
        return base / "pending"


def temp_dir() -> Path:
    """Fallback pending location when CLAUDE_PLUGIN_DATA is unavailable."""
    return Path(os.environ.get("TEMP", "/tmp"))


# ---------------------------------------------------------------------------
# Pure helpers (exported for tests)
# ---------------------------------------------------------------------------


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def occurred_at(date: datetime | None = None) -> str:
    """UTC second-precision ISO 8601 string, the contract's format."""
    dt = date or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def truncate(value: Any, max_chars: int) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "\n…(truncated by memoryhub plugin)"
    return text


def default_quality() -> dict:
    return {
        "score": 1.0,
        "status": "accepted",
        "completeness": 1.0,
        "validity": 1.0,
        "consistency": 1.0,
        "freshness": 1.0,
        "issues": [],
    }


def is_memoryhub_tool(tool_name: str) -> bool:
    """True for the MemoryHub MCP server's own tools (avoid self-recording)."""
    return "memoryhub" in tool_name.lower()


def to_tool_call(entry: dict, sequence: int, max_chars: int) -> dict:
    """Convert one PostToolBatch tool_calls entry into a ToolCallResult dict."""
    tool_name = str(entry.get("tool_name") or "unknown_tool")
    return {
        "call_id": str(entry.get("tool_use_id") or f"call_{sequence}_{sha256_hex(tool_name)[:8]}"),
        "tool_name": tool_name,
        "arguments": entry.get("tool_input") if isinstance(entry.get("tool_input"), dict) else {"value": entry.get("tool_input")},
        "result": truncate(entry.get("tool_response"), max_chars),
        "status": "success",
        "sequence": int(sequence),
        "error": "",
    }


def build_event(
    *,
    session_id: str,
    turn_id: str,
    text: str,
    tool_calls: list[dict],
    first_seen: str,
    cfg: HookConfig,
) -> dict | None:
    """Build one validated MemoryEvent payload (or None when there is nothing)."""
    calls = [c for c in tool_calls if isinstance(c, dict)]

    if calls:
        event = {
            "event_id": f"evt_cc_{sha256_hex(f'{session_id}:{turn_id}')[:12]}",
            "source_type": "tool_result",
            "event_type": "agent_response",
            "user_id": cfg.user_id,
            "session_id": session_id,
            "turn_id": turn_id or session_id,
            "scene": cfg.scene,
            "task_type": cfg.task_type,
            "occurred_at": first_seen or occurred_at(),
            "text": text.strip() or "claude code turn completed",
            "payload": {"action": "turn_record", "tool_call_count": len(calls)},
            "tool_calls": calls,
        }
    elif cfg.record_summaries and text.strip():
        event = {
            "event_id": f"evt_cc_{sha256_hex(f'{session_id}:{turn_id}:summary')[:12]}",
            "source_type": "user_behavior",
            "event_type": "agent_summary",
            "user_id": cfg.user_id,
            "session_id": session_id,
            "turn_id": turn_id or session_id,
            "scene": cfg.scene,
            "task_type": cfg.task_type,
            "occurred_at": first_seen or occurred_at(),
            "text": text.strip(),
            "payload": {"action": "turn_summary", "tool_call_count": 0},
            "tool_calls": [],
        }
    else:
        return None

    return _finalize_event(event)


def _finalize_event(event: dict) -> dict:
    event["schema_version"] = "1.1"
    seed = {k: event[k] for k in event if k not in ("source_hash", "quality", "schema_version")}
    event["source_hash"] = sha256_hex(json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    event["redactions"] = []
    event["quality"] = default_quality()

    try:
        if _try_import_memoryhub():
            from memoryhub.adapter.schemas import MemoryEvent

            validated = MemoryEvent.model_validate(event)
            return validated.model_dump(mode="json")
    except Exception:  # noqa: BLE001 - fall back to manual payload, REST validates
        pass
    return event


def _try_import_memoryhub() -> bool:
    try:
        import importlib.util

        if importlib.util.find_spec("memoryhub.adapter.schemas") is not None:
            return True
    except (ImportError, AttributeError):
        return False
    return False


# ---------------------------------------------------------------------------
# Pending-trace accumulator (a JSONL file per session under CLAUDE_PLUGIN_DATA)
# ---------------------------------------------------------------------------


def _sanitize(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in value) or "session"


def pending_path(session_id: str, turn_id: str, cfg: HookConfig) -> Path:
    """Per-turn pending file: ``<session>_<turn>.jsonl``.

    Keying by turn (prompt_id) keeps concurrent async hook processes from
    mixing one turn's tool calls into another's event.
    """
    key = f"{_sanitize(session_id)}_{_sanitize(turn_id)}"
    return cfg.pending_dir() / f"{key}.jsonl"


class FileLock:
    """A tiny cross-platform advisory lock based on O_CREAT|O_EXCL."""

    def __init__(self, path: Path, timeout_ms: int = 3000):
        self.path = path
        self.timeout_ms = timeout_ms

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_ms / 1000.0
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self._owned = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"lock wait timed out: {self.path}")
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if getattr(self, "_owned", False):
            try:
                os.remove(self.path)
            except OSError:
                pass


def accumulate(input_data: dict, cfg: HookConfig) -> int:
    """Append a PostToolBatch's tool calls to the session's pending file.

    Returns the number of tool calls recorded (0 when skipped).
    """
    if not cfg.auto_record:
        return 0
    session_id = str(input_data.get("session_id") or "")
    if not session_id:
        return 0
    if not cfg.record_subagents and input_data.get("agent_id"):
        return 0

    tool_calls = input_data.get("tool_calls") or []
    kept = []
    for entry in tool_calls:
        if not isinstance(entry, dict):
            continue
        tool_name = str(entry.get("tool_name") or "")
        if not tool_name or is_memoryhub_tool(tool_name):
            continue
        kept.append(entry)

    if not kept:
        return 0

    turn_id = str(input_data.get("prompt_id") or "")
    path = pending_path(session_id, turn_id, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    with FileLock(lock):
        first_seen = occurred_at()
        lines: list[str] = []
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
            if lines and not lines[0].startswith("__meta__"):
                lines = []
        if not lines:
            lines = [json.dumps({"__meta__": {"first_seen": first_seen}}, ensure_ascii=False)]
        for entry in kept:
            call = to_tool_call(entry, len(lines), cfg.max_result_chars)  # sequence continues the file
            lines.append(json.dumps(call, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(kept)


def _read_pending(path: Path) -> tuple[str, list[dict]]:
    lines = []
    try:
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    first_seen = ""
    calls: list[dict] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("__meta__"):
            first_seen = obj["__meta__"].get("first_seen") or ""
        else:
            calls.append(obj)
    return first_seen, calls


def flush_turn(input_data: dict, cfg: HookConfig) -> dict:
    """Build and POST one event for the turn that just stopped, then clear.

    Returns a summary dict (never raises; the caller always exits 0).
    """
    if not cfg.auto_record:
        return {"skipped": "auto_record_disabled"}
    session_id = str(input_data.get("session_id") or "")
    turn_id = str(input_data.get("prompt_id") or "") or session_id
    if not session_id:
        return {"skipped": "no_session_id"}

    if cfg.flush_settle_ms > 0:
        time.sleep(cfg.flush_settle_ms / 1000.0)

    path = pending_path(session_id, turn_id, cfg)
    lock = path.with_suffix(".lock")
    try:
        with FileLock(lock):
            first_seen, calls = _read_pending(path)
            try:
                os.remove(path)
            except OSError:
                pass
    except TimeoutError as exc:
        return {"skipped": str(exc)}

    text = str(input_data.get("last_assistant_message") or "")
    event = build_event(
        session_id=session_id,
        turn_id=turn_id,
        text=text,
        tool_calls=calls,
        first_seen=first_seen,
        cfg=cfg,
    )
    if event is None:
        return {"skipped": "nothing_to_record"}

    result = post_events([event], cfg)
    return {"event_id": event["event_id"], "post": result}


def flush_all(input_data: dict, cfg: HookConfig) -> dict:
    """Drain every pending trace left at session end as summary events."""
    if not cfg.auto_record:
        return {"skipped": "auto_record_disabled"}
    pending_dir = cfg.pending_dir()
    if not pending_dir.exists():
        return {"flushed": 0}
    flushed = 0
    for path in sorted(pending_dir.glob("*.jsonl")):
        if path.name.startswith("."):
            continue
        try:
            first_seen, calls = _read_pending(path)
            os.remove(path)
        except OSError:
            continue
        session_id = _sanitize(path.stem)
        text = str(input_data.get("last_assistant_message") or "")
        event = build_event(
            session_id=session_id,
            turn_id=session_id,
            text=text,
            tool_calls=calls,
            first_seen=first_seen,
            cfg=cfg,
        )
        if event is None:
            continue
        post_events([event], cfg)
        flushed += 1
    return {"flushed": flushed}


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


def post_events(events: list[dict], cfg: HookConfig) -> dict | None:
    """POST one or more MemoryEvents to the MemoryHub REST service."""
    url = f"{cfg.api_url.rstrip('/')}/api/memory/events"
    body = json.dumps({"events": events}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        _log("warn", f"MemoryHub POST /events failed: {exc}")
        return None


def _log(level: str, message: str) -> None:
    print(f"[memoryhub-record] {level}: {message}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    mode = argv[0] if argv else ""
    if mode not in ("--accumulate", "--flush-turn", "--flush-all"):
        _log("error", f"unknown mode: {mode!r}")
        return 0

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    cfg = HookConfig()
    try:
        if mode == "--accumulate":
            recorded = accumulate(payload, cfg)
            if recorded:
                _log("info", f"accumulated {recorded} tool call(s) for session {payload.get('session_id', '')}")
        elif mode == "--flush-turn":
            summary = flush_turn(payload, cfg)
            if summary.get("post") is not None:
                _log("info", f"recorded turn {summary.get('event_id')}: {summary['post']}")
            elif summary.get("skipped"):
                _log("debug", f"skipped flush: {summary['skipped']}")
        else:
            summary = flush_all(payload, cfg)
            _log("info", f"session end flush: {summary}")
    except Exception as exc:  # noqa: BLE001 - never break Claude Code
        _log("error", f"record.py {mode} failed: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
