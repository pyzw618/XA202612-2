"""
向量引擎抽象层。

通过 create_vector_engine 工厂按 provider 创建具体引擎实现：
- "milvus"：麒麟 Milvus SDK（生产唯一链路）
- "milvus_mock"：项目内 mock 动态库（非麒麟环境测试）
- "faiss"：本地 FAISS 索引（仅 development/test 或显式故障诊断场景使用，
  生产配置不可达）
"""

import logging
from typing import Any

from memoryhub.storage.vector_engine._milvus_ctypes import MilvusEngineError
from memoryhub.storage.vector_engine.base import BaseVectorEngine, VectorSearchResult
from memoryhub.storage.vector_engine.sparse import build_sparse_vector

logger = logging.getLogger(__name__)

__all__ = [
    "BaseVectorEngine",
    "MilvusEngineError",
    "VectorSearchResult",
    "build_sparse_vector",
    "create_vector_engine",
]


def create_vector_engine(provider: str, **kwargs: Any) -> BaseVectorEngine:
    """
    向量引擎工厂。

    参数:
        provider: "faiss" | "milvus" | "milvus_mock"
        **kwargs: 透传给具体引擎构造函数
            - faiss: index_path, dimension
            - milvus: so_path, host, port, collection, dimension
            - milvus_mock: 同 milvus（so_path 默认指向项目内 mock 库）

    返回:
        BaseVectorEngine 实例
    """
    if provider == "faiss":
        from memoryhub.config import is_production_mode
        from memoryhub.storage.vector_engine.faiss_engine import FAISSVectorEngine

        if is_production_mode():
            logger.warning(
                "faiss_engine_created_in_production_mode: "
                "FAISS is only allowed in development/test or explicit diagnostic scenarios"
            )
        return FAISSVectorEngine(**kwargs)
    if provider == "milvus":
        from memoryhub.storage.vector_engine.milvus_engine import MilvusVectorEngine

        return MilvusVectorEngine(**kwargs)
    if provider == "milvus_mock":
        from memoryhub.storage.vector_engine.milvus_engine import MilvusVectorEngine

        kwargs.setdefault("mock", True)
        return MilvusVectorEngine(**kwargs)
    raise ValueError(f"unknown vector_engine provider: {provider}")
