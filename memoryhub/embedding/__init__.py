"""
Embedding 子包 — 统一入口。

提供工厂函数 create_embedding_client()：
- provider="kylin"：麒麟真实 .so，加载失败抛 KylinEmbeddingError
- provider=None（或 "auto"）：等价于 "kylin"

Mock 实现已移除；非麒麟环境没有 .so 时调用会抛 KylinEmbeddingError。
"""

from .base import BaseEmbeddingClient
from .kylin_client import KylinEmbeddingClient, KylinEmbeddingError

__all__ = [
    "BaseEmbeddingClient",
    "KylinEmbeddingClient",
    "KylinEmbeddingError",
    "create_embedding_client",
]

_KYLIN_KWARGS = ("dim", "model_name", "so_path", "query_timeout_ms")


def create_embedding_client(
    provider: str | None = None, **kwargs
) -> BaseEmbeddingClient:
    """
    创建 Embedding 客户端（仅支持麒麟真实 SDK）。

    参数:
        provider: "kylin" | None/"auto"（均指向麒麟真实 SDK）
        **kwargs: 透传给 KylinEmbeddingClient（dim, model_name, so_path, query_timeout_ms）

    返回:
        KylinEmbeddingClient 实例

    异常:
        KylinEmbeddingError: 动态库加载或初始化失败
        ValueError: 未知 provider
    """
    kylin_kwargs = {k: v for k, v in kwargs.items() if k in _KYLIN_KWARGS}

    if provider in (None, "", "auto", "kylin"):
        client = KylinEmbeddingClient(**kylin_kwargs)
        if not client.is_available():
            raise KylinEmbeddingError("embedding.unavailable")
        return client

    raise ValueError(f"unknown embedding provider: {provider}")
