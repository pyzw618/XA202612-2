"""
向量引擎抽象层。

通过 create_vector_engine 工厂按 provider 创建具体引擎实现：
- "milvus"：麒麟 Milvus SDK（生产唯一链路）

Mock 与 FAISS 实现已移除。
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
        provider: 仅支持 "milvus"
        **kwargs: 透传给 MilvusVectorEngine
            (app_id, so_path, host, port, collection, dimension)

    返回:
        MilvusVectorEngine 实例
    """
    if provider == "milvus":
        from memoryhub.storage.vector_engine.milvus_engine import MilvusVectorEngine

        return MilvusVectorEngine(**kwargs)
    raise ValueError(f"unknown vector_engine provider: {provider}")
