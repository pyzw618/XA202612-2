"""
重排序模块

对融合后的检索结果进行二次排序。
"""

from datetime import datetime

from memoryhub.adapter.schemas import SearchRequest, SearchResult


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
            1. 原始检索分数（第一阶段唯一因子）
            2. 与查询的语义相关性（LLM 打分或交叉编码器，后续接入）
            3. 场景 scope 匹配度
            4. 置信度
            5. 时间新鲜度
        """
        return sorted(results, key=lambda r: r.score, reverse=True)

    def _compute_relevance_score(self, query: str, content: str) -> float:
        """计算查询与内容的相关性分数（基于词项重叠的简易实现）"""
        query_terms = {t for t in query.lower().split() if t}
        if not query_terms or not content:
            return 0.0
        content_lower = content.lower()
        hits = sum(1 for t in query_terms if t in content_lower)
        return hits / len(query_terms)

    def _compute_scope_score(self, result: SearchResult, request: SearchRequest) -> float:
        """计算场景匹配分数：scope 与请求 context 逐字段匹配的比例"""
        scope = result.metadata.get("scope")
        if not isinstance(scope, dict):
            return 0.5  # 无 scope 信息时给中性分
        fields = ("scene", "task_type", "app")
        matched = 0
        total = 0
        for field in fields:
            expected = getattr(request.context, field, "")
            if not expected:
                continue
            total += 1
            if scope.get(field, "") == expected:
                matched += 1
        if total == 0:
            return 0.5
        return matched / total

    def _compute_freshness_score(self, result: SearchResult) -> float:
        """计算时间新鲜度分数：按天数指数衰减，30 天半衰期"""
        raw = result.metadata.get("updated_at") or result.metadata.get("created_at")
        if not raw:
            return 0.5  # 无时间信息时给中性分
        try:
            ts = datetime.fromisoformat(str(raw))
        except ValueError:
            return 0.5
        age_days = max((datetime.now() - ts.replace(tzinfo=None)).days, 0)
        return 0.5 ** (age_days / 30.0)
