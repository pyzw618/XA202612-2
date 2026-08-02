"""
向量引擎抽象基类。

定义所有向量引擎实现（FAISS / Milvus）必须遵循的统一接口，
调用方（检索层）无需关心底层是本地 FAISS 索引还是 Milvus 服务。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class VectorSearchResult:
    """向量检索结果。"""

    memory_id: str
    content: str
    score: float
    source: str = "dense"  # dense | sparse | hybrid
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseVectorEngine(ABC):
    """
    向量引擎抽象基类。

    支持上下文管理器协议，退出时自动调用 close()：

        with create_vector_engine("faiss", index_path=...) as engine:
            engine.insert(...)
    """

    @abstractmethod
    def insert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        插入一条记忆。

        参数:
            memory_id: 记忆 ID（主键，重复插入视为更新）
            text: 原始文本内容（用于生成稀疏向量）
            vector: 稠密向量
            metadata: 可选元数据
        """
        ...

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """
        稠密向量检索。

        参数:
            query_vector: 查询稠密向量
            top_k: 返回数量
            filters: 可选过滤条件（实现可自行支持或忽略）

        返回:
            VectorSearchResult 列表，按相关度降序
        """
        ...

    @abstractmethod
    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
    ) -> list[VectorSearchResult]:
        """
        混合检索（稠密 + 稀疏，RRF 融合）。

        参数:
            dense_vector: 查询稠密向量
            sparse_terms: 查询稀疏向量，[(token 索引, 权重), ...]，
                由 sparse.build_sparse_vector 生成
            top_k: 返回数量

        返回:
            VectorSearchResult 列表，按 RRF 融合分降序
        """
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """
        删除一条记忆。

        参数:
            memory_id: 记忆 ID，删除不存在的 ID 不应报错
        """
        ...

    @abstractmethod
    def persist(self) -> None:
        """持久化索引到磁盘（对服务端引擎可为 no-op）。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """释放引擎资源，必须幂等（可重复调用）。"""
        ...

    def __enter__(self) -> "BaseVectorEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
