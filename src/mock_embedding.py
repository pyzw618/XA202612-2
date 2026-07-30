"""
向后兼容层 — re-export 到新位置的 MockEmbeddingClient。

原有代码 `from src.mock_embedding import MockEmbeddingClient` 仍然可用。
新代码推荐 `from src.embedding import create_embedding_client` 使用工厂函数。
"""

from src.embedding.mock_client import MockEmbeddingClient  # noqa: F401
