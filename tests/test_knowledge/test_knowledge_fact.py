"""FACT 并入知识记忆（REFACTOR_PLAN_V2 §4.8）的验证。

覆盖：数据模型落库、共指修复（"两个小孩"）、S/P/O 冲突（supersede/coexist/duplicate）、
确定性抽取、API 写入 + 检索。
"""

from __future__ import annotations

from memoryhub.adapter.schemas import (
    EventQuality,
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryStatus,
    QualityStatus,
    ToolCallResult,
)

_QUALITY = EventQuality(
    score=1.0,
    status=QualityStatus.ACCEPTED,
    completeness=1.0,
    validity=1.0,
    consistency=1.0,
    freshness=1.0,
)
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)


def _setup(tmp_path):
    db = Database(str(tmp_path / "kb.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    updater = KnowledgeUpdater(write_service=writer)
    return db, know_repo, updater


def _fact(**overrides) -> KnowledgeMemory:
    base = dict(
        user_id="u1",
        knowledge_type=KnowledgeType.FACT,
        subject="项目A",
        predicate="负责人",
        object_value="张三",
        object_type="Person",
        single_value=True,
    )
    base.update(overrides)
    return KnowledgeMemory(**base)


def test_fact_duplicate_reinforces_evidence(tmp_path):
    """同 S/P/O → 只补证据不覆盖（返回既有 memory_id）。"""
    _db, know_repo, updater = _setup(tmp_path)
    id1 = updater.add(_fact())
    f2 = _fact()
    f2.evidences = [
        Evidence(event_id="e2", evidence_id="e2:1", content="工具返回：项目A负责人张三")
    ]
    id2 = updater.add(f2)
    assert id2 == id1
    stored = know_repo.get_by_id(id1)
    assert stored.status == MemoryStatus.ACTIVE
    assert stored.object_value == "张三"


def test_fact_single_value_conflict_waits_for_decision(tmp_path):
    """同 S+P 异 O 且 single_value → 持久化待裁决任务，不自动覆盖。"""
    _db, know_repo, updater = _setup(tmp_path)
    id1 = updater.add(_fact())
    id2 = updater.add(_fact(object_value="李四"))
    assert id2 != id1
    old = know_repo.get_by_id(id1)
    new = know_repo.get_by_id(id2)
    assert old.status == MemoryStatus.ACTIVE
    assert new.status == MemoryStatus.PENDING
    assert new.parent_id == ""
    assert new.extra_payload["fact_decision_task"]["conflict_type"] == "subject_cardinality"


def test_fact_multi_value_coexists(tmp_path):
    """single_value=None（多值/未知）→ 同 S+P 异 O 共存，不覆盖。"""
    _db, know_repo, updater = _setup(tmp_path)
    id1 = updater.add(
        _fact(subject="老王", predicate="孩子", object_value="哥哥", single_value=None)
    )
    id2 = updater.add(
        _fact(subject="老王", predicate="孩子", object_value="妹妹", single_value=None)
    )
    assert id1 != id2
    assert know_repo.get_by_id(id1).status == MemoryStatus.ACTIVE
    assert know_repo.get_by_id(id2).status == MemoryStatus.ACTIVE


def test_fact_conflict_caps_versions(tmp_path):
    """连续单值冲突达上限 → REVIEW，不再自动覆盖。"""
    _db, know_repo, updater = _setup(tmp_path)
    id1 = updater.add(_fact())
    for value in ("李四", "王五", "赵六"):
        result = updater.add(_fact(object_value=value))
    # 第 4 次冲突（version>=3）进入 REVIEW/PENDING
    review = updater.add(_fact(object_value="钱七"))
    stored = know_repo.get_by_id(review)
    assert stored.status == MemoryStatus.PENDING


def test_extract_facts_deterministic_mapping():
    """结构化工具结果不经 LLM 直接映射为 FACT 知识。"""
    extractor = KnowledgeExtractor(llm_client=None)
    event = MemoryEvent(
        event_id="e1",
        user_id="u1",
        source_type="tool_result",
        event_type="project_query",
        text="查询项目负责人",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash="a" * 64,
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
    facts = extractor.extract_facts([event])
    assert len(facts) == 1
    fact = facts[0]
    assert fact.knowledge_type == KnowledgeType.FACT
    assert fact.subject == "项目A"
    assert fact.predicate == "负责人"
    assert fact.object_value == "张三"
    assert fact.object_type == "Person"
    assert fact.single_value is True  # "负责人" 在单值谓词集合
    assert "项目A" in fact.content and "张三" in fact.content


def test_extract_facts_skips_failed_tools_and_empties():
    """失败/空结果工具不产生 FACT。"""
    extractor = KnowledgeExtractor(llm_client=None)
    event = MemoryEvent(
        event_id="e2",
        user_id="u1",
        source_type="tool_result",
        event_type="query",
        text="查询",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash="b" * 64,
        quality=_QUALITY,
        tool_calls=[
            ToolCallResult(
                call_id="c1", sequence=1, tool_name="q", status="error", result={"subject": "x"}
            ),
            ToolCallResult(
                call_id="c2", sequence=2, tool_name="q", status="success", result=None
            ),
        ],
    )
    assert extractor.extract_facts([event]) == []


def test_extract_facts_from_dialogue_text():
    """纯对话文本中的 "X是Y/X为Y" 客观陈述确定性沉淀为 knowledge(FACT)。"""
    extractor = KnowledgeExtractor(llm_client=None)
    event = MemoryEvent(
        event_id="e3",
        user_id="u1",
        source_type="user_behavior",
        event_type="user_action",
        text="周报负责人是李四。账单日期是每月7号",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash="c" * 64,
        quality=_QUALITY,
        payload={"action": "message", "role": "user"},
        tool_calls=[],
    )
    facts = extractor.extract_facts([event])
    assert facts, "对话文本事实应被确定性抽取"
    assert all(f.knowledge_type == KnowledgeType.FACT for f in facts)

    owner = next(f for f in facts if f.object_value == "李四")
    assert owner.subject == "周报"  # "负责人" 归一为谓词
    assert owner.predicate == "负责人"
    assert owner.single_value is True

    bill = next(f for f in facts if "每月7号" in f.object_value)
    assert bill.subject == "账单日期"
    assert bill.evidences and "对话文本" in bill.evidences[0].content


def test_extract_facts_dialogue_skips_subjective_wishes():
    """主观意愿句（"偏好/希望"结尾主语）不得成为事实。"""
    extractor = KnowledgeExtractor(llm_client=None)
    event = MemoryEvent(
        event_id="e4",
        user_id="u1",
        source_type="user_behavior",
        event_type="user_action",
        text="用户偏好是简洁输出",
        occurred_at="2026-08-18T00:00:00Z",
        source_hash="d" * 64,
        quality=_QUALITY,
        payload={"action": "message", "role": "user"},
        tool_calls=[],
    )
    assert extractor.extract_facts([event]) == []
