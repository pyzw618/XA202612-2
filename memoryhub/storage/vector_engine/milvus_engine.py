"""
Milvus 向量引擎实现。

通过 ctypes 桥接（_milvus_ctypes.py）调用
libkysdk-vector-engine-client-capi（或项目内 mock 动态库），
实现 BaseVectorEngine 接口。稀疏向量由 C 侧在 insert 时根据
content 生成；查询侧稀疏向量由调用方用 sparse.build_sparse_vector
生成后传入 hybrid_search。
"""

import json
from typing import Any, Optional

from memoryhub.storage.vector_engine._milvus_ctypes import (
    MilvusEngineError,
    _MilvusCAPI,
    vector_engine_t,
)
from memoryhub.storage.vector_engine.base import BaseVectorEngine, VectorSearchResult


class MilvusVectorEngine(BaseVectorEngine):
    """
    Milvus 向量引擎（基于麒麟 C API SDK）。

    使用方式:
        engine = MilvusVectorEngine(mock=True, collection="memoryhub", dimension=768)
        engine.insert("mem_001", "文本", [0.1] * 768)
        results = engine.hybrid_search([0.1] * 768, build_sparse_vector("查询"), 5)
        engine.close()
    """

    def __init__(
        self,
        so_path: Optional[str] = None,
        mock: bool = False,
        host: str = "127.0.0.1",
        port: int = 19530,
        collection: str = "memoryhub",
        dimension: int = 768,
        connect: bool = True,
    ):
        """
        参数:
            so_path: 动态库显式路径；mock=True 时默认指向项目内 mock 库
            mock: 是否使用项目内 mock 动态库（非麒麟环境测试用）
            host: Milvus 服务地址
            port: Milvus 服务端口
            collection: 集合名
            dimension: 稠密向量维度
            connect: 是否在构造时完成 connect + collection 准备；
                False 时仅加载库并创建句柄（由调用方自行 connect）
        """
        self._api = _MilvusCAPI(so_path=so_path, mock=mock)
        self._handle: Optional[vector_engine_t] = self._api.create()
        self.collection = collection
        self.dimension = dimension
        self._connected = False
        self._closed = False

        if connect:
            try:
                self.connect(host, port)
            except Exception:
                self.close()
                raise

    # ---- 连接与 collection 准备 ----

    def connect(self, host: str, port: int) -> None:
        """连接 Milvus 服务，并确保 collection 已创建且加载到内存。"""
        self._ensure_open()
        self._api.connect(self._handle, host, port)
        self._connected = True
        try:
            self._api.create_collection(self._handle, self.collection, self.dimension)
        except MilvusEngineError as exc:
            # C API 没有 has_collection，create 报"已存在"则视为正常
            if "already exists" not in str(exc):
                raise
        self._api.load_collection(self._handle, self.collection)

    # ---- BaseVectorEngine 接口 ----

    def insert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """插入一条记忆（稀疏向量由 C 侧根据 text 生成）。metadata 暂由业务层存储。"""
        self._ensure_open()
        if len(vector) != self.dimension:
            raise ValueError(
                f"向量维度不一致: 期望 {self.dimension}, 实际 {len(vector)}"
            )
        self._api.insert(self._handle, self.collection, memory_id, text, vector)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """稠密向量检索。filters 暂未支持（保留参数）。"""
        self._ensure_open()
        self._check_dimension(query_vector)
        payload = json.loads(self._api.dense_search(self._handle, self.collection, query_vector, top_k))
        return self._parse_results(payload)

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
    ) -> list[VectorSearchResult]:
        """混合检索（稠密 + 稀疏，C 侧 RRF 融合）。"""
        self._ensure_open()
        self._check_dimension(dense_vector)
        payload = json.loads(
            self._api.hybrid_search(self._handle, self.collection, dense_vector, sparse_terms, top_k)
        )
        return self._parse_results(payload)

    def delete(self, memory_id: str) -> None:
        """删除一条记忆（删除不存在的 ID 不报错）。"""
        self._ensure_open()
        self._api.delete(self._handle, self.collection, memory_id)

    def persist(self) -> None:
        """Milvus 服务端自行持久化，本方法为 no-op（保留接口）。"""
        return None

    def close(self) -> None:
        """释放资源：release collection → disconnect → destroy。幂等。"""
        if self._closed:
            return
        self._closed = True
        handle, self._handle = self._handle, None
        if not handle:
            return
        # 关闭路径尽力而为，不让清理异常掩盖原始错误
        try:
            if self._connected:
                try:
                    self._api.release_collection(handle, self.collection)
                except MilvusEngineError:
                    pass
                try:
                    self._api.disconnect(handle)
                except MilvusEngineError:
                    pass
        finally:
            self._connected = False
            self._api.destroy(handle)

    def __del__(self):
        # 析构兜底，防止漏调 close 导致 C 侧资源泄漏
        try:
            self.close()
        except Exception:
            pass

    # ---- 内部 ----

    def _ensure_open(self) -> None:
        if self._closed or not self._handle:
            raise MilvusEngineError("向量引擎已关闭")

    def _check_dimension(self, vector: list[float]) -> None:
        if len(vector) != self.dimension:
            raise ValueError(
                f"向量维度不一致: 期望 {self.dimension}, 实际 {len(vector)}"
            )

    @staticmethod
    def _parse_results(payload: dict) -> list[VectorSearchResult]:
        """把 C 侧 JSON 解析为 VectorSearchResult 列表。"""
        return [
            VectorSearchResult(
                memory_id=item.get("memory_id", ""),
                content=item.get("content", ""),
                score=float(item.get("score", 0.0)),
                source=item.get("source", ""),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("results", [])
        ]
