"""
Embedding 子包 — 统一入口。

提供工厂函数 create_embedding_client()：
- provider="kylin"：麒麟真实 .so，加载失败抛 KylinEmbeddingError
- provider="kylin_mock"：项目内 mock 动态库（真实 SDK 相同 API）
- provider="mock"：纯 Python MockEmbeddingClient
- provider=None（或 "auto"）：Kylin OS + .so 存在 → KylinEmbeddingClient，
  其他环境 → MockEmbeddingClient（向后兼容的自动选择）

调用方无需关心底层实现。
"""

from .base import BaseEmbeddingClient
from .mock_client import MockEmbeddingClient
from .kylin_client import KylinEmbeddingClient, KylinEmbeddingError

__all__ = [
    "BaseEmbeddingClient",
    "KylinEmbeddingClient",
    "KylinEmbeddingError",
    "MockEmbeddingClient",
    "create_embedding_client",
]

_KYLIN_KWARGS = ("dim", "model_name", "so_path", "mock_so_path", "query_timeout_ms")
_MOCK_KWARGS = ("dim", "latency", "seed")


def create_embedding_client(
    provider: str | None = None, **kwargs
) -> BaseEmbeddingClient:
    """
    创建 Embedding 客户端。

    通用参数 (dim) 对所有实现有效。
    Kylin 专有参数 (model_name, so_path, mock_so_path) 仅传给 Kylin 客户端。
    Mock 专有参数 (latency, seed) 仅传给 Mock 客户端。

    参数:
        provider: "kylin" | "kylin_mock" | "mock" | None/"auto"（自动选择）
        **kwargs: 透传给具体客户端实现

    返回:
        BaseEmbeddingClient 实例

    异常:
        KylinEmbeddingError: 显式指定 kylin/kylin_mock 但动态库加载或初始化失败
        ValueError: 未知 provider
    """
    kylin_kwargs = {k: v for k, v in kwargs.items() if k in _KYLIN_KWARGS}
    mock_kwargs = {k: v for k, v in kwargs.items() if k in _MOCK_KWARGS}

    if provider == "mock":
        return MockEmbeddingClient(**mock_kwargs)

    if provider == "kylin_mock":
        client = KylinEmbeddingClient(use_mock=True, **kylin_kwargs)
        if not client.is_available():
            raise KylinEmbeddingError("embedding.mock_unavailable")
        return client

    if provider == "kylin":
        client = KylinEmbeddingClient(**kylin_kwargs)
        if not client.is_available():
            raise KylinEmbeddingError("embedding.unavailable")
        return client

    if provider in (None, "", "auto"):
        # 自动选择：Kylin（真实） > Mock（开发用），保持向后兼容
        kylin = KylinEmbeddingClient(**kylin_kwargs)
        if kylin.is_available():
            return kylin
        return MockEmbeddingClient(**mock_kwargs)

    raise ValueError(f"unknown embedding provider: {provider}")
