"""
Mock Embedding 客户端实现。

用于开发环境，用确定性随机向量替代真实 Embedding 推理。
同一文本永远返回相同向量，保证可复现。
"""

import time
import hashlib
import random
from typing import List

from .base import BaseEmbeddingClient

DEFAULT_DIM = 768
SIMULATED_LATENCY = 0.1


class MockEmbeddingClient(BaseEmbeddingClient):
    """
    模拟的 Embedding 客户端。

    使用 SHA256 哈希 + 固定随机种子，保证：
    - 同一文本 → 同一向量（确定性）
    - 不同文本 → 不同向量
    - time.sleep(latency) 模拟真实推理耗时
    """

    def __init__(self, dim: int = DEFAULT_DIM, latency: float = SIMULATED_LATENCY, seed: int = 42):
        self.dim = dim
        self.latency = latency
        self.seed = seed

    # ---- 实现抽象方法 ----

    def embed(self, text: str) -> List[float]:
        time.sleep(self.latency)
        rng = random.Random(self._deterministic_seed(text))
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        time.sleep(self.latency)
        return [self._embed_no_latency(t) for t in texts]

    def get_dimension(self) -> int:
        return self.dim

    def is_available(self) -> bool:
        return True  # Mock 始终可用

    def close(self) -> None:
        """释放资源；Mock 客户端无需特殊清理。"""
        pass

    # ---- 内部方法 ----

    def _deterministic_seed(self, text: str) -> int:
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(hash_bytes[:4], byteorder="big")

    def _embed_no_latency(self, text: str) -> List[float]:
        rng = random.Random(self._deterministic_seed(text))
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
