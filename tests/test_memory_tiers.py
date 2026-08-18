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
        fact_mode="knowledge",
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
