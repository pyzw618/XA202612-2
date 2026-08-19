"""Phase C：FACT 生产切换验证（ingestion 消除双写 + 统一知识链产出 FACT 知识）。"""

from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    QualityStatus,
    ToolCallResult,
)
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


def _setup(tmp_path):
    db = Database(str(tmp_path / "kb.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    extractor = KnowledgeExtractor(llm_client=None)
    executor = ExtractionExecutor(
        memory_write_service=writer,
        knowledge_extractor=extractor,
    )
    return db, know_repo, executor


def test_fact_extraction_produces_knowledge_fact(tmp_path):
    """事件 → knowledge(FACT) 写入（FACT 已并入知识链，legacy Fact 已删除）。"""
    db, know_repo, executor = _setup(tmp_path)
    event = _event_with_tool_result()
    executor.run_knowledge([event])

    fact_knowledge = know_repo.get_by_type("u1", knowledge_type="fact", status="active")
    assert any(f.subject == "项目A" and f.object_value == "张三" for f in fact_knowledge)
    db.close()


def test_fact_knowledge_round_trips_idempotently(tmp_path):
    """knowledge(FACT) 经 KnowledgeRepository 重复落库保持单条（幂等）。"""
    db, know_repo, _executor = _setup(tmp_path)
    fact = KnowledgeMemory(
        user_id="u1",
        knowledge_type=KnowledgeType.FACT,
        subject="项目A",
        predicate="负责人",
        object_value="张三",
        object_type="Person",
        single_value=True,
        content="项目A 负责人 张三",
    )
    know_repo.save(fact)
    know_repo.save(fact)

    fact_knowledge = know_repo.get_by_type("u1", knowledge_type="fact", status="active")
    assert len(fact_knowledge) == 1
    assert fact_knowledge[0].subject == "项目A"
    assert fact_knowledge[0].predicate == "负责人"
    assert fact_knowledge[0].object_value == "张三"
    db.close()
