"""ToolPreferenceMiner：工具选择偏好挖掘验证（REFACTOR_PLAN_V2 §4.2.1）。"""

from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    KnowledgeType,
    MemoryEvent,
    MemoryStatus,
    QualityStatus,
    ToolCallResult,
)
from memoryhub.core.lifecycle.memory_consolidator import MemoryConsolidator
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.preference.tool_miner import ToolPreferenceMiner
from memoryhub.core.preference.updater import PreferenceUpdater
from memoryhub.storage.database import (
    Database,
    EventRepository,
    KnowledgeRepository,
    MidTermMemoryRepository,
    PreferenceRepository,
)

_QUALITY = EventQuality(
    score=1.0, status=QualityStatus.ACCEPTED, completeness=1.0, validity=1.0,
    consistency=1.0, freshness=1.0,
)


def _event(eid: str, tool: str, status: str = "success", task: str = "周报生成", scene: str = "office"):
    return MemoryEvent(
        event_id=eid,
        user_id="u1",
        session_id="s1",
        task_type=task,
        scene=scene,
        source_type="tool_result",
        event_type="tool_call",
        text=f"调用 {tool}",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash=hashlib.sha256(eid.encode()).hexdigest(),
        quality=_QUALITY,
        payload={"source": "test"},
        tool_calls=[
            ToolCallResult(
                call_id=f"{eid}-c1", sequence=1, tool_name=tool, status=status,
                result={"ok": True},
            )
        ],
    )


def test_miner_produces_tool_preference_for_frequent_success():
    events = [
        _event("e1", "markdown_editor"),
        _event("e2", "markdown_editor"),
        _event("e3", "markdown_editor"),
    ]
    prefs = ToolPreferenceMiner().mine(events, user_id="u1")
    assert len(prefs) == 1
    pref = prefs[0]
    assert pref.preference_type == "tool_preference"
    assert pref.payload["tool"] == "markdown_editor"
    assert pref.payload["task_type"] == "周报生成"
    assert "markdown_editor" in pref.text
    assert pref.extract_source == "tool_preference_miner"
    assert 0.0 <= pref.confidence <= 0.95


def test_miner_skips_low_frequency():
    events = [_event("e1", "tool_a"), _event("e2", "tool_a")]
    assert ToolPreferenceMiner(min_frequency=3).mine(events, user_id="u1") == []


def test_miner_skips_low_success_rate():
    events = [
        _event("e1", "flaky_tool", status="success"),
        _event("e2", "flaky_tool", status="error"),
        _event("e3", "flaky_tool", status="error"),
    ]
    # success_rate = 1/3 < 0.7
    assert ToolPreferenceMiner().mine(events, user_id="u1") == []


def test_miner_separates_tasks():
    events = [
        _event("e1", "tool_x", task="周报"),
        _event("e2", "tool_x", task="周报"),
        _event("e3", "tool_x", task="周报"),
        _event("e4", "tool_y", task="报销"),
        _event("e5", "tool_y", task="报销"),
        _event("e6", "tool_y", task="报销"),
    ]
    prefs = ToolPreferenceMiner().mine(events, user_id="u1")
    assert len(prefs) == 2
    assert {p.payload["tool"] for p in prefs} == {"tool_x", "tool_y"}


def _setup(tmp_path):
    db = Database(str(tmp_path / "tp.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    event_repo = EventRepository(db)
    mt_repo = MidTermMemoryRepository(db)
    writer = MemoryWriteService(pref_repo=pref_repo, know_repo=know_repo, project_immediately=False)
    updater = PreferenceUpdater(pref_repo=pref_repo, write_service=writer)
    consolidator = MemoryConsolidator(
        mid_term_repo=mt_repo, event_repo=event_repo, extraction_executor=None,
        preference_updater=updater, tool_miner=ToolPreferenceMiner(),
    )
    return db, {"pref": pref_repo, "events": event_repo, "mt": mt_repo, "cons": consolidator}


def test_consolidate_tool_preferences_from_episodes(tmp_path):
    """从中期情景挖掘并写入长期 TOOL_PREFERENCE；幂等（重跑 reinforce 不重复建）。"""
    db, repos = _setup(tmp_path)
    for i in range(3):
        repos["events"].save(_event(f"te{i}", "markdown_editor"))
    repos["mt"].add(
        episode_id="epi_tp1", user_id="u1", session_ids=["s1"], task_type="周报生成",
        event_ids=[f"te{i}" for i in range(3)], trajectory_summary="x",
        tools=["markdown_editor"],
    )
    written = repos["cons"].consolidate_tool_preferences(user_id="u1")
    assert len(written) == 1
    prefs = repos["pref"].list_all(status="active", user_id="u1")
    tool_prefs = [p for p in prefs if p.preference_type == "tool_preference"]
    assert len(tool_prefs) == 1
    assert tool_prefs[0].payload["tool"] == "markdown_editor"
    assert tool_prefs[0].status == MemoryStatus.ACTIVE
    db.close()
