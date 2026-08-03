# -*- coding: utf-8 -*-
"""MilvusHybridRetriever + milvus_mock 引擎集成测试。

通过工厂 provider="milvus_mock" 建引擎，embedding 用确定性的
bag-of-words 假向量（稠密路也按 token 重合度区分），验证：
- search 返回结构与 HybridRetriever 兼容（SearchResponse/SearchResult）
- 相关记忆排前、top_k 生效
- memory_types / min_confidence / scope 过滤
- preferences/knowledge 由 memory_lookup 补全
"""

import pytest

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
    SearchResponse,
)
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever, _memory_text
from memoryhub.storage.vector_engine import build_sparse_vector, create_vector_engine

DIM = 768


def _bow_embedding(text: str) -> list[float]:
    """确定性假 embedding：稀疏 token 投影到 DIM 维，token 重合越多越相似。"""
    vec = [0.0] * DIM
    for index, weight in build_sparse_vector(text):
        vec[index % DIM] += weight
    return vec


@pytest.fixture()
def memories():
    return [
        PreferenceMemory(
            memory_id="pref_001",
            text="项目周报默认使用 Markdown 格式",
            scope=SceneScope(scene="office", task_type="office.weekly_report"),
            confidence=0.9,
        ),
        KnowledgeMemory(
            memory_id="know_001",
            name="周报生成流程",
            content="收集事件、生成大纲、填充模板",
            scope=SceneScope(scene="office", task_type="office.weekly_report"),
            confidence=0.85,
        ),
        PreferenceMemory(
            memory_id="pref_002",
            text="I prefer Python over Java for scripting",
            confidence=0.4,
        ),
        PreferenceMemory(
            memory_id="pref_003",
            text="今天天气很好适合散步",
            confidence=0.6,
        ),
    ]


@pytest.fixture()
def retriever(memories):
    engine = create_vector_engine(
        provider="milvus_mock",
        collection="test_milvus_hybrid",
        dimension=DIM,
    )
    lookup = {m.memory_id: m for m in memories}
    for memory in memories:
        text = _memory_text(memory)
        engine.insert(memory.memory_id, text, _bow_embedding(text))
    yield MilvusHybridRetriever(
        engine=engine,
        embedding_fn=_bow_embedding,
        memory_lookup=lookup,
    )
    engine.close()


class TestMilvusHybridRetriever:
    def test_search_structure(self, retriever):
        resp = retriever.search(SearchRequest(query="周报", top_k=5))
        assert isinstance(resp, SearchResponse)
        assert resp.total_count > 0
        assert resp.latency_ms >= 0
        for result in resp.results:
            assert result.source == "hybrid"
            assert result.memory_id
            assert result.memory_type in ("preference", "knowledge")
            assert isinstance(result.score, float)

    def test_relevant_memory_ranks_first(self, retriever):
        """查询与记忆共享稀疏 token，相关记忆应排最前。"""
        resp = retriever.search(SearchRequest(query="周报", top_k=5))
        top_ids = [r.memory_id for r in resp.results[:2]]
        # 两条周报相关记忆都应排在无关记忆之前
        assert set(top_ids) == {"pref_001", "know_001"}
        assert resp.results[0].score >= resp.results[-1].score

    def test_english_query(self, retriever):
        resp = retriever.search(SearchRequest(query="Python scripting", top_k=5))
        assert resp.results[0].memory_id == "pref_002"

    def test_top_k(self, retriever):
        resp = retriever.search(SearchRequest(query="周报", top_k=2))
        assert len(resp.results) == 2
        assert resp.total_count == 2

    def test_memory_types_filter(self, retriever):
        resp = retriever.search(
            SearchRequest(query="周报", top_k=5, memory_types=["knowledge"])
        )
        assert [r.memory_id for r in resp.results] == ["know_001"]
        assert resp.preferences == []
        assert [k.memory_id for k in resp.knowledge] == ["know_001"]

    def test_min_confidence_filter(self, retriever):
        resp = retriever.search(
            SearchRequest(query="周报", top_k=5, min_confidence=0.88)
        )
        assert [r.memory_id for r in resp.results] == ["pref_001"]

    def test_scope_conflict_filter(self, retriever):
        resp = retriever.search(
            SearchRequest(
                query="周报",
                top_k=5,
                context=SceneScope(scene="code", task_type="code.review"),
            )
        )
        # pref_001/know_001 的 scope 与请求冲突被过滤；pref_003 无 scope 信息保留
        ids = [r.memory_id for r in resp.results]
        assert "pref_001" not in ids
        assert "know_001" not in ids

    def test_response_full_memory_objects(self, retriever):
        """preferences/knowledge 由 memory_lookup 补全为完整记忆对象。"""
        resp = retriever.search(SearchRequest(query="周报", top_k=5))
        pref_ids = [p.memory_id for p in resp.preferences]
        know_ids = [k.memory_id for k in resp.knowledge]
        assert "pref_001" in pref_ids
        assert "know_001" in know_ids
        pref = resp.preferences[pref_ids.index("pref_001")]
        assert pref.text == "项目周报默认使用 Markdown 格式"
        assert pref.confidence == 0.9

    def test_empty_query(self, retriever):
        resp = retriever.search(SearchRequest(query="", top_k=5))
        assert resp.results == []
        assert resp.total_count == 0
