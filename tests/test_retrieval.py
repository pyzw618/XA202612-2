"""retrieval 模块单元测试：关键词/向量/混合检索、缓存与 API 路由。"""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
)
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher, _tokenize
from memoryhub.retrieval.reranker import Reranker
from memoryhub.retrieval.vector_search import VectorSearcher

DIM = 8

_DOCS = [
    (
        "pref_1",
        "项目周报默认使用 Markdown 格式",
        {"memory_type": "preference", "scope": {"scene": "office"}, "confidence": 0.9},
    ),
    (
        "know_1",
        "项目周报生成流程：收集数据、生成摘要、发送邮件",
        {"memory_type": "knowledge", "scope": {"scene": "office"}, "confidence": 0.8},
    ),
    (
        "pref_2",
        "代码审查时偏好详细注释",
        {"memory_type": "preference", "scope": {"scene": "code"}, "confidence": 0.7},
    ),
]


def _build_keyword_searcher() -> KeywordSearcher:
    searcher = KeywordSearcher()
    searcher.build_index([(mid, content, json.dumps(meta)) for mid, content, meta in _DOCS])
    return searcher


def _build_vector_searcher() -> tuple[VectorSearcher, list[float]]:
    rng = np.random.default_rng(42)
    base = rng.random(DIM).tolist()
    searcher = VectorSearcher(dimension=DIM)
    for (memory_id, _, meta), noise in zip(_DOCS, [0.01, 0.05, 1.0]):
        vector = (np.array(base) + noise * rng.random(DIM)).tolist()
        searcher.add(memory_id, vector, metadata=dict(meta))
    return searcher, base


# ---------- KeywordSearcher ----------


def test_tokenize_keeps_chinese_english_digits():
    tokens = _tokenize("我的系统密码是Admin@123")
    assert "系统" in tokens
    assert "密码" in tokens
    assert "admin" in tokens
    assert "123" in tokens


def test_keyword_search_finds_by_keyword():
    searcher = _build_keyword_searcher()
    results = searcher.search("项目周报", top_k=2)
    assert results
    assert results[0].memory_id in ("pref_1", "know_1")
    assert all(r.source == "keyword" for r in results)
    assert results[0].content


def test_keyword_search_empty_index_returns_empty():
    searcher = KeywordSearcher()
    assert searcher.search("任意查询", top_k=5) == []


def test_keyword_search_delete_and_update():
    searcher = _build_keyword_searcher()
    # update：换成包含独特词项的内容，确保能被检索到
    searcher.update("pref_1", "项目周报改用麒麟笔记模板")
    results = searcher.search("麒麟笔记", top_k=1)
    assert results[0].memory_id == "pref_1"

    # delete：删除后不再出现在结果中
    assert searcher.delete("pref_2") is True
    assert searcher.delete("pref_2") is False
    assert all(r.memory_id != "pref_2" for r in searcher.search("代码审查", top_k=5))


# ---------- VectorSearcher ----------


def test_vector_search_returns_top_k():
    searcher, base = _build_vector_searcher()
    results = searcher.search(base, top_k=2)
    assert len(results) == 2
    assert results[0].memory_id == "pref_1"  # 与查询向量最接近
    assert all(r.source == "vector" for r in results)


def test_vector_search_dimension_mismatch_raises():
    searcher, _ = _build_vector_searcher()
    with pytest.raises(ValueError):
        searcher.add("bad", [0.1, 0.2])
    with pytest.raises(ValueError):
        searcher.search([0.1, 0.2])


def test_vector_search_delete_marks_removed():
    searcher, base = _build_vector_searcher()
    assert searcher.size() == 3
    assert searcher.delete("pref_2") is True
    assert searcher.delete("pref_2") is False
    assert all(r.memory_id != "pref_2" for r in searcher.search(base, top_k=5))
    searcher.rebuild_index()
    assert searcher.size() == 2


def test_vector_search_persistence_roundtrip(tmp_path):
    searcher, base = _build_vector_searcher()
    searcher.index_path = str(tmp_path / "vec.index")
    searcher.save_index()

    loaded = VectorSearcher(index_path=searcher.index_path, dimension=DIM)
    loaded.load_index()
    results = loaded.search(base, top_k=1)
    assert results and results[0].memory_id == "pref_1"
    assert results[0].metadata.get("memory_type") == "preference"


# ---------- HybridRetriever ----------


def _build_retriever(**overrides) -> HybridRetriever:
    keyword_search, _ = _build_keyword_searcher(), None
    vector_search, base = _build_vector_searcher()
    lookup = {
        "pref_1": PreferenceMemory(memory_id="pref_1"),
        "know_1": KnowledgeMemory(memory_id="know_1"),
        "pref_2": PreferenceMemory(memory_id="pref_2"),
    }
    kwargs = dict(
        vector_search=vector_search,
        keyword_search=keyword_search,
        reranker=Reranker(),
        embedding_fn=lambda query: base,
        memory_lookup=lookup,
    )
    kwargs.update(overrides)
    return HybridRetriever(**kwargs)


def test_hybrid_merge_result_count_and_formula():
    retriever = _build_retriever()
    request = SearchRequest(query="项目周报", context=SceneScope(scene="office"), top_k=3)
    response = retriever.search(request)

    # pref_2 的 scope 是 code，与请求 context(office) 冲突，被过滤
    assert response.total_count == len(response.results) == 2
    assert {r.memory_id for r in response.results} == {"pref_1", "know_1"}
    assert response.latency_ms > 0
    for result in response.results:
        expected = (
            0.6 * result.metadata["vector_score"]
            + 0.3 * result.metadata["keyword_score"]
            + 0.1 * result.metadata["metadata_score"]
        )
        assert result.score == pytest.approx(expected)


def test_hybrid_splits_preferences_and_knowledge():
    retriever = _build_retriever()
    response = retriever.search(SearchRequest(query="项目周报", top_k=3))
    pref_ids = {p.memory_id for p in response.preferences}
    know_ids = {k.memory_id for k in response.knowledge}
    assert pref_ids == {"pref_1", "pref_2"}
    assert know_ids == {"know_1"}


def test_hybrid_filters_by_memory_types_and_confidence():
    retriever = _build_retriever()
    response = retriever.search(
        SearchRequest(query="项目周报", top_k=5, memory_types=["knowledge"])
    )
    assert all(r.memory_type == "knowledge" for r in response.results)

    response = retriever.search(SearchRequest(query="项目周报", top_k=5, min_confidence=0.85))
    assert all(r.metadata.get("confidence", 1.0) >= 0.85 for r in response.results)


def test_hybrid_filters_scope_conflict():
    retriever = _build_retriever()
    response = retriever.search(
        SearchRequest(query="项目周报", context=SceneScope(scene="code"), top_k=5)
    )
    assert all(
        r.metadata.get("scope", {}).get("scene") != "office" for r in response.results
    )


def test_hybrid_works_without_vector_route():
    keyword_search = _build_keyword_searcher()
    retriever = HybridRetriever(keyword_search=keyword_search)
    response = retriever.search(SearchRequest(query="项目周报", top_k=2))
    assert response.total_count == 2


# ---------- SearchCache ----------


def test_cache_hit_and_miss():
    cache = SearchCache(max_size=10, ttl_seconds=300)
    keyword_search = _build_keyword_searcher()
    retriever = HybridRetriever(keyword_search=keyword_search, cache=cache)
    request = SearchRequest(query="项目周报", top_k=2)

    assert cache.get(request) is None  # 未命中
    response = retriever.search(request)
    assert cache.get(request) is response  # 命中
    assert retriever.search(request) is response


def test_cache_ttl_expiry():
    cache = SearchCache(max_size=10, ttl_seconds=0)
    keyword_search = _build_keyword_searcher()
    retriever = HybridRetriever(keyword_search=keyword_search, cache=cache)
    request = SearchRequest(query="项目周报", top_k=2)
    retriever.search(request)
    time.sleep(0.01)
    assert cache.get(request) is None


def test_cache_invalidate_by_memory_id():
    cache = SearchCache(max_size=10, ttl_seconds=300)
    retriever = _build_retriever(cache=cache)
    request = SearchRequest(query="项目周报", top_k=3)
    retriever.search(request)
    assert cache.size() == 1
    cache.invalidate("pref_1")
    assert cache.size() == 0


# ---------- API 路由 ----------


def test_search_api_returns_json():
    from fastapi.testclient import TestClient

    from memoryhub.app import create_app

    app = create_app()
    with TestClient(app) as client:
        # 用预置数据的检索器替换启动时装配的空检索器
        app.state.retriever = _build_retriever()
        resp = client.post(
            "/api/memory/search",
            json={"query": "项目周报", "top_k": 3, "context": {"scene": "office"}},
        )
        assert resp.status_code == 200
        payload = resp.json()
        # pref_2 的 scope 是 code，与请求 context(office) 冲突，被过滤
        assert payload["total_count"] == 2
        assert payload["latency_ms"] > 0
        assert [p["memory_id"] for p in payload["preferences"]] == ["pref_1"]
        assert [k["memory_id"] for k in payload["knowledge"]] == ["know_1"]


def test_search_api_503_when_retriever_not_initialized():
    from fastapi.testclient import TestClient

    from memoryhub.app import create_app

    # 不使用 context manager，startup 不执行，retriever 未初始化
    client = TestClient(create_app())
    resp = client.post("/api/memory/search", json={"query": "项目周报", "top_k": 3})
    assert resp.status_code == 503
