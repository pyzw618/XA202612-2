"""
Milvus 混合检索器

面向向量引擎（BaseVectorEngine）的检索器：稠密向量由 embedding_fn 生成，
稀疏向量由 sparse.build_sparse_vector 生成（与 C 侧规则逐位一致），
融合检索（RRF）在引擎内部完成。返回结构与 HybridRetriever 一致，
便于 API 层无差别切换。
"""

import time
from collections.abc import Callable

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from memoryhub.config import RetrievalConfig
from memoryhub.storage.vector_engine import BaseVectorEngine, build_sparse_vector


def _memory_text(memory: PreferenceMemory | KnowledgeMemory) -> str:
    """用于建索引的记忆文本：知识记忆拼上名称，偏好记忆用正文"""
    if memory.memory_type == "knowledge":
        return f"{memory.name} {memory.content}".strip()
    return memory.text


def _memory_metadata(memory: PreferenceMemory | KnowledgeMemory) -> dict:
    """检索结果随行的元数据（与 app.py 中 _VectorStoreSearchAdapter 的补全逻辑一致）"""
    return {
        "memory_type": memory.memory_type,
        "content": _memory_text(memory),
        "confidence": memory.confidence,
        "scope": memory.scope.model_dump(),
    }


class MilvusHybridRetriever:
    """
    基于向量引擎的混合检索器

    使用方式:
        retriever = MilvusHybridRetriever(engine, embedding_fn, memory_lookup=lookup)
        response = retriever.search(request)

    数据流:
        SearchRequest → embedding_fn(query) 生成稠密向量
                      → build_sparse_vector(query) 生成稀疏向量
                      → engine.hybrid_search（引擎内部 RRF 融合）
                      → memory_lookup 补齐 metadata → SearchResponse
    """

    def __init__(
        self,
        engine: BaseVectorEngine,
        embedding_fn: Callable[[str], list[float]],
        config: RetrievalConfig | None = None,
        memory_lookup: dict | None = None,
    ):
        """
        参数:
            engine: 向量引擎实例（milvus / milvus_mock / faiss 均可）
            embedding_fn: query 文本 → 稠密向量的函数
            config: 检索配置，缺省用 RetrievalConfig 默认值
            memory_lookup: memory_id → PreferenceMemory/KnowledgeMemory 的映射，
                用于补齐 SearchResult 的 metadata 和 SearchResponse 的
                preferences/knowledge（与 HybridRetriever 行为一致）
        """
        self.engine = engine
        self.embedding_fn = embedding_fn
        self.config = config or RetrievalConfig()
        self.memory_lookup = memory_lookup or {}

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        执行混合检索

        参数:
            request: 检索请求

        返回:
            SearchResponse（含偏好和知识列表），结构同 HybridRetriever.search
        """
        start = time.perf_counter()

        if not request.query:
            return self._format_response([], 0.0)

        # 多取候选再按 context 过滤，避免过滤后不足 top_k
        fetch_k = max(request.top_k * 2, 10)

        dense_vector = self.embedding_fn(request.query)
        sparse_terms = build_sparse_vector(request.query)
        hits = self.engine.hybrid_search(dense_vector, sparse_terms, fetch_k)

        results = [self._to_search_result(hit) for hit in hits]
        filtered = self._filter_by_context(results, request)
        top_results = filtered[: request.top_k]

        latency_ms = (time.perf_counter() - start) * 1000
        return self._format_response(top_results, latency_ms)

    # ---- 内部 ----

    def _to_search_result(self, hit) -> SearchResult:
        """VectorSearchResult → adapter 的 SearchResult（source 固定为 hybrid）"""
        memory = self.memory_lookup.get(hit.memory_id)
        metadata = _memory_metadata(memory) if memory is not None else dict(hit.metadata)
        return SearchResult(
            memory_id=hit.memory_id,
            memory_type=metadata.get("memory_type", ""),
            content=metadata.get("content", hit.content),
            score=float(hit.score),
            source="hybrid",
            metadata=metadata,
        )

    def _filter_by_context(
        self, results: list[SearchResult], request: SearchRequest
    ) -> list[SearchResult]:
        """按记忆类型、置信度和场景 scope 过滤结果（与 HybridRetriever 一致）"""
        filtered = []
        for result in results:
            if request.memory_types and result.memory_type:
                if result.memory_type not in request.memory_types:
                    continue
            confidence = result.metadata.get("confidence")
            if confidence is not None and confidence < request.min_confidence:
                continue
            if self._scope_conflict(result, request):
                continue
            filtered.append(result)
        return filtered

    @staticmethod
    def _scope_conflict(result: SearchResult, request: SearchRequest) -> bool:
        """scope 与请求 context 存在明确冲突时返回 True（无信息不算冲突）"""
        scope = result.metadata.get("scope")
        if not isinstance(scope, dict):
            return False
        for field in ("scene", "task_type", "app"):
            expected = getattr(request.context, field, "")
            actual = scope.get(field, "")
            if expected and actual and actual != expected:
                return True
        return False

    def _format_response(
        self, results: list[SearchResult], latency_ms: float
    ) -> SearchResponse:
        """将检索结果格式化为 SearchResponse（与 HybridRetriever 一致）"""
        preferences: list[PreferenceMemory] = []
        knowledge: list[KnowledgeMemory] = []
        for result in results:
            memory = self.memory_lookup.get(result.memory_id)
            if isinstance(memory, PreferenceMemory):
                preferences.append(memory)
            elif isinstance(memory, KnowledgeMemory):
                knowledge.append(memory)
        return SearchResponse(
            results=results,
            preferences=preferences,
            knowledge=knowledge,
            latency_ms=round(latency_ms, 2),
            total_count=len(results),
        )
