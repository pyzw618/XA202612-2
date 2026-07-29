"""
混合检索入口

组合向量检索、关键词检索、元数据过滤，返回融合结果。
"""

from memoryhub.adapter.schemas import SearchRequest, SearchResponse, SearchResult


class HybridRetriever:
    """
    混合检索器

    使用方式:
        retriever = HybridRetriever(vector_store, keyword_store, cache)
        response = retriever.search(request)
    """

    def __init__(
        self,
        vector_search=None,
        keyword_search=None,
        reranker=None,
        cache=None,
    ):
        """
        参数:
            vector_search: VectorSearcher 实例
            keyword_search: KeywordSearcher 实例
            reranker: Reranker 实例
            cache: SearchCache 实例
        """
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.reranker = reranker
        self.cache = cache

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
        raise NotImplementedError

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

        对同一 memory_id 的结果合并分数。
        """
        raise NotImplementedError

    def _filter_by_context(self, results: list[SearchResult], request: SearchRequest) -> list[SearchResult]:
        """按场景 scope 和置信度过滤结果"""
        raise NotImplementedError

    def _format_response(self, results: list[SearchRequest], latency_ms: float) -> SearchResponse:
        """将检索结果格式化为 SearchResponse"""
        raise NotImplementedError
