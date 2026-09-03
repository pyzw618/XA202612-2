# -*- coding: utf-8 -*-
"""RET-01 ~ RET-09 检索链路专项验收测试。

对应 old/docs/0811功能性测试/TEST_PLAN.md 6.8 检索链路(RET-01~09)，依据 old/docs/INTERFACE.md 5.2、
old/docs/ARCHITECTURE.md 3/8、old/docs/0805数据流测试/DATA_FLOW_UPDATE.md。
单元级驱动 HybridRetriever / MilvusHybridRetriever / Reranker / SearchCache /
KeywordSearcher / VectorSearcher；API 级驱动 /search 与 /context。
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from memoryhub.app import create_app
from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    RetrievalConfig,
    StorageConfig,
)
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher, _tokenize
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
from memoryhub.retrieval.reranker import Reranker
from memoryhub.retrieval.vector_search import VectorSearcher
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.models import PreferenceRow

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
        "代码审查时详细注释",
        {"memory_type": "preference", "scope": {"scene": "code"}, "confidence": 0.4},
    ),
]


def _doc_map() -> dict:
    return {mid: _meta_text(meta) for mid, _, meta in _DOCS}


def _meta_text(meta: dict) -> str:
    return f"{meta.get('memory_type')} {json.dumps(meta, ensure_ascii=False)}"


def _keyword_searcher() -> KeywordSearcher:
    searcher = KeywordSearcher()
    searcher.build_index([(mid, content, json.dumps(meta)) for mid, content, meta in _DOCS])
    return searcher


def _vector_searcher() -> tuple[VectorSearcher, list[float]]:
    rng = np.random.default_rng(42)
    base = rng.random(DIM).tolist()
    searcher = VectorSearcher(dimension=DIM)
    for (memory_id, _, meta), noise in zip(_DOCS, [0.01, 0.05, 1.0]):
        vector = (np.array(base) + noise * rng.random(DIM)).tolist()
        searcher.add(memory_id, vector, metadata=dict(meta))
    return searcher, base


def _lookup() -> dict:
    out = {}
    for memory_id, content, meta in _DOCS:
        scope = SceneScope(scene=meta["scope"]["scene"])
        if meta["memory_type"] == "knowledge":
            out[memory_id] = KnowledgeMemory(
                memory_id=memory_id,
                user_id="u1",
                name=content,
                content=content,
                scope=scope,
                confidence=meta["confidence"],
            )
        else:
            out[memory_id] = PreferenceMemory(
                memory_id=memory_id,
                user_id="u1",
                text=content,
                scope=scope,
                confidence=meta["confidence"],
            )
    return out


# ---------------------------------------------------------------------------
# RET-01 混合加权
# ---------------------------------------------------------------------------


def test_ret_01_hybrid_weighted_merges_three_routes() -> None:
    vector_searcher, base = _vector_searcher()
    retriever = HybridRetriever(
        vector_search=vector_searcher,
        keyword_search=_keyword_searcher(),
        embedding_fn=lambda _q: base,
        memory_lookup=_lookup(),
        config=RetrievalConfig(rerank_enabled=False),
    )
    request = SearchRequest(user_id="u1", query="项目周报", top_k=5)
    response = retriever.search(request)

    # final = 0.6V + 0.3K + 0.1M
    assert len(response.results) > 0
    for result in response.results:
        v = result.metadata.get("vector_score", 0.0)
        k = result.metadata.get("keyword_score", 0.0)
        m = result.metadata.get("metadata_score", 0.0)
        expected = 0.6 * v + 0.3 * k + 0.1 * m
        assert abs(result.score - expected) < 1e-9, (result.memory_id, result.score, expected)


# ---------------------------------------------------------------------------
# RET-02 向量引擎切换
# ---------------------------------------------------------------------------


class FakeEngine:
    """模拟 BaseVectorEngine：hybrid_search 返回与 FAISS 相同的命中集合。"""

    def __init__(self, ids: list[str]):
        self._ids = ids
        self.deleted: list[str] = []
        self.last_filters = None

    def hybrid_search(self, dense_vector, sparse_vector, top_k, filters=None, **kwargs):
        from memoryhub.storage.vector_engine import VectorSearchResult
        self.last_filters = filters
        return [
            VectorSearchResult(memory_id=mid, content="x", score=0.9, metadata={})
            for mid in self._ids[:top_k]
        ]

    def delete(self, memory_id):
        self.deleted.append(memory_id)


def test_ret_02_vector_engine_switch_keeps_results_and_filters() -> None:
    # FAISS 路径（HybridRetriever）
    faiss_searcher, base = _vector_searcher()
    faiss_response = HybridRetriever(
        vector_search=faiss_searcher,
        embedding_fn=lambda _q: base,
        memory_lookup=_lookup(),
        config=RetrievalConfig(rerank_enabled=False),
    ).search(SearchRequest(user_id="u1", query="项目周报", top_k=3))

    # Milvus 路径（MilvusHybridRetriever）返回同集合
    engine = FakeEngine([mid for mid, _, _ in _DOCS])
    milvus_response = MilvusHybridRetriever(
        engine=engine,
        embedding_fn=lambda _q: base,
        memory_lookup=_lookup(),
    ).search(SearchRequest(user_id="u1", query="项目周报", top_k=3))

    faiss_ids = sorted(r.memory_id for r in faiss_response.results)
    milvus_ids = sorted(r.memory_id for r in milvus_response.results)
    assert faiss_ids == milvus_ids

    # 引擎侧携带 user/status 过滤（RET-02 隔离语义）
    assert engine.last_filters["user_id"] == "u1"
    assert engine.last_filters["status"] == "active"


from memoryhub.storage.vector_engine import build_sparse_vector  # noqa: E402


def test_ret_02_sparse_vector_deterministic_across_calls() -> None:
    a = build_sparse_vector("数据库登录密码 Admin123")
    b = build_sparse_vector("数据库登录密码 Admin123")
    assert a == b
    assert a and all(isinstance(i, int) and isinstance(w, float) for i, w in a)


# ---------------------------------------------------------------------------
# RET-03 BM25 关键词
# ---------------------------------------------------------------------------


def test_ret_03_bm25_hits_exact_keyword_and_jieba_tokenize() -> None:
    tokens = _tokenize("数据库登录密码是Admin@123")
    assert "数据库" in tokens and "密码" in tokens
    assert "admin" in tokens and "123" in tokens

    searcher = _keyword_searcher()
    results = searcher.search("周报", top_k=5)
    hit_ids = {r.memory_id for r in results}
    assert "pref_1" in hit_ids
    assert "know_1" in hit_ids


# ---------------------------------------------------------------------------
# RET-04 scope/置信度过滤
# ---------------------------------------------------------------------------


def test_ret_04_scope_and_confidence_filtered() -> None:
    retriever = HybridRetriever(
        keyword_search=_keyword_searcher(),
        memory_lookup=_lookup(),
        config=RetrievalConfig(rerank_enabled=False),
    )
    # 场景冲突 → 过滤
    request = SearchRequest(
        user_id="u1", query="周报", context=SceneScope(scene="code"), top_k=5
    )
    response = retriever.search(request)
    assert all(r.metadata.get("scope", {}).get("scene") != "office" for r in response.results)

    # 置信度过滤 → pref_2(0.4) 被过滤
    request2 = SearchRequest(user_id="u1", query="代码", top_k=5, min_confidence=0.5)
    response2 = retriever.search(request2)
    assert "pref_2" not in {r.memory_id for r in response2.results}


# ---------------------------------------------------------------------------
# RET-05 重排序因子
# ---------------------------------------------------------------------------


def test_ret_05_rerank_factors_scope_freshness_health() -> None:
    old = SearchResult(
        memory_id="m_old", content="周报流程", score=0.5,
        metadata={"health_score": 0.2, "scope": {"scene": "office"}, "created_at": "2020-01-01"},
    )
    fresh = SearchResult(
        memory_id="m_fresh", content="周报流程", score=0.5,
        metadata={"health_score": 0.9, "scope": {"scene": "office"}, "created_at": "2026-08-01"},
    )
    reranker = Reranker()
    request = SearchRequest(user_id="u1", query="周报", context=SceneScope(scene="office"))

    reranked = reranker.rerank([old, fresh], request)

    assert reranked[0].memory_id == "m_fresh"
    for r in reranked:
        for key in ("rerank_score", "relevance_score", "scope_score",
                    "freshness_score", "health_score"):
            assert key in r.metadata


# ---------------------------------------------------------------------------
# RET-06 LRU 缓存
# ---------------------------------------------------------------------------


def test_ret_06_lru_hit_ttl_and_invalidate() -> None:
    cache = SearchCache(max_size=10, ttl_seconds=300)
    request = SearchRequest(user_id="u1", query="周报")
    response = _fake_response(["pref_1"])

    assert cache.get(request) is None
    cache.set(request, response)
    assert cache.get(request).total_count == 1

    # TTL 过期
    cache_short = SearchCache(max_size=10, ttl_seconds=0)
    cache_short.set(request, response)
    import time as _time
    _time.sleep(0.01)
    assert cache_short.get(request) is None

    # invalidate 命中记忆的条目
    cache.set(SearchRequest(user_id="u1", query="周报2"), _fake_response(["pref_1", "pref_2"]))
    cache.invalidate("pref_1")
    assert cache.size() == 0


def _fake_response(ids: list[str]) -> SearchResponse:
    return SearchResponse(
        results=[SearchResult(memory_id=mid, content="x", score=1.0) for mid in ids],
        total_count=len(ids),
    )


# ---------------------------------------------------------------------------
# RET-07 /context 与 RET-08 访问统计、RET-09 空库空查询
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_config(tmp_path):
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path=db_path)
    db.init_schema()

    pref = PreferenceMemory(
        user_id="u1", text="项目周报默认使用 Markdown 格式",
        scope=SceneScope(scene="office"), confidence=0.9,
    )
    know = KnowledgeMemory(
        user_id="u1", name="周报生成流程", content="收集事件、生成摘要",
        scope=SceneScope(scene="office"), confidence=0.85,
    )
    PreferenceRepository(db).save(pref)
    KnowledgeRepository(db).save(know)
    db.close()

    config = AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="mock", dimension=64),
    )
    config._seeded = (pref, know)
    return config


def test_ret_07_context_returns_joinable_prompt_text(seeded_config) -> None:
    with TestClient(create_app(seeded_config)) as client:
        resp = client.post(
            "/api/memory/context",
            json={"user_id": "u1", "query": "周报", "top_k": 5},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["context"]
    assert "周报" in body["context"]
    assert "Markdown" in body["context"]
    assert body.get("context_text") == body.get("context")


def test_ret_08_search_updates_access_stats(seeded_config) -> None:
    pref, _know = seeded_config._seeded
    with TestClient(create_app(seeded_config)) as client:
        client.post("/api/memory/search", json={"user_id": "u1", "query": "周报", "top_k": 5})
        client.post("/api/memory/search", json={"user_id": "u1", "query": "周报", "top_k": 5})
    db = Database(seeded_config.storage.db_path)
    db.init_schema()
    with db.session() as s:
        row = s.query(PreferenceRow).filter_by(memory_id=pref.memory_id).one()
        assert row.access_count_30d >= 2
        assert row.last_accessed_at is not None
    db.close()


def test_ret_09_empty_query_and_empty_db(tmp_path) -> None:
    retriever = HybridRetriever(
        vector_search=_vector_searcher()[0],
        keyword_search=_keyword_searcher(),
        embedding_fn=lambda _q: np.zeros(DIM).tolist(),
        memory_lookup=_lookup(),
        config=RetrievalConfig(rerank_enabled=False),
    )
    # 空查询：不报错，返回空
    empty_query = retriever.search(SearchRequest(user_id="u1", query="", top_k=5))
    assert empty_query.total_count == 0

    # 空库：不报错，返回空
    db_path = str(tmp_path / "empty.db")
    db = Database(db_path)
    db.init_schema()
    empty_retriever = HybridRetriever(
        keyword_search=KeywordSearcher(),
        memory_lookup={},
        config=RetrievalConfig(rerank_enabled=False),
    )
    response = empty_retriever.search(SearchRequest(user_id="u1", query="周报", top_k=5))
    assert response.total_count == 0
    db.close()
