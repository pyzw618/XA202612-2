"""
检索缓存模块

LRU 缓存，减少重复检索的延迟。
"""

from memoryhub.adapter.schemas import SearchRequest, SearchResponse


class SearchCache:
    """
    检索结果 LRU 缓存

    使用方式:
        cache = SearchCache(max_size=1000, ttl_seconds=300)
        cached = cache.get(request)
        if cached is None:
            result = retriever.search(request)
            cache.set(request, result)
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 300):
        """
        参数:
            max_size: 最大缓存条目数
            ttl_seconds: 缓存过期时间（秒）
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache = {}

    def get(self, request: SearchRequest) -> SearchResponse | None:
        """
        查询缓存

        参数:
            request: 检索请求

        返回:
            缓存的 SearchResponse 或 None（未命中/已过期）
        """
        raise NotImplementedError

    def set(self, request: SearchRequest, response: SearchResponse) -> None:
        """
        写入缓存

        参数:
            request: 检索请求（作为 key）
            response: 检索结果（作为 value）
        """
        raise NotImplementedError

    def invalidate(self, memory_id: str) -> None:
        """
        使包含指定记忆 ID 的缓存条目失效

        数据流: 记忆更新/删除 → invalidate → 清除相关缓存

        参数:
            memory_id: 被更新/删除的记忆 ID
        """
        raise NotImplementedError

    def clear(self) -> None:
        """清空所有缓存"""
        raise NotImplementedError

    def size(self) -> int:
        """返回当前缓存条目数"""
        raise NotImplementedError

    def _make_key(self, request: SearchRequest) -> str:
        """生成缓存 key"""
        raise NotImplementedError
