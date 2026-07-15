"""
Mock Embedding 客户端

开发和测试用，不依赖真实 SDK。
"""

import hashlib
import random

from memoryhub.embedding.base import BaseEmbeddingClient


class MockEmbeddingClient(BaseEmbeddingClient):
    """
    Mock Embedding 客户端

    使用方式:
        client = MockEmbeddingClient(dimension=1024)
        vector = client.embed("任意文本")  # 返回确定性伪向量

    特点:
        - 相同文本返回相同向量（基于 hash 的确定性）
        - 不同文本返回不同向量
        - 不依赖任何外部服务
        - 适合开发调试和单元测试
    """

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        """
        生成确定性伪向量

        实现: 基于 text 的 hash 值生成伪随机向量，
             保证相同文本总是返回相同结果。
        """
        # 基于 hash 的确定性伪向量生成
        seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        vector = [rng.gauss(0, 1) for _ in range(self.dimension)]
        # 归一化
        norm = sum(x**2 for x in vector) ** 0.5
        return [x / norm for x in vector]

    def batch_embed(self, texts: list[str]) -> list[list[float]]:
        """批量调用 embed"""
        return [self.embed(t) for t in texts]

    def get_dimension(self) -> int:
        return self.dimension

    def is_available(self) -> bool:
        return True
