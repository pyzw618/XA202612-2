"""
Embedding 子包 — 统一入口。

提供工厂函数 create_embedding_client()：
- Kylin OS + .so 存在 → KylinEmbeddingClient（真实语义向量）
- 其他环境 → MockEmbeddingClient（确定性随机向量）

调用方无需关心底层实现。
"""

from .base import BaseEmbeddingClient
from .mock_client import MockEmbeddingClient
from .kylin_client import KylinEmbeddingClient


def create_embedding_client(**kwargs) -> BaseEmbeddingClient:
    """
    创建 Embedding 客户端（自动选择最佳实现）。

    优先级：Kylin（真实） > Mock（开发用）

    通用参数 (dim) 对两者都有效。
    Kylin 专有参数 (model_name, so_path) 仅传给 Kylin 客户端。
    Mock 专有参数 (latency, seed) 仅传给 Mock 客户端。

    Args:
        **kwargs: 透传给具体客户端实现

    Returns:
        BaseEmbeddingClient 实例
    """
    # Kylin 专有参数
    kylin_kwargs = {k: v for k, v in kwargs.items() if k in ("dim", "model_name", "so_path")}
    kylin = KylinEmbeddingClient(**kylin_kwargs)
    if kylin.is_available():
        return kylin

    # Mock 专有参数
    mock_kwargs = {k: v for k, v in kwargs.items() if k in ("dim", "latency", "seed")}
    return MockEmbeddingClient(**mock_kwargs)
