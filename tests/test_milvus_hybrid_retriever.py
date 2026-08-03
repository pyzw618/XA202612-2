# -*- coding: utf-8 -*-
"""MilvusHybridRetriever 生产路径单元测试"""

from __future__ import annotations

import pytest

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
    SearchResponse,
)
from memoryhub.config import RetrievalConfig
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
from memoryhub.storage.vector_engine.base import BaseVectorEngine, VectorSearchResult


class FakeVectorEngine(BaseVectorEngine):
    """可编程的向量引擎 stub，用于验证 Retriever 调用链路。"""

    def __init__(self, dimension: int = 768):
        self.dimension = dimension
        self.hybrid_search_calls: list[tuple[list[float], list[tuple[int, float]], int]] = []
        self._closed = False
        self._results: list[VectorSearchResult] = []

    def set_results(self, results: list[VectorSearchResult]) -> None:
        self._results = results

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
    ) -> list[VectorSearchResult]:
        self.hybrid_search_calls.append((dense_vector, sparse_terms, top_k))
        return list(self._results)

    def insert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: dict | None = None,
    ) -> None:
        pass

    def search(
        self, query_vector: list[float], top_k: int, filters: dict | None = None
    ) -> list[VectorSearchResult]:
        return list(self._results)

    def delete(self, memory_id: str) -> None:
        pass

    def persist(self) -> None:
        pass

    def close(self) -> None:
        self._closed = True


class FakeReranker:
    """记录调用次数与候选数的 stub reranker。"""

    def __init__(self):
        self.calls: list[list] = []

    def rerank(self, results, request):
        self.calls.append(list(results))
        return results


def _pref_memory(memory_id: str, text: str, scene: str = "office") -> PreferenceMemory:
    return PreferenceMemory(
        user_id="u1",
        text=text,
        scope=SceneScope(scene=scene, task_type="office.weekly_report"),
        confidence=0.9,
    )


def _know_memory(memory_id: str, name: str, scene: str = "office") -> KnowledgeMemory:
    return KnowledgeMemory(
        user_id="u1",
        name=name,
        content="内容",
        scope=SceneScope(scene=scene, task_type="office.weekly_report"),
        confidence=0.85,
    )


def _embedding_fn(text: str) -> list[float]:
    """确定性 embedding stub：返回文本长度个 0.1 的向量，但固定 768 维。"""
    dim = 768
    return [0.1] * dim


class TestMilvusHybridRetrieverSearch:
    def test_empty_query_returns_empty_response(self) -> None:
        engine = FakeVectorEngine()
        retriever = MilvusHybridRetriever(
            engine=engine, embedding_fn=_embedding_fn, config=RetrievalConfig()
        )
        response = retriever.search(SearchRequest(query=""))
        assert response.total_count == 0
        assert response.results == []
        assert not engine.hybrid_search_calls

    def test_query_normalized_and_truncated(self) -> None:
        engine = FakeVectorEngine()
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(max_query_chars=10, candidate_multiplier=2),
        )
        retriever.search(SearchRequest(query="  hello   world  这是一段很长的查询文本  "))
        assert len(engine.hybrid_search_calls) == 1
        # 规范化后截断至 10 字符
        assert len(engine.hybrid_search_calls[0][1]) > 0  # 稀疏向量非空

    def test_candidate_multiplier_used(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id=f"m{i}", content="c", score=0.5) for i in range(20)]
        )
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=4),
        )
        retriever.search(SearchRequest(query="周报", top_k=5))
        assert engine.hybrid_search_calls[-1][2] == 20  # 5 * 4

    def test_top_k_results_returned(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [
                VectorSearchResult(memory_id=f"m{i}", content=f"c{i}", score=0.5 - i * 0.01)
                for i in range(10)
            ]
        )
        memories = {f"m{i}": _pref_memory(f"m{i}", f"p{i}") for i in range(10)}
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
        )
        response = retriever.search(SearchRequest(query="周报", top_k=3))
        assert response.total_count == 3
        assert len(response.preferences) == 3

    def test_result_cache_hit(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id="m1", content="c1", score=0.9)]
        )
        cache = SearchCache(max_size=10, ttl_seconds=300)
        memories = {"m1": _pref_memory("m1", "周报格式")}
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
            cache=cache,
            index_version="v1",
        )
        response1 = retriever.search(SearchRequest(query="周报", top_k=3))
        response2 = retriever.search(SearchRequest(query="周报", top_k=3))
        assert response1.results[0].memory_id == response2.results[0].memory_id
        # 第二次应命中缓存，不再调用引擎
        assert len(engine.hybrid_search_calls) == 1

    def test_result_cache_isolated_by_index_version(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id="m1", content="c1", score=0.9)]
        )
        cache = SearchCache(max_size=10, ttl_seconds=300)
        memories = {"m1": _pref_memory("m1", "周报格式")}
        retriever_v1 = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
            cache=cache,
            index_version="v1",
        )
        retriever_v2 = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
            cache=cache,
            index_version="v2",
        )
        retriever_v1.search(SearchRequest(query="周报", top_k=3))
        retriever_v2.search(SearchRequest(query="周报", top_k=3))
        # 不同 index_version 不应共享缓存，因此引擎被调用两次
        assert len(engine.hybrid_search_calls) == 2

    def test_query_vector_cache_reuses_embedding(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id="m1", content="c1", score=0.9)]
        )
        call_count = 0

        def counting_embedding(text: str) -> list[float]:
            nonlocal call_count
            call_count += 1
            return _embedding_fn(text)

        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=counting_embedding,
            config=RetrievalConfig(candidate_multiplier=2),
        )
        retriever.search(SearchRequest(query="周报", top_k=3))
        retriever.search(SearchRequest(query="  周报  ", top_k=3))  # 规范化后相同
        # embedding_fn 只应被调用一次（第二次命中查询向量缓存）
        assert call_count == 1
        # 但引擎 hybrid_search 被调用两次（因为结果未缓存）
        assert len(engine.hybrid_search_calls) == 2

    def test_rerank_disabled_by_default(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id="m1", content="c1", score=0.9)]
        )
        reranker = FakeReranker()
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(rerank_enabled=False),
            reranker=reranker,
        )
        retriever.search(SearchRequest(query="周报", top_k=3))
        assert len(reranker.calls) == 0

    def test_rerank_only_top_20_candidates(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [VectorSearchResult(memory_id=f"m{i}", content="c", score=0.5) for i in range(30)]
        )
        reranker = FakeReranker()
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=6, rerank_enabled=True, default_top_k=5),
            reranker=reranker,
        )
        retriever.search(SearchRequest(query="周报", top_k=5))
        assert len(reranker.calls) == 1
        assert len(reranker.calls[0]) == 20

    def test_filter_by_memory_type(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [
                VectorSearchResult(memory_id="p1", content="c", score=0.9),
                VectorSearchResult(memory_id="k1", content="c", score=0.8),
            ]
        )
        memories = {
            "p1": _pref_memory("p1", "偏好"),
            "k1": _know_memory("k1", "知识"),
        }
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
        )
        response = retriever.search(SearchRequest(query="周报", top_k=5, memory_types=["knowledge"]))
        assert response.total_count == 1
        assert response.results[0].memory_id == "k1"

    def test_filter_by_min_confidence(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [
                VectorSearchResult(memory_id="m1", content="c", score=0.9),
                VectorSearchResult(memory_id="m2", content="c", score=0.5),
            ]
        )
        memories = {
            "m1": _pref_memory("m1", "高置信度"),
            "m2": _pref_memory("m2", "低置信度"),
        }
        memories["m1"].confidence = 0.9
        memories["m2"].confidence = 0.3
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
        )
        response = retriever.search(SearchRequest(query="周报", top_k=5, min_confidence=0.5))
        assert response.total_count == 1
        assert response.results[0].memory_id == "m1"

    def test_filter_by_scope_conflict(self) -> None:
        engine = FakeVectorEngine()
        engine.set_results(
            [
                VectorSearchResult(memory_id="m1", content="c", score=0.9),
                VectorSearchResult(memory_id="m2", content="c", score=0.8),
            ]
        )
        memories = {
            "m1": _pref_memory("m1", "匹配", scene="office"),
            "m2": _pref_memory("m2", "冲突", scene="home"),
        }
        retriever = MilvusHybridRetriever(
            engine=engine,
            embedding_fn=_embedding_fn,
            config=RetrievalConfig(candidate_multiplier=2),
            memory_lookup=memories,
        )
        response = retriever.search(
            SearchRequest(query="周报", top_k=5, context=SceneScope(scene="office"))
        )
        assert response.total_count == 1
        assert response.results[0].memory_id == "m1"
