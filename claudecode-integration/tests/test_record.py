"""Unit tests for the MemoryHub Claude Code auto-record script.

Run with the project's Python (>= 3.10 is fine; record.py itself is 3.8+):
    D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_record.py -v
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "plugin" / "memoryhub" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import record  # noqa: E402


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_occurred_at_format():
    value = record.occurred_at()
    assert len(value) == 20
    assert value.endswith("Z")
    assert value[10] == "T"


def test_sha256_hex():
    assert len(record.sha256_hex("")) == 64
    assert record.sha256_hex("a") == record.sha256_hex("a")


def test_truncate():
    assert record.truncate(None, 100) is None
    assert record.truncate("hello world", 5) == "hello\n…(truncated by memoryhub plugin)"
    assert record.truncate({"a": 1}, 100) == json.dumps({"a": 1})
    assert record.truncate("short", 100) == "short"


def test_is_memoryhub_tool():
    assert record.is_memoryhub_tool("memoryhub_search")
    assert record.is_memoryhub_tool("mcp__memoryhub__memoryhub_search")
    assert record.is_memoryhub_tool("mcp__plugin_memoryhub_memoryhub__memoryhub_search")
    assert not record.is_memoryhub_tool("Bash")
    assert not record.is_memoryhub_tool("Read")


def test_to_tool_call():
    entry = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "tool_response": {"stdout": "ok"}, "tool_use_id": "toolu_1"}
    call = record.to_tool_call(entry, 3, 100)
    assert call["call_id"] == "toolu_1"
    assert call["tool_name"] == "Bash"
    assert call["arguments"] == {"command": "git status"}
    assert call["status"] == "success"
    assert call["sequence"] == 3


# ---------------------------------------------------------------------------
# Event building
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return record.HookConfig(
        api_url="http://127.0.0.1:8099",
        user_id="tester",
        auto_record=True,
        scene="code",
        task_type="coding_task",
        max_result_chars=100,
        record_summaries=True,
        record_subagents=False,
        flush_settle_ms=0,
        plugin_data=str(tmp_path),
    )


def test_build_event_with_tool_calls(tmp_path):
    cfg = _cfg(tmp_path)
    calls = [record.to_tool_call({"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "tool_response": "ok"}, 1, 100)]
    event = record.build_event(session_id="s1", turn_id="t1", text="done", tool_calls=calls, first_seen="2026-08-08T08:00:00Z", cfg=cfg)
    assert event is not None
    assert event["source_type"] == "tool_result"
    assert event["event_type"] == "agent_response"
    assert event["turn_id"] == "t1"
    assert event["text"] == "done"
    assert len(event["tool_calls"]) == 1
    assert event["source_hash"] and len(event["source_hash"]) == 64
    assert event["quality"]["status"] == "accepted"


def test_build_event_summary_only(tmp_path):
    cfg = _cfg(tmp_path)
    event = record.build_event(session_id="s1", turn_id="t1", text="hello", tool_calls=[], first_seen="", cfg=cfg)
    assert event is not None
    assert event["source_type"] == "user_behavior"
    assert event["event_type"] == "agent_summary"


def test_build_event_nothing(tmp_path):
    cfg = record.HookConfig(**{**_cfg(tmp_path).__dict__, "record_summaries": False})
    event = record.build_event(session_id="s1", turn_id="t1", text="hello", tool_calls=[], first_seen="", cfg=cfg)
    assert event is None


# ---------------------------------------------------------------------------
# Accumulator + flush (post_events monkeypatched, no network)
# ---------------------------------------------------------------------------


def test_accumulate_and_flush_turn(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    posted = []
    monkeypatch.setattr(record, "post_events", lambda events, c: posted.append(events) or {"accepted": 1})

    batch = {
        "session_id": "sess-1",
        "prompt_id": "turn-1",
        "hook_event_name": "PostToolBatch",
        "tool_calls": [
            {"tool_name": "Read", "tool_input": {"file_path": "a.py"}, "tool_response": "1 a\n2 b", "tool_use_id": "toolu_1"},
            {"tool_name": "Bash", "tool_input": {"command": "pytest"}, "tool_response": "passed", "tool_use_id": "toolu_2"},
        ],
    }
    assert record.accumulate(batch, cfg) == 2

    stop = {"session_id": "sess-1", "hook_event_name": "Stop", "prompt_id": "turn-1", "last_assistant_message": "all green"}
    summary = record.flush_turn(stop, cfg)
    assert summary.get("post") == {"accepted": 1}
    assert len(posted) == 1
    event = posted[0][0]
    assert event["event_type"] == "agent_response"
    assert event["turn_id"] == "turn-1"
    assert event["text"] == "all green"
    assert [c["sequence"] for c in event["tool_calls"]] == [1, 2]
    # pending file removed after flush
    assert not record.pending_path("sess-1", "turn-1", cfg).exists()


def test_turns_are_isolated(tmp_path, monkeypatch):
    """Tool calls from different turns never mix into one event."""
    cfg = _cfg(tmp_path)
    posted = []
    monkeypatch.setattr(record, "post_events", lambda events, c: posted.append(events) or {})

    t1 = {"session_id": "sess-9", "prompt_id": "t1", "tool_calls": [{"tool_name": "Read", "tool_input": {}, "tool_response": "r", "tool_use_id": "a"}]}
    t2 = {"session_id": "sess-9", "prompt_id": "t2", "tool_calls": [{"tool_name": "Bash", "tool_input": {}, "tool_response": "r", "tool_use_id": "b"}]}
    assert record.accumulate(t1, cfg) == 1
    assert record.accumulate(t2, cfg) == 1

    record.flush_turn({"session_id": "sess-9", "prompt_id": "t1", "last_assistant_message": "one"}, cfg)
    assert len(posted) == 1
    assert [c["tool_name"] for c in posted[0][0]["tool_calls"]] == ["Read"]

    record.flush_turn({"session_id": "sess-9", "prompt_id": "t2", "last_assistant_message": "two"}, cfg)
    assert len(posted) == 2
    assert [c["tool_name"] for c in posted[1][0]["tool_calls"]] == ["Bash"]


def test_accumulate_skips_memoryhub_tools(tmp_path):
    cfg = _cfg(tmp_path)
    batch = {
        "session_id": "sess-2",
        "tool_calls": [
            {"tool_name": "memoryhub_search", "tool_input": {"query": "x"}, "tool_response": "r"},
            {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": "r"},
        ],
    }
    assert record.accumulate(batch, cfg) == 1
    _, calls = record._read_pending(record.pending_path("sess-2", "", cfg))
    assert [c["tool_name"] for c in calls] == ["Bash"]


def test_accumulate_skips_subagents_by_default(tmp_path):
    cfg = _cfg(tmp_path)
    batch = {"session_id": "sess-3", "agent_id": "sub-1", "tool_calls": [{"tool_name": "Read", "tool_input": {}, "tool_response": "r"}]}
    assert record.accumulate(batch, cfg) == 0


def test_accumulate_records_subagents_when_enabled(tmp_path):
    cfg = record.HookConfig(**{**_cfg(tmp_path).__dict__, "record_subagents": True})
    batch = {"session_id": "sess-3", "agent_id": "sub-1", "tool_calls": [{"tool_name": "Read", "tool_input": {}, "tool_response": "r"}]}
    assert record.accumulate(batch, cfg) == 1


def test_flush_turn_nothing_to_record(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    posted = []
    monkeypatch.setattr(record, "post_events", lambda events, c: posted.append(events) or {})
    stop = {"session_id": "sess-x", "prompt_id": "t", "last_assistant_message": ""}
    summary = record.flush_turn(stop, cfg)
    assert "skipped" in summary
    assert posted == []


def test_accumulate_respects_auto_record_off(tmp_path):
    cfg = record.HookConfig(**{**_cfg(tmp_path).__dict__, "auto_record": False})
    batch = {"session_id": "s", "tool_calls": [{"tool_name": "Bash", "tool_input": {}, "tool_response": "r"}]}
    assert record.accumulate(batch, cfg) == 0


def test_flush_all_drains_pending(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    posted = []
    monkeypatch.setattr(record, "post_events", lambda events, c: posted.append(events) or {})

    record.accumulate({"session_id": "a", "tool_calls": [{"tool_name": "Read", "tool_input": {}, "tool_response": "r"}]}, cfg)
    record.accumulate({"session_id": "b", "tool_calls": [{"tool_name": "Bash", "tool_input": {}, "tool_response": "r"}]}, cfg)
    assert record.flush_all({"reason": "other"}, cfg) == {"flushed": 2}
    assert len(posted) == 2
    assert list(cfg.pending_dir().glob("*.jsonl")) == []


def test_main_parses_stdin(monkeypatch, capsys, tmp_path):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(record, "HookConfig", lambda: cfg)
    monkeypatch.setattr(
        record,
        "post_events",
        lambda events, c: {"accepted": len(events), "rejected": 0, "event_ids": [e["event_id"] for e in events], "extraction_failures": 0},
    )
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s", "prompt_id": "t", "last_assistant_message": "hi"})))
    assert record.main(["--flush-turn"]) == 0
    out = capsys.readouterr()
    assert "recorded turn" in out.err


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
