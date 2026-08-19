"""
混合检索入口（development/test 降级路径）。

组合 FAISS 向量检索、BM25 关键词检索、元数据过滤，返回融合结果。
生产环境请使用 MilvusHybridRetriever，本类仅在 development/test 模式或
显式故障诊断场景下作为 fallback 保留。
"""

import time
from collections.abc import Callable

from memoryhub.adapter.schemas import (
    FactMemory,
    KnowledgeMemory,
    PreferenceMemory,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from memoryhub.config import RetrievalConfig


class HybridRetriever:
    """
    混合检索器（development/test 的 FAISS + BM25 fallback）。

    使用方式:
        retriever = HybridRetriever(vector_search, keyword_search, reranker, cache)
        response = retriever.search(request)

    注意:
        本检索器仅用于 development/test 或显式诊断场景；生产环境请使用
        MilvusHybridRetriever。
    """

    def __init__(
        self,
        vector_search=None,
        keyword_search=None,
        reranker=None,
        cache=None,
        config: RetrievalConfig | None = None,
        embedding_fn: Callable[[str], list[float]] | None = None,
        memory_lookup: dict | None = None,
    ):
        """
        参数:
            vector_search: VectorSearcher 实例
            keyword_search: KeywordSearcher 实例
            reranker: Reranker 实例
            cache: SearchCache 实例
            config: 检索配置（融合权重等），缺省用 RetrievalConfig 默认值
            embedding_fn: query 文本 → 向量的函数；缺省时跳过向量检索
            memory_lookup: memory_id → PreferenceMemory/KnowledgeMemory 的映射，
                用于填充 SearchResponse 的 preferences/knowledge（storage 层接入前的简化方案）
        """
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.reranker = reranker
        self.cache = cache
        self.config = config or RetrievalConfig()
        self.embedding_fn = embedding_fn
        self.memory_lookup = memory_lookup if memory_lookup is not None else {}

    def search(self, request: SearchRequest) -> SearchResponse:
        """
        执行混合检索

        数据流:
            SearchRequest → search
              → 检查缓存
              → 向量检索（FAISS）
              → 关键词检索（BM25）
              → 元数据过滤（scope/status/confidence）
              → 分数融合
              → 重排序
              → 缓存结果
              → 返回 SearchResponse

        参数:
            request: 检索请求

        返回:
            SearchResponse（含偏好和知识列表）

        性能目标:
            总延迟 ≤ 500ms
        """
        start = time.perf_counter()

        if self.cache is not None:
            cached = self.cache.get(request)
            if cached is not None:
                return cached

        fetch_k = max(request.top_k * 2, 10)

        # 向量检索：需要 embedding_fn 把 query 转成向量；缺省时跳过
        vector_results: list[SearchResult] = []
        if self.vector_search is not None and self.embedding_fn is not None and request.query:
            query_vector = self.embedding_fn(request.query)
            vector_results = self.vector_search.search(query_vector, top_k=fetch_k)

        # 关键词检索
        keyword_results: list[SearchResult] = []
        if self.keyword_search is not None and request.query:
            keyword_results = self.keyword_search.search(request.query, top_k=fetch_k)

        # 元数据检索（第一阶段简化实现）：对候选结果按 scope 匹配度给固定分数
        metadata_results = self._score_by_metadata(vector_results + keyword_results, request)

        merged = self._merge_results(vector_results, keyword_results, metadata_results)
        filtered = self._filter_by_context(merged, request)

        if self.reranker is not None and self.config.rerank_enabled:
            filtered = self.reranker.rerank(filtered, request)
        else:
            filtered.sort(key=lambda r: r.score, reverse=True)

        top_results = filtered[: request.top_k]

        latency_ms = (time.perf_counter() - start) * 1000
        response = self._format_response(top_results, latency_ms)

        if self.cache is not None:
            self.cache.set(request, response)

        return response

    def _merge_results(
        self,
        vector_results: list[SearchResult],
        keyword_results: list[SearchResult],
        metadata_results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        融合多路检索结果

        融合公式:
            final_score = vector_weight × vector_score
                        + keyword_weight × keyword_score
                        + metadata_weight × metadata_score

        对同一 memory_id 的结果合并分数。向量分数映射到 [0,1]，
        关键词分数做 min-max 归一化。
        """
        vector_scores = self._normalize_vector(vector_results)
        keyword_scores = self._normalize_minmax(keyword_results)
        metadata_scores = {r.memory_id: r.score for r in metadata_results}

        merged: dict[str, SearchResult] = {}

        def _ensure(result: SearchResult) -> SearchResult:
            entry = merged.get(result.memory_id)
            if entry is None:
                entry = SearchResult(
                    memory_id=result.memory_id,
                    memory_type=result.memory_type,
                    content=result.content,
                    score=0.0,
                    source="",
                    metadata=dict(result.metadata),
                )
                merged[result.memory_id] = entry
            else:
                # 优先保留有内容/类型的字段
                if not entry.content and result.content:
                    entry.content = result.content
                if not entry.memory_type and result.memory_type:
                    entry.memory_type = result.memory_type
                if not entry.metadata and result.metadata:
                    entry.metadata = dict(result.metadata)
            return entry

        sources: dict[str, list[str]] = {}
        for result in vector_results:
            entry = _ensure(result)
            entry.score += self.config.vector_weight * vector_scores.get(result.memory_id, 0.0)
            entry.metadata["vector_score"] = vector_scores.get(result.memory_id, 0.0)
            sources.setdefault(result.memory_id, []).append("vector")
        for result in keyword_results:
            entry = _ensure(result)
            entry.score += self.config.keyword_weight * keyword_scores.get(result.memory_id, 0.0)
            entry.metadata["keyword_score"] = keyword_scores.get(result.memory_id, 0.0)
            sources.setdefault(result.memory_id, []).append("keyword")
        for memory_id, score in metadata_scores.items():
            if memory_id not in merged:
                continue  # 元数据只对候选集合打分，不引入新候选
            entry = merged[memory_id]
            entry.score += self.config.metadata_weight * score
            entry.metadata["metadata_score"] = score
            sources.setdefault(memory_id, []).append("metadata")

        for memory_id, entry in merged.items():
            entry.source = "+".join(sources.get(memory_id, []))

        return sorted(merged.values(), key=lambda r: r.score, reverse=True)

    def _filter_by_context(
        self, results: list[SearchResult], request: SearchRequest
    ) -> list[SearchResult]:
        """按记忆类型、场景 scope 和置信度过滤结果"""
        filtered = []
        for result in results:
            memory = self.memory_lookup.get(result.memory_id)
            result_user_id = result.metadata.get("user_id") or getattr(memory, "user_id", "")
            if result_user_id and result_user_id != request.user_id:
                continue
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

    def _format_response(self, results: list[SearchResult], latency_ms: float) -> SearchResponse:
        """将检索结果格式化为 SearchResponse"""
        preferences: list[PreferenceMemory] = []
        knowledge: list[KnowledgeMemory] = []
        facts: list[FactMemory] = []
        for result in results:
            # 分层级联标注（REFACTOR_PLAN_V2 §4.4.3 / I-4）：长期记忆默认标注 memory_level=long
            result.memory_level = result.memory_level or "long"
            memory = self.memory_lookup.get(result.memory_id)
            if isinstance(memory, PreferenceMemory):
                preferences.append(memory)
            elif isinstance(memory, KnowledgeMemory):
                knowledge.append(memory)
        return SearchResponse(
            results=results,
            preferences=preferences,
            knowledge=knowledge,
            facts=facts,
            latency_ms=round(latency_ms, 2),
            total_count=len(results),
        )

    # ---- 内部 ----

    def _score_by_metadata(
        self, candidates: list[SearchResult], request: SearchRequest
    ) -> list[SearchResult]:
        """
        元数据打分（第一阶段简化实现）：
        scope 与 request.context 完全匹配记 1.0，无 scope 信息记 0.5，冲突记 0.0。
        """
        scored = []
        seen = set()
        for result in candidates:
            if result.memory_id in seen:
                continue
            seen.add(result.memory_id)
            scope = result.metadata.get("scope")
            if not isinstance(scope, dict):
                score = 0.5
            else:
                conflict = False
                matched = False
                for field in ("scene", "task_type", "app"):
                    expected = getattr(request.context, field, "")
                    if not expected:
                        continue
                    actual = scope.get(field, "")
                    # "*" 表示全局/通配作用域，对任意具体场景都不构成冲突
                    if actual and actual != "*" and actual != expected:
                        conflict = True
                        break
                    if actual == expected or actual == "*":
                        matched = True
                score = 0.0 if conflict else (1.0 if matched else 0.5)
            scored.append(
                SearchResult(memory_id=result.memory_id, score=score, source="metadata")
            )
        return scored

    @staticmethod
    def _scope_conflict(result: SearchResult, request: SearchRequest) -> bool:
        """scope 与请求 context 存在明确冲突时返回 True（无信息不算冲突）"""
        scope = result.metadata.get("scope")
        if not isinstance(scope, dict):
            return False
        for field in ("scene", "task_type", "app"):
            expected = getattr(request.context, field, "")
            actual = scope.get(field, "")
            # "*" 为全局/通配作用域，不与任何具体场景冲突
            if expected and actual and actual != "*" and actual != expected:
                return True
        return False

    @staticmethod
    def _normalize_vector(results: list[SearchResult]) -> dict[str, float]:
        """余弦相似度 [-1, 1] → [0, 1]"""
        return {r.memory_id: (r.score + 1.0) / 2.0 for r in results}

    @staticmethod
    def _normalize_minmax(results: list[SearchResult]) -> dict[str, float]:
        """min-max 归一化到 [0, 1]；所有分数相同时记 0.5"""
        if not results:
            return {}
        scores = [r.score for r in results]
        lo, hi = min(scores), max(scores)
        if hi <= lo:
            return {r.memory_id: 0.5 for r in results}
        return {r.memory_id: (r.score - lo) / (hi - lo) for r in results}
