"""
重排序模块

对融合后的检索结果进行二次排序。
"""

from memoryhub.adapter.schemas import SearchResult, SearchRequest


class Reranker:
    """
    检索结果重排序器

    使用方式:
        reranker = Reranker(llm_client=llm)
        reranked = reranker.rerank(results, request)
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def rerank(self, results: list[SearchResult], request: SearchRequest) -> list[SearchResult]:
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
            1. 原始检索分数
            2. 与查询的语义相关性（LLM 打分或交叉编码器）
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

            # 综合得分：原始分数 + 相关性 + 场景 + 新鲜度 + 健康度
            final_score = (
                0.50 * result.score
                + 0.20 * relevance
                + 0.10 * scope
                + 0.10 * freshness
                + 0.10 * health
            )

            result.score = final_score
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

    def _compute_scope_score(self, result: SearchResult, request: SearchRequest) -> float:
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

    def _compute_freshness_score(self, result: SearchResult) -> float:
        """
        计算时间新鲜度分数

        基于 result.metadata["updated_at"] 计算距今天数，
        越近越新鲜。无时间戳时默认返回 1.0。
        """
        from datetime import datetime

        updated_at = result.metadata.get("updated_at")
        if updated_at is None:
            return 1.0

        try:
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at)
            now = datetime.now()
            days = (now - updated_at).total_seconds() / 86400.0
        except (ValueError, TypeError):
            return 1.0

        # 30 天内线性衰减，超过 30 天视为 0.0
        return max(0.0, 1.0 - days / 30.0)
