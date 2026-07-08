"""
Mock Embedding SDK — 模拟麒麟 Embedding 服务。

在拿到真实 SDK 之前，用随机向量 + 固定延迟替代，
保持与真实 SDK 相同的接口约定，后续只需替换实现即可。
"""

import time
import hashlib
import random
from typing import List, Union

# 默认输出向量维度（匹配常见 Embedding 模型）
DEFAULT_DIM = 768
# 模拟网络/推理延迟（秒）
SIMULATED_LATENCY = 0.1


class MockEmbeddingClient:
    """
    模拟的 Embedding 客户端，接口设计与真实 SDK 对齐。
    后续替换为麒麟 SDK 时只需实现同样的方法签名。
    """

    def __init__(self, dim: int = DEFAULT_DIM, latency: float = SIMULATED_LATENCY, seed: int = 42):
        """
        Args:
            dim: 向量维度，默认 768
            latency: 模拟耗时（秒），默认 0.1
            seed: 随机种子，保证同一文本每次调用结果一致（可复现）
        """
        self.dim = dim
        self.latency = latency
        self.seed = seed

    def _deterministic_seed(self, text: str) -> int:
        """根据文本内容生成确定性种子，保证同一文本返回同一向量。"""
        hash_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(hash_bytes[:4], byteorder="big")

    def embed(self, text: str) -> List[float]:
        """
        对单条文本做 Embedding。

        Args:
            text: 输入文本

        Returns:
            长度为 dim 的浮点数向量（list[float]）
        """
        time.sleep(self.latency)  # 模拟推理耗时

        rng = random.Random(self._deterministic_seed(text))
        # 随机生成向量，不做归一化（FAISS 内部可用 IndexFlatIP 做内积搜索）
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量 Embedding（模拟批量推理）。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量长度为 dim
        """
        # 批量模式下每批也有一个固定延迟（模拟一次批量推理调用）
        time.sleep(self.latency)
        return [self.embed_without_latency(t) for t in texts]

    def embed_without_latency(self, text: str) -> List[float]:
        """不模拟延迟的单条向量生成（供 batch 内部使用）。"""
        rng = random.Random(self._deterministic_seed(text))
        return [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
