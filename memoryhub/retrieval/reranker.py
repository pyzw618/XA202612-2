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
        """
        raise NotImplementedError

    def _compute_relevance_score(self, query: str, content: str) -> float:
        """计算查询与内容的相关性分数"""
        raise NotImplementedError

    def _compute_scope_score(self, result: SearchResult, request: SearchRequest) -> float:
        """计算场景匹配分数"""
        raise NotImplementedError

    def _compute_freshness_score(self, result: SearchResult) -> float:
        """计算时间新鲜度分数"""
        raise NotImplementedError
