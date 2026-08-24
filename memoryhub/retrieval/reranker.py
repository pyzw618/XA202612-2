"""
重排序模块

对融合后的检索结果进行二次排序。
"""

from memoryhub.adapter.schemas import SearchRequest, SearchResult
from memoryhub.adapter.vnext_schemas import RetrievedMemory
from memoryhub.core.memory.freshness import freshness_score
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope


class Reranker:
    """
    检索结果重排序器

    第一阶段实现：按融合分数降序排列，保证链路跑通。
    第二阶段可叠加时间新鲜度、scope 匹配度等因子（见各 _compute_* 方法）。

    使用方式:
        reranker = Reranker()
        reranked = reranker.rerank(results, request)
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def rerank(
        self, results: list[SearchResult], request: SearchRequest
    ) -> list[SearchResult]:
        """
        对检索结果重排序

        数据流:
            融合结果 → rerank → 重排序结果

        参数:
            results: 融合后的检索结果
            request: 原始检索请求

        返回:
            重排序后的 SearchResult 列表

        排序因子:
            1. 原始检索分数（第一阶段唯一因子）
            2. 与查询的语义相关性（LLM 打分或交叉编码器，后续接入）
            3. 场景 scope 匹配度
            4. 置信度
            5. 时间新鲜度
            6. 记忆健康度（被动遗忘）
        """
        scored_results = []
        for result in results:
            relevance = self._compute_relevance_score(request.query, result.content)
            scope = self._compute_scope_score(result, request)
            freshness = self._compute_freshness_score(result)
            health = self._compute_health_score(result)

            confidence = self._compute_confidence_score(result)

            # Preserve relevance while applying bounded lifecycle signals.
            final_score = (
                0.45 * self._clamp(result.score)
                + 0.15 * relevance
                + 0.10 * scope
                + 0.10 * confidence
                + 0.10 * freshness
                + 0.10 * health
            )
            # Keep SearchResult.score as the documented hybrid-fusion score.
            # Reranking changes order only; expose its score separately for auditability.
            result.metadata["rerank_score"] = final_score
            result.metadata["relevance_score"] = relevance
            result.metadata["scope_score"] = scope
            result.metadata["freshness_score"] = freshness
            result.metadata["health_score"] = health
            result.metadata["confidence_score"] = confidence
            scored_results.append((final_score, result))

        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored_results]

    def _merge_scores(self, relevance_score: float, health_score: float) -> float:
        """
        融合相关性分数与健康度分数。

        公式：final_score = 0.7 * relevance_score + 0.3 * health_score
        健康度低的记忆自然被排到后面，实现被动遗忘。
        """
        alpha = 0.7
        beta = 0.3
        return alpha * relevance_score + beta * health_score

    def _compute_health_score(self, result: SearchResult) -> float:
        """
        从 SearchResult 的 metadata 中读取健康度。
        若未提供，默认为 1.0（最健康）。
        """
        return result.metadata.get("health_score", 1.0)

    def _compute_relevance_score(self, query: str, content: str) -> float:
        """
        计算查询与内容的相关性分数

        第一版使用简单的关键词重叠度（Jaccard 近似）作为默认值。
        后续可替换为 LLM 打分或交叉编码器。
        """
        if not query or not content:
            return 0.0

        query_tokens = set(query.lower().split())
        content_tokens = set(content.lower().split())

        if not query_tokens:
            return 0.0

        overlap = query_tokens & content_tokens
        union = query_tokens | content_tokens
        if not union:
            return 0.0

        return len(overlap) / len(union)

    def _compute_scope_score(
        self, result: SearchResult, request: SearchRequest
    ) -> float:
        """
        计算场景匹配分数

        比较 result.metadata 中的 scope 字段与 request.context，
        scene / task_type / app 三者同时匹配得 1.0，部分匹配按比例得分。
        """
        result_scope = result.metadata.get("scope", {}) or {}
        request_scope = request.context.model_dump() if request.context else {}

        if not request_scope:
            return 1.0

        keys = ["scene", "task_type", "app"]
        matches = 0
        total = 0
        for key in keys:
            expected = request_scope.get(key)
            if expected:
                total += 1
                if result_scope.get(key) == expected:
                    matches += 1

        return 1.0 if total == 0 else matches / total

    def _compute_confidence_score(self, result: SearchResult) -> float:
        return self._clamp(result.metadata.get("confidence", 1.0))

    def _compute_freshness_score(self, result: SearchResult) -> float:
        """Use the same per-memory-type half lives as confidence calculation."""
        timestamp = (
            result.metadata.get("observed_at")
            or result.metadata.get("updated_at")
            or result.metadata.get("created_at")
        )
        return freshness_score(timestamp, memory_type=result.memory_type)

    @staticmethod
    def _clamp(value) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


class VNextReranker:
    """Unified reranker for vNext ``RetrievedMemory`` candidates.

    The reranker is deterministic and explainable: every candidate receives a
    ``final_score`` together with a ``score_breakdown`` that records the
    contribution of each factor.  It never mutates the input ``score`` field;
    instead it writes its results into the candidate's ``score_breakdown`` and
    returns newly ordered ``RetrievedMemory`` objects whose ``score`` field is
    the reranked score.
    """

    DEFAULT_TYPE_WEIGHTS: dict[str, float] = {
        "PREFERENCE": 0.20,
        "SEMANTIC": 0.25,
        "PROCEDURAL": 0.25,
        "EPISODIC": 0.20,
        "WORKING": 0.05,
        "EPISODE": 0.05,
    }

    def __init__(
        self,
        *,
        base_weight: float = 0.35,
        relevance_weight: float = 0.20,
        scope_weight: float = 0.15,
        confidence_weight: float = 0.10,
        freshness_weight: float = 0.10,
        health_weight: float = 0.10,
        intent_type_boosts: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.base_weight = base_weight
        self.relevance_weight = relevance_weight
        self.scope_weight = scope_weight
        self.confidence_weight = confidence_weight
        self.freshness_weight = freshness_weight
        self.health_weight = health_weight
        self.intent_type_boosts = intent_type_boosts or {}

    def rerank(
        self,
        candidates: list[RetrievedMemory],
        *,
        query: str = "",
        scope_level: MemoryScope | None = None,
        scope: str = "",
        task_id: str = "",
        top_k: int | None = None,
        intent: str = "",
    ) -> list[RetrievedMemory]:
        """Rerank fused candidates and return a new ordered list."""
        scored: list[tuple[float, RetrievedMemory]] = []
        for candidate in candidates:
            breakdown = self._score(candidate, query, scope_level, scope, task_id, intent)
            final_score = breakdown["final_score"]
            merged_breakdown = dict(candidate.score_breakdown)
            merged_breakdown.update(breakdown)
            new_candidate = RetrievedMemory(
                **candidate.model_dump(
                    exclude={"score", "score_breakdown"}, mode="json"
                ),
                score=round(final_score, 6),
                score_breakdown=merged_breakdown,
            )
            scored.append((final_score, new_candidate))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        result = [item for _, item in scored]
        if top_k is not None:
            result = result[:top_k]
        return result

    def _score(
        self,
        candidate: RetrievedMemory,
        query: str,
        scope_level: MemoryScope | None,
        scope: str,
        task_id: str,
        intent: str,
    ) -> dict[str, float]:
        base_score = self._clamp(candidate.score)
        relevance = self._compute_relevance(query, candidate)
        scope_match = self._compute_scope_match(candidate, scope_level, scope, task_id)
        confidence = self._clamp(candidate.content.get("confidence", 0.8))
        freshness = self._compute_freshness(candidate)
        health = self._clamp(candidate.content.get("health_score", 1.0))

        weighted = (
            self.base_weight * base_score
            + self.relevance_weight * relevance
            + self.scope_weight * scope_match
            + self.confidence_weight * confidence
            + self.freshness_weight * freshness
            + self.health_weight * health
        )

        # Intent-aware type boost: e.g. PREFERENCE queries may up-weight PREFERENCE.
        type_key = candidate.memory_type.value
        if candidate.layer is not LifecycleLayer.LONG_TERM:
            type_key = candidate.layer.value
        boost = self.intent_type_boosts.get(intent, {}).get(type_key, 1.0)
        final_score = min(1.0, weighted * boost)

        return {
            "final_score": round(final_score, 6),
            "base_score": round(base_score, 6),
            "relevance_score": round(relevance, 6),
            "scope_match_score": round(scope_match, 6),
            "confidence_score": round(confidence, 6),
            "freshness_score": round(freshness, 6),
            "health_score": round(health, 6),
            "type_boost": round(boost, 6),
        }

    @staticmethod
    def _compute_relevance(query: str, candidate: RetrievedMemory) -> float:
        if not query:
            return 0.0
        text = " ".join(
            str(value)
            for value in candidate.content.values()
            if isinstance(value, (str, int, float))
        ).lower()
        query_tokens = set(query.lower().split())
        content_tokens = set(text.split())
        if not query_tokens or not content_tokens:
            return 0.0
        overlap = query_tokens & content_tokens
        union = query_tokens | content_tokens
        return len(overlap) / len(union)

    def _compute_scope_match(
        self,
        candidate: RetrievedMemory,
        scope_level: MemoryScope | None,
        scope: str,
        task_id: str,
    ) -> float:
        # Exact scope match is strongest.
        if scope_level is not None and candidate.scope_level == scope_level:
            if scope and candidate.scope == scope:
                return 1.0
            if candidate.scope_level is MemoryScope.GLOBAL:
                return 0.8
            return 0.6

        # TASK scope matches current task_id strongly.
        if task_id and candidate.scope == f"TASK:{task_id}":
            return 0.9

        # Prefer narrower scopes over GLOBAL when no explicit scope requested.
        if scope_level is None:
            if candidate.scope_level is MemoryScope.GLOBAL:
                return 0.5
            return 0.7

        # Different explicit scope: still give partial credit for same tenant/user.
        return 0.2

    @staticmethod
    def _compute_freshness(candidate: RetrievedMemory) -> float:
        timestamp = (
            candidate.content.get("updated_at")
            or candidate.content.get("created_at")
            or candidate.content.get("valid_from")
        )
        memory_type = candidate.memory_type.value if candidate.memory_type else ""
        try:
            return freshness_score(timestamp, memory_type=memory_type)
        except Exception:
            return 1.0

    @staticmethod
    def _clamp(value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0


__all__ = ["Reranker", "VNextReranker"]
