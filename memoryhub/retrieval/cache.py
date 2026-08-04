"""
检索缓存模块

LRU 缓存，减少重复检索的延迟。
"""

import time
from collections import OrderedDict

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
        self._cache: OrderedDict[str, tuple[float, SearchResponse]] = OrderedDict()

    def get(
        self, request: SearchRequest, version: str | None = None
    ) -> SearchResponse | None:
        """
        查询缓存

        参数:
            request: 检索请求
            version: 可选的版本号，会作为缓存键的一部分；
                用于在索引版本变化时隔离旧缓存。

        返回:
            缓存的 SearchResponse 或 None（未命中/已过期）
        """
        key = self._make_key(request, version)
        entry = self._cache.get(key)
        if entry is None:
            return None

        created_at, response = entry
        if time.time() - created_at > self.ttl_seconds:
            del self._cache[key]
            return None

        # 命中：移动到末尾，维持 LRU 顺序
        self._cache.move_to_end(key)
        return response

    def set(
        self,
        request: SearchRequest,
        response: SearchResponse,
        version: str | None = None,
    ) -> None:
        """
        写入缓存

        参数:
            request: 检索请求（作为 key）
            response: 检索结果（作为 value）
            version: 可选的版本号，会作为缓存键的一部分
        """
        key = self._make_key(request, version)
        self._cache[key] = (time.time(), response)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def invalidate(self, memory_id: str) -> None:
        """
        使包含指定记忆 ID 的缓存条目失效

        数据流: 记忆更新/删除 → invalidate → 清除相关缓存

        参数:
            memory_id: 被更新/删除的记忆 ID
        """
        stale_keys = [
            key
            for key, (_, response) in self._cache.items()
            if self._contains_memory(response, memory_id)
        ]
        for key in stale_keys:
            del self._cache[key]

    def clear(self) -> None:
        """清空所有缓存"""
        self._cache.clear()

    def size(self) -> int:
        """返回当前缓存条目数"""
        return len(self._cache)

    def _make_key(self, request: SearchRequest, version: str | None = None) -> str:
        """生成缓存 key（索引版本 + 请求的 canonical JSON 表示）"""
        base = request.model_dump_json()
        if version:
            return f"{version}:{base}"
        return base

    @staticmethod
    def _contains_memory(response: SearchResponse, memory_id: str) -> bool:
        """判断响应中是否包含指定记忆 ID"""
        if any(r.memory_id == memory_id for r in response.results):
            return True
        if any(p.memory_id == memory_id for p in response.preferences):
            return True
        if any(k.memory_id == memory_id for k in response.knowledge):
            return True
        return any(f.fact_id == memory_id for f in response.facts)
