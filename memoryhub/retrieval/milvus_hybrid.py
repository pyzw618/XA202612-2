"""
Milvus 混合检索器

面向向量引擎（BaseVectorEngine）的检索器：稠密向量由 embedding_fn 生成，
稀疏向量由 sparse.build_sparse_vector 生成（与 C 侧规则逐位一致），
融合检索（RRF）在引擎内部完成。返回结构与 HybridRetriever 一致，
便于 API 层无差别切换。
"""

import logging
import math
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from memoryhub.adapter.schemas import (
    FactMemory,
    KnowledgeMemory,
    PreferenceMemory,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from memoryhub.config import RetrievalConfig, RuntimeConfig
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.keyword_search import _tokenize
from memoryhub.storage.vector_engine import BaseVectorEngine, build_sparse_vector

logger = logging.getLogger(__name__)

# 生产模式下普通重排最多只能处理前 20 个候选
_RERANK_CANDIDATE_LIMIT = 20

# RRF 融合常数：与 fusion.py / C 侧保持一致，避免两处口径不同
_RRF_K = 60

# 稳定的检索超时/不可用错误码，供 API 层映射为 HTTP 503/504
_RETRIEVAL_TIMEOUT_CODES = {
    "embedding.timeout",
    "milvus.timeout",
}
_RETRIEVAL_UNAVAILABLE_CODES = {
    "embedding.unavailable",
    "milvus.call_failed",
    "milvus.schema_dimension_mismatch",
    "embedding.dimension_mismatch",
    "embedding.backend_error",
    "embedding.sdk_error",
    "embedding.call_failed",
    "embedding.invalid_text",
}


def _is_timeout_error(exc: Exception) -> bool:
    """判断异常是否为已知的超时错误。"""
    code = getattr(exc, "code", "")
    if isinstance(code, str):
        if code in _RETRIEVAL_TIMEOUT_CODES:
            return True
        if code.startswith("embedding.timeout") or code.startswith("milvus.timeout"):
            return True
    return False


def _is_unavailable_error(exc: Exception) -> bool:
    """判断异常是否为已知的后端不可用错误。"""
    code = getattr(exc, "code", "")
    if isinstance(code, str):
        if code in _RETRIEVAL_UNAVAILABLE_CODES:
            return True
        if code.startswith("embedding.") or code.startswith("milvus."):
            return True
    return False


def _memory_text(memory) -> str:
    """用于建索引的记忆文本：知识记忆拼上名称，偏好记忆用正文"""
    if memory.memory_type == "knowledge":
        from memoryhub.core.memory_write import MemoryWriteService

        return MemoryWriteService.index_text(memory)
    if memory.memory_type == "fact":
        return memory.content
    return memory.text


def _memory_metadata(memory) -> dict:
    """检索结果随行的元数据（与 app.py 中 _VectorStoreSearchAdapter 的补全逻辑一致）"""
    knowledge_fields = {}
    if memory.memory_type == "knowledge":
        knowledge_type = getattr(memory, "knowledge_type", "workflow")
        knowledge_fields = {
            "knowledge_type": getattr(knowledge_type, "value", knowledge_type),
            "name": getattr(memory, "name", ""),
            "knowledge_content": getattr(memory, "content", ""),
            "steps": list(getattr(memory, "steps", []) or []),
            "tools": list(getattr(memory, "tools", []) or []),
            "template_body": getattr(memory, "template_body", ""),
            "subject": getattr(memory, "subject", ""),
            "predicate": getattr(memory, "predicate", ""),
            "object_value": getattr(memory, "object_value", ""),
        }
    return {
        "memory_type": memory.memory_type,
        "user_id": memory.user_id,
        "content": _memory_text(memory),
        "confidence": memory.confidence,
        "status": (memory.status.value if hasattr(memory.status, "value") else str(memory.status)),
        "scope": (
            {"scope": memory.scope, "project_id": memory.project_id or ""}
            if memory.memory_type == "fact"
            else memory.scope.model_dump()
        ),
        **(
            {
                "subject_id": memory.subject_id,
                "predicate_id": memory.predicate_id,
                "object_id": memory.object_id,
            }
            if memory.memory_type == "fact"
            else {}
        ),
        **knowledge_fields,
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
        runtime_config: RuntimeConfig | None = None,
        memory_lookup: dict | None = None,
        cache: SearchCache | None = None,
        index_version: str = "",
        keyword_search: Any | None = None,
        reranker: Any | None = None,
        query_vector_cache_size: int = 1000,
        fallback_retriever: Callable[[SearchRequest], SearchResponse] | None = None,
        metrics_collector: Callable[[dict[str, float]], None] | None = None,
    ):
        """
        参数:
            engine: 向量引擎实例（生产环境要求 milvus）
            embedding_fn: query 文本 → 稠密向量的函数
            config: 检索配置，缺省用 RetrievalConfig 默认值
            runtime_config: 运行时配置，控制生产/开发模式与降级策略
            memory_lookup: memory_id → PreferenceMemory/KnowledgeMemory 的映射，
                用于补齐 SearchResult 的 metadata 和 SearchResponse 的
                preferences/knowledge（与 HybridRetriever 行为一致）
            cache: SearchCache 实例；为 None 时禁用结果缓存
            index_version: 索引版本号，会作为结果缓存键的一部分
            reranker: 可选的重排器；生产模式下默认关闭，开启时仅对前 20 候选生效
            query_vector_cache_size: 查询向量 LRU 缓存大小
            fallback_retriever: 可选的降级检索器；仅在 development/test 模式且
                allow_fallback=True 时，于 Embedding/Milvus 超时后调用
            metrics_collector: 可选的指标采集回调，每次检索完成后收到分段耗时字典
        """
        self.engine = engine
        self.embedding_fn = embedding_fn
        self.config = config or RetrievalConfig()
        self.runtime_config = runtime_config or RuntimeConfig()
        self.memory_lookup = memory_lookup if memory_lookup is not None else {}
        self.cache = cache
        self.index_version = index_version
        # 可选的关键词通道。给定时改用 Python 侧加权 RRF 融合稠密与词面两路，
        # 绕开引擎内部写死的等权融合（见 _weighted_fuse）。
        self.keyword_search = keyword_search
        self.reranker = reranker
        # 查询向量 LRU 缓存：query text -> dense vector
        self._query_vector_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._query_vector_cache_size = query_vector_cache_size
        self.fallback_retriever = fallback_retriever
        self.metrics_collector = metrics_collector

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        执行混合检索

        参数:
            request: 检索请求

        返回:
            SearchResponse（含偏好和知识列表），结构同 HybridRetriever.search

        异常:
            KylinEmbeddingError/MilvusEngineError: 生产模式下 Embedding/Milvus 超时或
                不可用会直接抛出稳定错误码，不会静默降级到 FAISS。
        """
        total_start = time.perf_counter()
        timings: dict[str, float] = {}

        # 1. 请求校验、规范化查询并构造缓存键
        t0 = time.perf_counter()
        normalized_query = self._normalize_query(request.query)
        search_request = request.model_copy(update={"query": normalized_query})
        timings["validate_ms"] = (time.perf_counter() - t0) * 1000

        if not normalized_query:
            latency_ms = (time.perf_counter() - total_start) * 1000
            response = self._format_response([], latency_ms)
            self._emit_metrics(timings, response.latency_ms)
            return response

        # 2. 查询结果缓存命中时直接返回
        t0 = time.perf_counter()
        if self.cache is not None:
            cached = self.cache.get(search_request, version=self.index_version)
            if cached is not None:
                timings["result_cache_ms"] = (time.perf_counter() - t0) * 1000
                self._emit_metrics(timings, cached.latency_ms, cache_hit=True)
                return cached
        timings["result_cache_ms"] = (time.perf_counter() - t0) * 1000

        # 3. 查询向量缓存命中时复用 768 维向量，否则调用 Embedding SDK
        t0 = time.perf_counter()
        try:
            dense_vector = self._get_cached_vector(normalized_query)
            vector_cache_hit = dense_vector is not None
            if not vector_cache_hit:
                dense_vector = self.embedding_fn(normalized_query)
                self._set_cached_vector(normalized_query, dense_vector)
            timings["embedding_ms"] = (time.perf_counter() - t0) * 1000
        except Exception as exc:
            timings["embedding_ms"] = (time.perf_counter() - t0) * 1000
            return self._handle_retrieval_error(
                exc,
                "embedding",
                self.config.target_p95_ms if self.config else 0,
                search_request,
                timings,
                total_start,
                vector_cache_hit=False,
            )

        # 4. 用与 C API 一致的 FNV-1a 规则构造稀疏向量
        t0 = time.perf_counter()
        sparse_terms = build_sparse_vector(normalized_query)
        timings["sparse_ms"] = (time.perf_counter() - t0) * 1000

        # 5. 调用 Milvus HybridSearch，召回 top_k * candidate_multiplier 候选
        t0 = time.perf_counter()
        try:
            # The installed vector engines only understand exact scalar filters.
            # Fetch enough candidates, then apply every request predicate against
            # authoritative metadata below, before slicing Top-K.
            configured_fetch_k = search_request.top_k * self.config.candidate_multiplier
            context = search_request.context
            needs_post_filter_overfetch = bool(
                search_request.memory_types
                or search_request.min_confidence > 0
                or search_request.scenes
                or search_request.task_types
                or search_request.project_id
                or context.scene
                or context.task_type
                or context.app
            )
            fetch_k = (
                max(configured_fetch_k, 100)
                if needs_post_filter_overfetch
                else configured_fetch_k
            )
            assert dense_vector is not None
            engine_filters: dict[str, Any] = {
                "user_id": search_request.user_id,
                "status": "active",
            }
            if self.keyword_search is not None:
                hits = self._weighted_fuse(
                    dense_vector, normalized_query, fetch_k, engine_filters
                )
            else:
                hits = self.engine.hybrid_search(
                    dense_vector, sparse_terms, fetch_k, filters=engine_filters
                )
            timings["hybrid_search_ms"] = (time.perf_counter() - t0) * 1000
        except Exception as exc:
            timings["hybrid_search_ms"] = (time.perf_counter() - t0) * 1000
            return self._handle_retrieval_error(
                exc,
                "milvus",
                self.config.target_p95_ms if self.config else 0,
                search_request,
                timings,
                total_start,
                vector_cache_hit=vector_cache_hit,
            )

        # 6. 元数据过滤（含回表读取记忆元数据）
        t0 = time.perf_counter()
        results = [self._to_search_result(hit, timings) for hit in hits]
        filtered = self._filter_by_context(results, search_request)

        # 7. 普通重排默认关闭；开启时仅对前 20 个候选执行无模型规则重排
        if self.reranker is not None and self.config.rerank_enabled:
            filtered = self.reranker.rerank(filtered[:_RERANK_CANDIDATE_LIMIT], search_request)

        top_results = filtered[: search_request.top_k]
        timings["filter_ms"] = (time.perf_counter() - t0) * 1000

        # 8. SQLite 回表补齐详情并序列化为响应
        t0 = time.perf_counter()
        latency_ms = (time.perf_counter() - total_start) * 1000
        response = self._format_response(top_results, latency_ms, timings)
        timings["serialize_ms"] = (time.perf_counter() - t0) * 1000

        # 9. 写入结果缓存（缓存键包含索引版本号）
        if self.cache is not None:
            self.cache.set(search_request, response, version=self.index_version)

        self._emit_metrics(
            timings,
            response.latency_ms,
            cache_hit=False,
            vector_cache_hit=vector_cache_hit,
        )
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

    def _emit_metrics(
        self,
        timings: dict[str, float],
        total_ms: float,
        cache_hit: bool = False,
        vector_cache_hit: bool = False,
    ) -> None:
        """汇总并输出分段耗时指标，供基准脚本与可观测性系统采集。"""
        metrics: dict[str, float] = {
            **{k: round(v, 2) for k, v in timings.items()},
            "total_ms": round(total_ms, 2),
            "budget_p95_ms": float(self.config.target_p95_ms),
            "budget_p99_ms": float(self.config.target_p99_ms),
            "cache_hit": 1.0 if cache_hit else 0.0,
            "vector_cache_hit": 1.0 if vector_cache_hit else 0.0,
        }
        # 与延迟预算对比：超过预算时记录警告，便于告警与后续调优
        if total_ms > self.config.target_p99_ms:
            metrics["budget_violation"] = 99.0
            logger.warning(
                "milvus_hybrid_search_timings: %s (exceeds P99 budget %dms)",
                metrics,
                self.config.target_p99_ms,
            )
        elif total_ms > self.config.target_p95_ms:
            metrics["budget_violation"] = 95.0
            logger.warning(
                "milvus_hybrid_search_timings: %s (exceeds P95 budget %dms)",
                metrics,
                self.config.target_p95_ms,
            )
        else:
            metrics["budget_violation"] = 0.0
            logger.info("milvus_hybrid_search_timings: %s", metrics)

        if self.metrics_collector is not None:
            try:
                self.metrics_collector(metrics)
            except Exception:
                logger.exception("metrics_collector failed")

    def _handle_retrieval_error(
        self,
        exc: Exception,
        stage: str,
        budget_ms: int,
        request: SearchRequest,
        timings: dict[str, float],
        total_start: float,
        vector_cache_hit: bool = False,
    ) -> SearchResponse:
        """
        统一处理 Embedding/Milvus 超时或不可用异常。

        - 生产模式：记录结构化告警后直接抛出，禁止静默降级。
        - development/test 模式且 allow_fallback=True：在记录告警后可调用
          fallback_retriever 返回降级结果；无 fallback 时同样抛出。
        """
        elapsed_ms = (time.perf_counter() - total_start) * 1000
        is_timeout = _is_timeout_error(exc)
        is_unavailable = _is_unavailable_error(exc)
        code = getattr(exc, "code", "retrieval.error")

        alert = {
            "event": "retrieval_alert",
            "stage": stage,
            "code": code,
            "is_timeout": is_timeout,
            "is_unavailable": is_unavailable,
            "elapsed_ms": round(elapsed_ms, 2),
            "budget_ms": budget_ms,
        }
        if is_timeout:
            logger.warning("retrieval_timeout_alert: %s", alert)
        else:
            logger.warning("retrieval_unavailable_alert: %s", alert)

        # 生产模式禁止静默降级
        if self.runtime_config.is_production:
            raise

        # development/test 模式：allow_fallback 为 true 且提供 fallback 时启用降级
        if self.runtime_config.allow_fallback and self.fallback_retriever is not None:
            logger.warning(
                "retrieval_fallback_triggered: stage=%s code=%s mode=%s",
                stage,
                code,
                self.runtime_config.mode,
            )
            try:
                response = self.fallback_retriever(request)
                self._emit_metrics(
                    timings,
                    response.latency_ms,
                    cache_hit=False,
                    vector_cache_hit=vector_cache_hit,
                )
                return response
            except Exception as fallback_exc:
                logger.exception("retrieval_fallback_failed: stage=%s", stage)
                # 降级失败时，把原始异常带出来，避免吞掉错误
                raise fallback_exc from exc

        # 非生产模式也不允许降级时，同样抛出原始异常
        raise

    def _weighted_fuse(
        self,
        dense_vector: list[float],
        query: str,
        fetch_k: int,
        engine_filters: dict[str, Any],
    ) -> list[SearchResult]:
        """在 Python 侧按权重融合稠密与词面两路，取代引擎内部的等权 RRF。

        **为什么需要这一层**：引擎的 ``hybrid_search`` 在 C 侧做 RRF，两路权重
        写死为等权，且 C API 不接受权重参数。当稠密通道区分度低时（语料偏模板化
        是常见成因），它接近随机的排序会被等权带进融合结果，把词面通道精确的
        顺序冲掉——实测召回因此从 1.00 掉到 0.65。这里让两路权重可配
        （``retrieval.vector_weight`` / ``retrieval.keyword_weight``）。

        两路各自独立取 ``fetch_k`` 个候选，再按 RRF（k=60）融合；返回的
        ``SearchResult.score`` 即融合分，后续过滤与截断逻辑不变。
        """
        dense_hits = self.engine.search(dense_vector, fetch_k, filters=engine_filters)
        keyword_hits = self.keyword_search.search(query, fetch_k)

        dense_weight = float(getattr(self.config, "vector_weight", 0.5) or 0.0)
        keyword_weight = float(getattr(self.config, "keyword_weight", 0.5) or 0.0)
        coverage_boost = float(getattr(self.config, "coverage_boost", 0.0) or 0.0)

        fused: dict[str, float] = {}
        payload: dict[str, SearchResult] = {}
        for weight, hits in ((dense_weight, dense_hits), (keyword_weight, keyword_hits)):
            if weight <= 0:
                continue
            for rank, hit in enumerate(hits, start=1):
                memory_id = getattr(hit, "memory_id", "")
                if not memory_id:
                    continue
                fused[memory_id] = fused.get(memory_id, 0.0) + weight / (_RRF_K + rank)
                payload.setdefault(
                    memory_id,
                    hit if isinstance(hit, SearchResult) else SearchResult(
                        memory_id=memory_id,
                        content=getattr(hit, "content", ""),
                        score=0.0,
                        metadata=dict(getattr(hit, "metadata", {}) or {}),
                    ),
                )

        if coverage_boost > 0:
            query_tokens = set(_tokenize(query))
            if query_tokens and fused:
                doc_tokens = {
                    memory_id: set(_tokenize(str(payload[memory_id].metadata.get("content", ""))))
                    for memory_id in fused
                }
                # **必须按词罕见度加权**。不加权时"历史/处理/案例"这类通用词会把
                # 结构相同、主题不同的记忆抬到同分（实测连按名称精确检索的 canary
                # 都从 100% 掉到 70%）。这里用候选集内的文档频率近似 IDF：
                # 只在少数候选里出现的词才具备区分力。
                total = len(doc_tokens) or 1
                doc_freq: dict[str, int] = {}
                for tokens in doc_tokens.values():
                    for token in query_tokens & tokens:
                        doc_freq[token] = doc_freq.get(token, 0) + 1
                idf = {
                    token: math.log((total + 1) / (doc_freq.get(token, 0) + 1)) + 1.0
                    for token in query_tokens
                }
                denominator = sum(idf.values()) or 1.0
                for memory_id, tokens in doc_tokens.items():
                    numerator = sum(idf[t] for t in query_tokens & tokens)
                    # 加性项，量级显著高于 RRF（RRF 各项约 0.01 量级）。
                    # 查询词覆盖更全的候选因此优先；当查询与候选**没有**词面
                    # 交集时 coverage 全为 0，排序自动退回 RRF（稠密为主），
                    # 语义检索能力得以保留。
                    #
                    # 用 coverage（|q∩d|/|q|）而非 Jaccard：后者按并集归一化会
                    # 惩罚长文档，实测接线后召回反而下降。
                    fused[memory_id] += coverage_boost * (numerator / denominator)

        ordered = sorted(fused.items(), key=lambda item: item[1], reverse=True)
        results: list[SearchResult] = []
        for memory_id, score in ordered:
            base = payload[memory_id]
            results.append(
                base.model_copy(update={"score": float(score), "source": "hybrid"})
            )
        return results

    def _to_search_result(self, hit, timings: dict[str, float] | None = None) -> SearchResult:
        """VectorSearchResult → adapter 的 SearchResult（source 固定为 hybrid）"""
        t0 = time.perf_counter()
        memory = self.memory_lookup.get(hit.memory_id)
        if timings is not None:
            timings["sqlite_lookup_ms"] = (
                timings.get("sqlite_lookup_ms", 0.0) + (time.perf_counter() - t0) * 1000
            )
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
            memory = self.memory_lookup.get(result.memory_id)
            result_user_id = getattr(memory, "user_id", "") or result.metadata.get("user_id")
            if not result_user_id or result_user_id != request.user_id:
                continue
            status = getattr(memory, "status", "") or result.metadata.get("status")
            status = status.value if hasattr(status, "value") else str(status)
            if status and status != "active":
                continue
            if request.memory_types and result.memory_type:
                if result.memory_type not in request.memory_types:
                    continue
            confidence = result.metadata.get("confidence")
            if confidence is not None and confidence < request.min_confidence:
                continue
            scope = result.metadata.get("scope")
            if isinstance(scope, dict):
                if request.scenes and scope.get("scene") not in request.scenes:
                    continue
                if request.task_types and scope.get("task_type") not in request.task_types:
                    continue
            elif request.scenes or request.task_types:
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
        self,
        results: list[SearchResult],
        latency_ms: float,
        timings: dict[str, float] | None = None,
    ) -> SearchResponse:
        """将检索结果格式化为 SearchResponse（与 HybridRetriever 一致）"""
        preferences: list[PreferenceMemory] = []
        knowledge: list[KnowledgeMemory] = []
        facts: list[FactMemory] = []
        for result in results:
            t0 = time.perf_counter()
            # 分层级联标注（REFACTOR_PLAN_V2 §4.4.3 / I-4）：长期记忆默认 memory_level=long
            result.memory_level = result.memory_level or "long"
            memory = self.memory_lookup.get(result.memory_id)
            if timings is not None:
                timings["sqlite_lookup_ms"] = (
                    timings.get("sqlite_lookup_ms", 0.0) + (time.perf_counter() - t0) * 1000
                )
            if isinstance(memory, PreferenceMemory):
                preferences.append(memory)
            elif isinstance(memory, KnowledgeMemory):
                knowledge.append(memory)
            elif getattr(memory, "memory_type", "") == "fact":
                facts.append(FactMemory.model_validate(memory))
        return SearchResponse(
            results=results,
            preferences=preferences,
            knowledge=knowledge,
            facts=facts,
            latency_ms=round(latency_ms, 2),
            total_count=len(results),
        )
