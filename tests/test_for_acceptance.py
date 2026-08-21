# -*- coding: utf-8 -*-
"""FOR-01 ~ FOR-07 遗忘模块专项验收测试。

对应 docs/tests/0811功能性测试/TEST_PLAN.md 6.7 遗忘模块(FOR-01~07)，依据 forget_module_v1.md。
每个测试驱动真实实现：MemoryForgetter / AutoForgetEngine / HealthCalculator /
Reranker（被动遗忘）/ ForgetRepository，对应用例矩阵列出通过/失败记录。
"""

from __future__ import annotations

from pathlib import Path

from memoryhub.adapter.schemas import (
    ForgetRequest,
    KnowledgeMemory,
    KnowledgeType,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
    SearchResult,
)
from memoryhub.core.forget.auto_forget import AutoForgetEngine
from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.reranker import Reranker
from memoryhub.storage.database import (
    Database,
    ForgetRepository,
    KnowledgeRepository,
    PreferenceRepository,
)


class FakeVectorEngine:
    def __init__(self):
        self.deleted: list[str] = []
        self.persist_count = 0

    def delete(self, memory_id):
        self.deleted.append(memory_id)

    def persist(self):
        self.persist_count += 1


class FakeVectorStore:
    def __init__(self):
        self.deleted: list[str] = []
        self.save_count = 0

    def delete(self, memory_id):
        self.deleted.append(memory_id)

    def save(self):
        self.save_count += 1


class FakeKeywordSearch:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, memory_id):
        self.deleted.append(memory_id)


class FakeEvidenceStore:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, memory_id):
        self.deleted.append(memory_id)


class FakeConflictRepo:
    def __init__(self):
        self.deleted_for: list[list[str]] = []

    def delete_for_memories(self, memory_ids):
        self.deleted_for.append(list(memory_ids))


class FixedCalculator:
    """返回固定健康度的计算器，用于 FOR-05 阈值判定。"""

    def __init__(self, health):
        self.health = health

    def calculate(self, memory):
        return self.health

    def calculate_from_row(self, row):
        return self.health


class MappedCalculator:
    """按 memory_id 返回各自健康度，避免互相干扰。"""

    def __init__(self, mapping):
        self.mapping = mapping

    def _health(self, obj) -> float:
        memory_id = getattr(obj, "memory_id", None) or getattr(obj, "fact_id", None)
        return self.mapping.get(memory_id, 1.0)

    def calculate(self, memory):
        return self._health(memory)

    def calculate_from_row(self, row):
        return self._health(row)


def _make_repos(tmp_path: Path):
    db = Database(str(tmp_path / "for.db"))
    db.init_schema()
    return db, PreferenceRepository(db), KnowledgeRepository(db)


def _pref(memory_id: str, text: str, scene: str = "office", user_id: str = "u1"):
    return PreferenceMemory(
        memory_id=memory_id,
        user_id=user_id,
        text=text,
        scope=SceneScope(scene=scene),
        confidence=0.9,
    )


def _know(memory_id: str, name: str, content: str, scene: str = "office", user_id: str = "u1"):
    return KnowledgeMemory(
        memory_id=memory_id,
        user_id=user_id,
        name=name,
        content=content,
        scope=SceneScope(scene=scene),
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# FOR-01 精确 ID 删除
# ---------------------------------------------------------------------------


def test_for_01_exact_id_soft_delete_and_audit(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    pref_repo.save(_pref("pref_a", "项目周报默认使用 Markdown"))
    pref_repo.save(_pref("pref_b", "代码审查偏好详细注释", scene="code"))

    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo, storage=db)
    response = forgetter.execute(ForgetRequest(
        user_id="u1", target_memory_ids=["pref_a"],
    ))

    assert response.deleted_count == 1
    assert response.deleted_ids == ["pref_a"]
    assert response.record_id
    assert pref_repo.get_by_id("pref_a").status.value == "deleted"
    assert pref_repo.get_by_id("pref_b").status.value == "active"
    db.close()


# ---------------------------------------------------------------------------
# FOR-02 范围删除
# ---------------------------------------------------------------------------


def test_for_02_scope_delete_batches_by_scene(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    pref_repo.save(_pref("p_office", "周报使用 Markdown", scene="office"))
    pref_repo.save(_pref("p_code", "代码用 4 空格缩进", scene="code"))
    know_repo.save(_know("k_office", "周报生成流程", "收集数据生成摘要", scene="office"))
    know_repo.save(_know("k_code", "重构流程", "提取函数", scene="code"))

    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo, storage=db)
    response = forgetter.execute(ForgetRequest(
        user_id="u1", target_scope=SceneScope(scene="office"),
    ))

    assert response.deleted_count == 2
    assert sorted(response.deleted_ids) == ["k_office", "p_office"]
    assert pref_repo.get_by_id("p_office").status.value == "deleted"
    assert pref_repo.get_by_id("p_code").status.value == "active"
    assert know_repo.get_by_id("k_code").status.value == "active"
    db.close()


def test_for_02_scope_delete_filters_by_user(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    pref_repo.save(_pref("p_u1", "周报使用 Markdown", scene="office", user_id="u1"))
    pref_repo.save(_pref("p_u2", "周报使用 PDF", scene="office", user_id="u2"))

    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo, storage=db)
    response = forgetter.execute(ForgetRequest(
        user_id="u1", target_scope=SceneScope(scene="office"),
    ))

    assert response.deleted_ids == ["p_u1"]
    assert pref_repo.get_by_id("p_u2").status.value == "active"
    db.close()


# ---------------------------------------------------------------------------
# FOR-03 自然语言定位
# ---------------------------------------------------------------------------


def test_for_02_scope_delete_by_task_type_and_app(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    pref_repo.save(PreferenceMemory(
        memory_id="p_weekly", user_id="u1", text="周报格式 Markdown",
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
        confidence=0.9,
    ))
    pref_repo.save(PreferenceMemory(
        memory_id="p_review", user_id="u1", text="代码审查注释",
        scope=SceneScope(scene="code", task_type="code.review"),
        confidence=0.9,
    ))

    # 只按 task_type 定位：不应误伤其他 scene 的记忆
    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo, storage=db)
    response = forgetter.execute(ForgetRequest(
        user_id="u1", target_scope=SceneScope(task_type="code.review"),
    ))
    assert response.deleted_ids == ["p_review"]
    assert pref_repo.get_by_id("p_weekly").status.value == "active"
    db.close()


def test_for_03_natural_language_keyword_locate_and_cascade(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    engine = FakeVectorEngine()
    store = FakeVectorStore()
    kws = FakeKeywordSearch()
    lookup = {}
    cache = SearchCache(max_size=10)

    pref_repo.save(_pref("p_wb", "周报格式偏好 Markdown"))
    know_repo.save(_know("k_wb", "周报模板", "周报生成流程"))
    pref_repo.save(_pref("p_other", "代码审查时详细注释", scene="code"))
    for mid, mem in [("p_wb", pref_repo.get_by_id("p_wb")),
                     ("k_wb", know_repo.get_by_id("k_wb")),
                     ("p_other", pref_repo.get_by_id("p_other"))]:
        lookup[mid] = mem

    forgetter = MemoryForgetter(
        pref_repo=pref_repo,
        know_repo=know_repo,
        vector_engine=engine,
        vector_store=store,
        keyword_search=kws,
        memory_lookup=lookup,
        cache=cache,
        storage=db,
    )
    response = forgetter.execute(ForgetRequest(
        user_id="u1", instruction="忘掉周报格式偏好",
    ))

    # 指令命中 preference 类型：仅偏好被定位，知识记忆不受影响
    assert response.deleted_ids == ["p_wb"]
    # 级联清理
    assert engine.deleted == ["p_wb"]
    assert store.deleted == ["p_wb"]
    assert kws.deleted == ["p_wb"]
    assert "p_wb" not in lookup
    assert pref_repo.get_by_id("p_wb").status.value == "deleted"
    assert pref_repo.get_by_id("p_other").status.value == "active"
    assert know_repo.get_by_id("k_wb").status.value == "active"
    db.close()


# ---------------------------------------------------------------------------
# FOR-04 级联一致性
# ---------------------------------------------------------------------------


def _make_fact(know_repo, user_id: str = "u1") -> KnowledgeMemory:
    """通过知识仓储写入一条全局事实性知识（knowledge_type=FACT）。"""
    fact = KnowledgeMemory(
        memory_id=f"fact_for_{user_id}",
        user_id=user_id,
        knowledge_type=KnowledgeType.FACT,
        subject="项目周报",
        predicate="负责人",
        object_value="张三",
        object_type="Person",
        single_value=True,
        content="项目周报的负责人是张三",
        confidence=0.9,
    )
    know_repo.save(fact)
    return fact


def test_for_04_cascade_cleans_evidence_conflicts_and_indexes(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    fact = _make_fact(know_repo)
    engine = FakeVectorEngine()
    store = FakeVectorStore()
    kws = FakeKeywordSearch()
    evidence = FakeEvidenceStore()
    conflicts = FakeConflictRepo()
    cache = SearchCache(max_size=10)
    lookup = {}

    pref_repo.save(_pref("pref_c", "周报使用 Markdown"))
    know_repo.save(_know("know_c", "周报流程", "收集数据"))
    for mid, mem in [("pref_c", pref_repo.get_by_id("pref_c")),
                     ("know_c", know_repo.get_by_id("know_c")),
                     (fact.memory_id, fact)]:
        lookup[mid] = mem

    # 缓存中预置一条包含 pref_c 的响应，验证 invalidate
    cache.set(SearchRequest(user_id="u1", query="周报"), _fake_response("pref_c"))

    forgetter = MemoryForgetter(
        pref_repo=pref_repo, know_repo=know_repo,
        vector_engine=engine, vector_store=store, keyword_search=kws,
        memory_lookup=lookup, evidence_store=evidence, conflict_repo=conflicts,
        cache=cache, storage=db,
    )
    response = forgetter.execute(ForgetRequest(
        user_id="u1", instruction="忘掉周报相关",
    ))

    assert response.deleted_count == 3
    ids = set(response.deleted_ids)
    assert {"pref_c", "know_c", fact.memory_id} <= ids
    # SQLite 软删除
    assert pref_repo.get_by_id("pref_c").status.value == "deleted"
    assert know_repo.get_by_id("know_c").status.value == "deleted"
    assert know_repo.get_by_id(fact.memory_id).status.value == "deleted"
    # 向量 / BM25 / lookup / 证据 / conflicts / 缓存全部清理
    assert set(engine.deleted) == ids
    assert set(store.deleted) == ids
    assert set(kws.deleted) == ids
    assert set(evidence.deleted) == ids
    assert "pref_c" not in lookup
    assert cache.size() == 0
    assert know_repo.get_by_type("u1", knowledge_type="fact", status="active") == []
    db.close()


def _fake_response(memory_id: str):
    from memoryhub.adapter.schemas import SearchResponse
    return SearchResponse(
        results=[SearchResult(memory_id=memory_id, content="x", score=1.0)],
    )


# ---------------------------------------------------------------------------
# FOR-05 自动遗忘阈值
# ---------------------------------------------------------------------------


def test_for_05_auto_forget_archive_demote_review(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    cases = [
        ("pref_low", "低健康度偏好", MemoryStatus.ARCHIVED, MemoryLevel.MID, 0.1),
        ("pref_demote", "待降级偏好", MemoryStatus.ACTIVE, MemoryLevel.SHORT, 0.3),
        ("pref_review", "待审查偏好", MemoryStatus.PENDING, MemoryLevel.MID, 0.5),
        ("pref_keep", "健康偏好", MemoryStatus.ACTIVE, MemoryLevel.MID, 0.9),
    ]
    for mid, text, _, _, _ in cases:
        pref_repo.save(_pref(mid, text))

    engine = AutoForgetEngine(
        pref_repo=pref_repo, know_repo=know_repo, db=db,
        calculator=MappedCalculator({mid: health for mid, _, _, _, health in cases}),
    )
    engine.run()

    for mid, _, expected_status, expected_level, _ in cases:
        updated = pref_repo.get_by_id(mid)
        assert updated.status == expected_status, f"{mid}: {updated.status}"
        assert updated.level == expected_level, f"{mid}: {updated.level}"
    db.close()


def test_for_05_fact_low_health_archived(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    fact = _make_fact(know_repo)

    engine = AutoForgetEngine(
        pref_repo=pref_repo, know_repo=know_repo, db=db,
        calculator=FixedCalculator(0.1),
    )
    stats = engine.run()

    assert stats["archived"] >= 1
    assert know_repo.get_by_id(fact.memory_id).status.value == "archived"
    db.close()


# ---------------------------------------------------------------------------
# FOR-06 被动遗忘：低健康度排序靠后但数据保留
# ---------------------------------------------------------------------------


def test_for_06_passive_forget_ranks_but_keeps_data() -> None:
    healthy = SearchResult(
        memory_id="m_healthy", content="周报流程", score=0.5,
        metadata={"health_score": 0.9, "scope": {"scene": "office"}},
    )
    unhealthy = SearchResult(
        memory_id="m_unhealthy", content="周报流程", score=0.5,
        metadata={"health_score": 0.1, "scope": {"scene": "office"}},
    )
    reranker = Reranker()
    request = SearchRequest(user_id="u1", query="周报", context=SceneScope(scene="office"))

    reranked = reranker.rerank([healthy, unhealthy], request)

    assert reranked[0].memory_id == "m_healthy"
    assert {r.memory_id for r in reranked} == {"m_healthy", "m_unhealthy"}
    assert reranked[0].metadata["health_score"] == 0.9


# ---------------------------------------------------------------------------
# FOR-07 遗忘历史（user 隔离）
# ---------------------------------------------------------------------------


def test_for_07_forget_history_records_and_isolates_users(tmp_path: Path) -> None:
    db, pref_repo, know_repo = _make_repos(tmp_path)
    repo = ForgetRepository(db)
    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo, storage=db)

    for i in range(3):
        pref_repo.save(_pref(f"pref_h{i}", f"偏好{i}"))
    forgetter.execute(ForgetRequest(user_id="u1", target_memory_ids=["pref_h0"]))
    forgetter.execute(ForgetRequest(user_id="u1", target_memory_ids=["pref_h1", "pref_h2"]))
    # 其他用户的历史不受影响
    forgetter.execute(ForgetRequest(user_id="u2", target_memory_ids=["pref_h0"]))

    history_u1 = repo.get_history("u1")
    history_u2 = repo.get_history("u2")

    assert len(history_u1) == 2
    assert all(r.user_id == "u1" for r in history_u1)
    target_sets = {tuple(sorted(r.target_memory_ids)) for r in history_u1}
    assert tuple(sorted(["pref_h0"])) in target_sets
    assert tuple(sorted(["pref_h1", "pref_h2"])) in target_sets
    assert len(history_u2) == 1
    assert history_u2[0].user_id == "u2"
    db.close()
