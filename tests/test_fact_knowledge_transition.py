"""Phase C：FACT 生产切换验证（ingestion 消除双写 + 迁移脚本）。"""

from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    KnowledgeType,
    MemoryEvent,
    QualityStatus,
    ToolCallResult,
)
from memoryhub.core.fact.models import Entity, Fact, PredicateDef
from memoryhub.core.fact.store import FactStore
from memoryhub.core.ingestion.extraction import ExtractionExecutor
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)

_QUALITY = EventQuality(
    score=1.0,
    status=QualityStatus.ACCEPTED,
    completeness=1.0,
    validity=1.0,
    consistency=1.0,
    freshness=1.0,
)


def _event_with_tool_result() -> MemoryEvent:
    return MemoryEvent(
        event_id="evt-fact-1",
        user_id="u1",
        source_type="tool_result",
        event_type="project_query",
        text="查询项目负责人",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash=hashlib.sha256(b"evt-fact-1").hexdigest(),
        quality=_QUALITY,
        tool_calls=[
            ToolCallResult(
                call_id="c1",
                sequence=1,
                tool_name="project_query",
                status="success",
                result={
                    "subject": "项目A",
                    "predicate": "负责人",
                    "object": "张三",
                    "object_type": "Person",
                },
            )
        ],
    )


def _setup(tmp_path, fact_mode):
    db = Database(str(tmp_path / "kb.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    extractor = KnowledgeExtractor(llm_client=None)
    fact_store = FactStore(str(tmp_path / "kb.db"))
    executor = ExtractionExecutor(
        memory_write_service=writer,
        knowledge_extractor=extractor,
        fact_mode=fact_mode,
    )
    return db, know_repo, executor, fact_store


def test_fact_mode_knowledge_produces_fact_knowledge_not_legacy_facts(tmp_path):
    """fact_mode=knowledge：事件 → knowledge(FACT) 写入，旧 facts 表零写入（消除双写）。"""
    db, know_repo, executor, fact_store = _setup(tmp_path, "knowledge")
    event = _event_with_tool_result()
    executor.run_knowledge([event])
    assert executor.run_fact(event) == 0  # 旧管线停用

    fact_knowledge = know_repo.get_by_type("u1", knowledge_type="fact", status="active")
    assert any(f.subject == "项目A" and f.object_value == "张三" for f in fact_knowledge)
    assert fact_store.list_facts(user_id="u1") == []  # 旧 facts 表无写入


def test_fact_mode_legacy_calls_fact_handler(tmp_path):
    """fact_mode=legacy：run_fact 照常走旧 Fact 管线（默认行为不变）。"""
    calls = []

    class _SpyFactHandler:
        def process_and_apply(self, event):
            calls.append(event.event_id)
            return []

    db, know_repo, _executor, _ = _setup(tmp_path, "legacy")
    executor = ExtractionExecutor(
        memory_write_service=_executor.memory_write_service,
        knowledge_extractor=_executor.knowledge_extractor,
        fact_handler=_SpyFactHandler(),
        fact_mode="legacy",
    )
    executor.run_fact(_event_with_tool_result())
    assert calls == ["evt-fact-1"]  # 旧管线被调用


def test_migrate_facts_to_knowledge_is_idempotent(tmp_path):
    """存量 facts → knowledge(FACT)，且重跑幂等不产生重复。"""
    from scripts.migrate_facts_to_knowledge import migrate

    db_path = str(tmp_path / "mig.db")
    store = FactStore(db_path)
    subj_id = Entity.make_id("Person", "项目A", "u1")
    obj_id = Entity.make_id("Person", "张三", "u1")
    store.upsert_entity(
        Entity(entity_id=subj_id, canonical_name="项目A", entity_type="Other", user_id="u1")
    )
    store.upsert_entity(
        Entity(entity_id=obj_id, canonical_name="张三", entity_type="Person", user_id="u1")
    )
    store.upsert_predicate(
        PredicateDef(predicate_id="pred:owner_x", canonical_name="负责人", single_value=True)
    )
    store.insert_fact(
        Fact(
            fact_id="fact_mig1",
            subject_id=subj_id,
            predicate_id="pred:owner_x",
            object_id=obj_id,
            object_value="张三",
            source_text="工具返回：项目A负责人张三",
            source_id="src1",
            observed_at="2026-08-01T00:00:00Z",
            confidence=0.9,
            status="active",
            user_id="u1",
        )
    )
    store.close()

    report1 = migrate(db_path, dry_run=True)
    assert report1["planned"] == 1

    report2 = migrate(db_path)
    assert report2["written"] == 1

    db = Database(db_path)
    db.init_schema()
    know_repo = KnowledgeRepository(db)
    fact_knowledge = know_repo.get_by_type("u1", knowledge_type="fact", status="active")
    assert len(fact_knowledge) == 1
    assert fact_knowledge[0].subject == "项目A"
    assert fact_knowledge[0].predicate == "负责人"
    assert fact_knowledge[0].object_value == "张三"

    # 幂等：重跑不新增
    report3 = migrate(db_path)
    fact_knowledge2 = know_repo.get_by_type("u1", knowledge_type="fact", status="active")
    assert len(fact_knowledge2) == 1
    db.close()
