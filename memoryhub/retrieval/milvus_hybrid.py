"""
Milvus 混合检索器

面向向量引擎（BaseVectorEngine）的检索器：稠密向量由 embedding_fn 生成，
稀疏向量由 sparse.build_sparse_vector 生成（与 C 侧规则逐位一致），
融合检索（RRF）在引擎内部完成。返回结构与 HybridRetriever 一致，
便于 API 层无差别切换。
"""

import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from memoryhub.config import RetrievalConfig
from memoryhub.retrieval.cache import SearchCache
from memoryhub.storage.vector_engine import BaseVectorEngine, build_sparse_vector

logger = logging.getLogger(__name__)

# 生产模式下普通重排最多只能处理前 20 个候选
_RERANK_CANDIDATE_LIMIT = 20


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
    生产环境唯一的混合检索器

    使用方式:
        retriever = MilvusHybridRetriever(engine, embedding_fn, memory_lookup=lookup)
        response = retriever.search(request)

    数据流:
        SearchRequest → 规范化查询并截断
                      → 查询结果缓存命中时直接返回
                      → 查询向量缓存命中时复用稠密向量
                      → embedding_fn(query) 生成稠密向量
                      → build_sparse_vector(query) 生成稀疏向量
                      → engine.hybrid_search（引擎内部 RRF 融合）
                      → 元数据过滤、SQLite 回表补齐详情
                      → 返回 Top-K 并写入缓存
    """

    def __init__(
        self,
        engine: BaseVectorEngine,
        embedding_fn: Callable[[str], list[float]],
        config: RetrievalConfig | None = None,
        memory_lookup: dict | None = None,
        cache: SearchCache | None = None,
        index_version: str = "",
        reranker: object | None = None,
        query_vector_cache_size: int = 1000,
    ):
        """
        参数:
            engine: 向量引擎实例（生产环境要求 milvus）
            embedding_fn: query 文本 → 稠密向量的函数
            config: 检索配置，缺省用 RetrievalConfig 默认值
            memory_lookup: memory_id → PreferenceMemory/KnowledgeMemory 的映射，
                用于补齐 SearchResult 的 metadata 和 SearchResponse 的
                preferences/knowledge（与 HybridRetriever 行为一致）
            cache: SearchCache 实例；为 None 时禁用结果缓存
            index_version: 索引版本号，会作为结果缓存键的一部分
            reranker: 可选的重排器；生产模式下默认关闭，开启时仅对前 20 候选生效
            query_vector_cache_size: 查询向量 LRU 缓存大小
        """
        self.engine = engine
        self.embedding_fn = embedding_fn
        self.config = config or RetrievalConfig()
        self.memory_lookup = memory_lookup or {}
        self.cache = cache
        self.index_version = index_version
        self.reranker = reranker
        # 查询向量 LRU 缓存：query text -> dense vector
        self._query_vector_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._query_vector_cache_size = query_vector_cache_size

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        执行混合检索

        参数:
            request: 检索请求

        返回:
            SearchResponse（含偏好和知识列表），结构同 HybridRetriever.search
        """
        total_start = time.perf_counter()
        timings: dict[str, float] = {}

        # 1. 规范化查询并限制长度
        normalized_query = self._normalize_query(request.query)
        if not normalized_query:
            latency_ms = (time.perf_counter() - total_start) * 1000
            return self._format_response([], latency_ms)

        # 使用规范化后的请求进行缓存与检索，使等价查询命中同一缓存
        search_request = request.model_copy(update={"query": normalized_query})

        # 2. 查询结果缓存命中时直接返回
        if self.cache is not None:
            cached = self.cache.get(search_request, version=self.index_version)
            if cached is not None:
                return cached

        # 3. 查询向量缓存命中时复用 768 维向量
        t0 = time.perf_counter()
        dense_vector = self._get_cached_vector(normalized_query)
        if dense_vector is None:
            dense_vector = self.embedding_fn(normalized_query)
            self._set_cached_vector(normalized_query, dense_vector)
        timings["embedding_ms"] = (time.perf_counter() - t0) * 1000

        # 4. 用与 C API 一致的 FNV-1a 规则构造稀疏向量
        t0 = time.perf_counter()
        sparse_terms = build_sparse_vector(normalized_query)
        timings["sparse_ms"] = (time.perf_counter() - t0) * 1000

        # 5. 调用 Milvus HybridSearch，召回 top_k * candidate_multiplier 候选
        t0 = time.perf_counter()
        fetch_k = max(search_request.top_k * self.config.candidate_multiplier, 1)
        hits = self.engine.hybrid_search(dense_vector, sparse_terms, fetch_k)
        timings["hybrid_search_ms"] = (time.perf_counter() - t0) * 1000

        # 6. 回表 SQLite 补齐详情，并按 memory_type/scope/confidence 过滤
        t0 = time.perf_counter()
        results = [self._to_search_result(hit) for hit in hits]
        filtered = self._filter_by_context(results, search_request)

        # 7. 普通重排默认关闭；开启时仅对前 20 个候选执行无模型规则重排
        if self.reranker is not None and self.config.rerank_enabled:
            filtered = self.reranker.rerank(filtered[:_RERANK_CANDIDATE_LIMIT], search_request)

        top_results = filtered[: search_request.top_k]
        timings["filter_ms"] = (time.perf_counter() - t0) * 1000

        latency_ms = (time.perf_counter() - total_start) * 1000
        response = self._format_response(top_results, latency_ms)

        # 8. 写入结果缓存（缓存键包含索引版本号）
        if self.cache is not None:
            self.cache.set(search_request, response, version=self.index_version)

        timings["total_ms"] = latency_ms
        self._log_timings(timings)

        return response

    # ---- 内部 ----

    def _normalize_query(self, query: str) -> str:
        """规范化查询：去除首尾空白、折叠连续空白、截断至 max_query_chars。"""
        query = (query or "").strip()
        if not query:
            return ""
        # 折叠连续空白为单个空格
        query = re.sub(r"\s+", " ", query)
        max_chars = self.config.max_query_chars
        if max_chars > 0 and len(query) > max_chars:
            query = query[:max_chars]
        return query

    def _get_cached_vector(self, query: str) -> list[float] | None:
        """从 LRU 查询向量缓存中读取稠密向量。"""
        vector = self._query_vector_cache.get(query)
        if vector is not None:
            self._query_vector_cache.move_to_end(query)
        return vector

    def _set_cached_vector(self, query: str, vector: list[float]) -> None:
        """写入 LRU 查询向量缓存。"""
        self._query_vector_cache[query] = vector
        self._query_vector_cache.move_to_end(query)
        while len(self._query_vector_cache) > self._query_vector_cache_size:
            self._query_vector_cache.popitem(last=False)

    def _log_timings(self, timings: dict[str, float]) -> None:
        """输出分段耗时指标，供基准脚本与可观测性系统采集。"""
        # 保留两位小数，避免日志过度膨胀
        formatted = {k: round(v, 2) for k, v in timings.items()}
        logger.info("milvus_hybrid_search_timings: %s", formatted)

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
