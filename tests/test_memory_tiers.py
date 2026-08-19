"""Phase E：记忆分层（short/mid/long）流转验证。"""

from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    ToolCallResult,
)
from memoryhub.core.forget.health import HealthCalculator
from memoryhub.core.ingestion.service import EventIngestionService
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.core.lifecycle.degrader import MemoryDegrader
from memoryhub.core.lifecycle.memory_consolidator import MemoryConsolidator
from memoryhub.core.lifecycle.session_consolidator import SessionConsolidator
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import (
    Database,
    EventRepository,
    KnowledgeRepository,
    MidTermMemoryRepository,
    PreferenceRepository,
    ShortTermMemoryRepository,
)

_QUALITY = EventQuality(
    score=1.0,
    status=QualityStatus.ACCEPTED,
    completeness=1.0,
    validity=1.0,
    consistency=1.0,
    freshness=1.0,
)


def _event(
    eid: str,
    session: str = "s1",
    task: str = "t1",
    source_type: str = "user_behavior",
    event_type: str = "chat",
    **overrides,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=eid,
        user_id="u1",
        session_id=session,
        task_type=task,
        scene="office",
        source_type=source_type,
        event_type=event_type,
        text=f"事件 {eid} 内容",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash=hashlib.sha256(eid.encode()).hexdigest(),
        quality=_QUALITY,
        payload={"source": "test"},
        **overrides,
    )


def _setup(tmp_path):
    db = Database(str(tmp_path / "tiers.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    event_repo = EventRepository(db)
    st_repo = ShortTermMemoryRepository(db)
    mt_repo = MidTermMemoryRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    return db, {"pref": pref_repo, "know": know_repo, "events": event_repo,
                "st": st_repo, "mt": mt_repo, "writer": writer}


def test_ingestion_buffers_short_term(tmp_path):
    """事件 → short_term_memory 缓冲（TTL）。"""
    db, repos = _setup(tmp_path)
    service = EventIngestionService(
        event_repo=repos["events"],
        safety_gate=None,
        quality_scorer=None,
        memory_write_service=repos["writer"],
        short_term_repo=repos["st"],
    )
    service._buffer_short_term([_event("e1", session="sx")])
    records = repos["st"].list_by_session("u1", "sx")
    assert len(records) == 1
    assert records[0]["event_id"] == "e1"


def test_session_consolidator_aggregates_and_clears(tmp_path):
    """short → mid：聚合会话为情景，清理短期。"""
    db, repos = _setup(tmp_path)
    repos["events"].save(_event("e1"))
    repos["events"].save(_event("e2"))
    st = repos["st"]
    st.add(user_id="u1", session_id="s1", task_type="t1", event_id="e1", text="x")
    st.add(user_id="u1", session_id="s1", task_type="t1", event_id="e2", text="y")

    consolidator = SessionConsolidator(
        short_term_repo=st, mid_term_repo=repos["mt"], event_repo=repos["events"]
    )
    created = consolidator.consolidate_sessions()
    assert len(created) == 1
    episode = repos["mt"].get_by_id(created[0])
    assert set(episode["event_ids"]) == {"e1", "e2"}
    assert "事件 e1" in episode["trajectory_summary"]
    assert st.list_by_session("u1", "s1") == []  # 短期已清理


def test_memory_consolidator_writes_long_term_and_marks(tmp_path):
    """mid → long：重放事件到抽取链，长期 FACT 知识写入，情景标记 consolidated。"""
    db, repos = _setup(tmp_path)
    event = _event(
        "e1",
        source_type="tool_result",
        event_type="project_query",
        tool_calls=[
            ToolCallResult(
                call_id="c1",
                sequence=1,
                tool_name="project_query",
                status="success",
                result={"subject": "项目A", "predicate": "负责人", "object": "张三"},
            )
        ],
    )
    repos["events"].save(event)
    repos["mt"].add(
        episode_id="epi_1", user_id="u1", session_ids=["s1"], task_type="t1",
        event_ids=["e1"], trajectory_summary="x", tools=["project_query"],
    )
    extractor = KnowledgeExtractor(llm_client=None)
    from memoryhub.core.ingestion.extraction import ExtractionExecutor

    executor = ExtractionExecutor(
        memory_write_service=repos["writer"],
        knowledge_extractor=extractor,
    )
    consolidator = MemoryConsolidator(
        mid_term_repo=repos["mt"], event_repo=repos["events"], extraction_executor=executor
    )
    stats = consolidator.consolidate_episodes()
    assert stats["consolidated"] == 1
    facts = repos["know"].get_by_type("u1", knowledge_type="fact", status="active")
    assert any(f.subject == "项目A" and f.object_value == "张三" for f in facts)
    assert repos["mt"].get_by_id("epi_1")["status"] == "consolidated"


def test_consolidation_idempotent(tmp_path):
    """重复 consolidate 不重复建情景/长期行。"""
    db, repos = _setup(tmp_path)
    repos["events"].save(_event("e1"))
    st = repos["st"]
    st.add(user_id="u1", session_id="s1", task_type="t1", event_id="e1", text="x")
    consolidator = SessionConsolidator(
        short_term_repo=st, mid_term_repo=repos["mt"], event_repo=repos["events"]
    )
    first = consolidator.consolidate_sessions()
    # 短期已清空，重跑无新情景
    second = consolidator.consolidate_sessions()
    assert len(first) == 1 and second == []


def test_memory_degrader_archives_low_health(tmp_path):
    """长期低健康度 → 中期情景快照 + 归档。"""
    db, repos = _setup(tmp_path)
    pref = PreferenceMemory(
        user_id="u1", preference_type="output_style", text="low health pref",
        status="active", access_count_30d=0,
    )
    # 手动把健康度拉低（利用极旧时间锚点）
    from datetime import datetime, timedelta, timezone

    pref.updated_at = datetime.now(timezone.utc) - timedelta(days=500)
    repos["pref"].save(pref)
    degrader = MemoryDegrader(
        pref_repo=repos["pref"], know_repo=repos["know"],
        mid_term_repo=repos["mt"], write_service=repos["writer"],
        threshold=0.3,
    )
    result = degrader.degrade_low_health("u1")
    assert result["degraded"] >= 1
    stored = repos["pref"].get_by_id(pref.memory_id)
    assert stored.status == MemoryStatus.ARCHIVED
    assert len(repos["mt"].list_all(user_id="u1")) >= 1


def test_tiered_cascade_search_annotates_levels(tmp_path):
    """I-4：带 session_id 的 /search 注入短期/中期结果并按 level 标注。"""
    import hashlib as _hashlib

    from fastapi.testclient import TestClient

    from memoryhub.app import create_app
    from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig

    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "cascade.db"),
            vector_index_path=str(tmp_path / "v"),
            evidence_path=str(tmp_path / "e"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    payload = {
        "event_id": "evt-cascade",
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": "u-cascade",
        "session_id": "sess-cascade",
        "scene": "office",
        "task_type": "office.weekly_report",
        "occurred_at": "2026-08-08T08:00:00Z",
        "text": "请用 Markdown 格式写周报",
        "payload": {"action": "message"},
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": _hashlib.sha256(b"cascade").hexdigest(),
        "redactions": [],
        "quality": {
            "score": 1.0, "status": "accepted", "completeness": 1.0,
            "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": [],
        },
    }
    with TestClient(
        create_app(config)
    ) as c:
        r = c.post("/api/memory/events", json={"events": [payload]})
        assert r.status_code == 200, r.text
        assert c.get("/api/memory/short-term", params={"user_id": "u-cascade", "session_id": "sess-cascade"}).status_code == 200

        # 带 session_id 检索：短期内容注入结果，且标注 memory_level
        sr = c.post("/api/memory/search", json={
            "user_id": "u-cascade", "session_id": "sess-cascade",
            "query": "Markdown 周报", "top_k": 5,
        })
        assert sr.status_code == 200, sr.text
        levels = {res["memory_level"] for res in sr.json()["results"]}
        assert "short" in levels, sr.json()



def test_workflow_preference_mining_from_episodes(tmp_path):
    """I-9：跨≥3 条同类轨迹挖掘稳定工作流 → WORKFLOW_PREF 写入长期偏好。"""
    db, repos = _setup(tmp_path)
    from memoryhub.core.knowledge.workflow_miner import WorkflowMiner
    from memoryhub.core.preference.updater import PreferenceUpdater

    events = []
    for i in range(3):  # 3 条同类任务轨迹（同一 scene/task_type）
        calls = [
            ToolCallResult(
                call_id=f"c{i}-1", sequence=1, tool_name="file_read", status="success",
                arguments={"path": f"/docs/{i}.md"}, result={"ok": True},
            ),
            ToolCallResult(
                call_id=f"c{i}-2", sequence=2, tool_name="template_apply", status="success",
                arguments={"name": "report"}, result={"ok": True},
            ),
        ]
        ev = _event(
            f"wf-e{i}", session=f"s{i}", task="weekly_report", source_type="tool_result",
            event_type="task_run", tool_calls=calls,
        )
        ev.payload = {"steps": ["读取项目文档", "应用周报模板"], "task_id": "report_gen"}
        repos["events"].save(ev)
        events.append(ev)
        repos["mt"].add(
            episode_id=f"epi-wf-{i}", user_id="u1", session_ids=[f"s{i}"],
            task_type="weekly_report", scene="office",
            event_ids=[f"wf-e{i}"], trajectory_summary="report generation",
            tools=["file_read", "template_apply"],
        )

    updater = PreferenceUpdater(
        pref_repo=repos["pref"], write_service=repos["writer"]
    )
    consolidator = MemoryConsolidator(
        mid_term_repo=repos["mt"], event_repo=repos["events"],
        extraction_executor=None, preference_updater=updater,
        workflow_miner=WorkflowMiner(),
    )
    written = consolidator.consolidate_workflow_preferences(user_id="u1")
    prefs = repos["pref"].list_all(status="active", user_id="u1")
    workflow_prefs = [
        p for p in prefs
        if str(getattr(p.preference_type, "value", "") or "") == "workflow_preference"
    ]
    assert workflow_prefs, "未挖掘出 WORKFLOW_PREF"
    assert any("读取项目文档" in (p.text or "") for p in workflow_prefs)
    assert written


def test_auto_forget_demote_writes_mid_episode(tmp_path):
    """I-6：AutoForgetEngine 降级与 MemoryDegrader 深融合——低健康度长期记忆
    先落中期情景快照再降级，而非仅改 level 字段。"""
    from datetime import datetime, timedelta, timezone

    from memoryhub.core.forget.auto_forget import AutoForgetEngine

    db, repos = _setup(tmp_path)
    pref = PreferenceMemory(
        user_id="u1", preference_type="output_style", text="低频旧偏好",
        status="active", level="long", access_count_30d=0,
    )
    # 拉低健康度到"降级带"（Preference 半衰期 180 天 → ~180 天未用≈健康0.3，
    # 落入 [ARCHIVE=0.2, DEMOTE=0.4) 的降级带，而非直接归档）
    pref.updated_at = datetime.now(timezone.utc) - timedelta(days=180)
    repos["pref"].save(pref)

    engine = AutoForgetEngine(
        pref_repo=repos["pref"], know_repo=repos["know"],
        memory_write_service=repos["writer"],
        mid_term_repo=repos["mt"],
    )
    stats = engine.run()
    # 低健康度落入降级带（而非直接归档） → 落中期情景快照
    episodes = repos["mt"].list_all(user_id="u1")
    assert episodes, "降级未落中期情景快照"
    assert episodes[0]["trajectory_summary"] == "低频旧偏好"
    stored = repos["pref"].get_by_id(pref.memory_id)
    assert str(stored.level.value if hasattr(stored.level, "value") else stored.level) in (
        "mid", "short",
    )


def test_level_precise_forget(tmp_path):
    """I-13：按记忆分层精准遗忘——level=long 只删长期、保留短期同主题记忆。"""
    from memoryhub.adapter.schemas import ForgetRequest
    from memoryhub.core.forget.forgetter import MemoryForgetter

    db, repos = _setup(tmp_path)
    long_pref = PreferenceMemory(
        user_id="u1", preference_type="format_preference", text="项目周报使用 Markdown",
        status="active", level="long",
    )
    short_pref = PreferenceMemory(
        user_id="u1", preference_type="format_preference", text="临时记住用 markdown",
        status="active", level="short",
    )
    repos["pref"].save(long_pref)
    repos["pref"].save(short_pref)

    forgetter = MemoryForgetter(
        pref_repo=repos["pref"],
        know_repo=repos["know"],
        memory_write_service=repos["writer"],
    )
    resp = forgetter.execute(
        ForgetRequest(
            user_id="u1",
            instruction="忘记 markdown 相关偏好",
            level="long",  # 只忘长期
        )
    )
    assert resp.deleted_count >= 1
    assert long_pref.memory_id in resp.deleted_ids
    # 短期记忆保留
    assert short_pref.memory_id not in resp.deleted_ids
    assert repos["pref"].get_by_id(short_pref.memory_id).status == "active"
