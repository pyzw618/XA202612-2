"""
Embedding 抽象基类

定义统一的向量化接口，支持不同后端实现。
"""

from abc import ABC, abstractmethod


class BaseEmbeddingClient(ABC):
    """
    Embedding 客户端抽象基类

    所有 Embedding 后端（麒麟 SDK、Mock 等）都实现此接口。
    上层模块（检索、存储）只依赖此接口。

    使用方式:
        client = KylinEmbeddingClient()
        vector = client.embed("项目周报生成流程")
    """

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """
        将文本转化为向量

        参数:
            text: 待向量化的文本

        返回:
            float 列表（向量）

        性能要求:
            单次调用应在 100ms 内完成
        """
        raise NotImplementedError

    @abstractmethod
    def batch_embed(self, texts: list[str]) -> list[list[float]]:
        """
        批量文本向量化

        参数:
            texts: 文本列表

        返回:
            向量列表

        说明:
            批量接口应比逐条调用 embed 更高效
        """
        raise NotImplementedError

    @abstractmethod
    def get_dimension(self) -> int:
        """
        返回向量维度

        返回:
            int，如 1024、768 等
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查 embedding 服务是否可用

        返回:
            True 表示服务正常
        """
        raise NotImplementedError
