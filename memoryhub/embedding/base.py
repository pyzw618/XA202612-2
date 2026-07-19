"""
Embedding 抽象基类。

定义所有 Embedding 客户端必须实现的统一接口。
Mock 和 Kylin 实现都继承此类，调用方无需关心底层实现。
"""

from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingClient(ABC):
    """Embedding 客户端抽象基类。"""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """
        对单条文本生成向量。

        Args:
            text: 输入文本

        Returns:
            浮点数向量列表
        """
        ...

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        对多条文本批量生成向量。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个元素对应一条输入文本
        """
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """
        返回当前模型输出的向量维度。

        Returns:
            向量维度（如 768）
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """
        检测当前客户端是否可用。

        例如 Kylin 客户端在非 Linux 或无 .so 时返回 False，
        调用方可通过工厂函数自动降级到 Mock。

        Returns:
            True 表示可以正常调用 embed
        """
        ...
