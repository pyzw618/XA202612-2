"""
Milvus 向量引擎实现。

通过 ctypes 桥接（_milvus_ctypes.py）调用
libkysdk-vector-engine-client-capi（或项目内 mock 动态库），
实现 BaseVectorEngine 接口。稀疏向量由 C 侧在 insert 时根据
content 生成；查询侧稀疏向量由调用方用 sparse.build_sparse_vector
生成后传入 hybrid_search。
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Optional

from memoryhub.storage.vector_engine._milvus_ctypes import (
    MilvusEngineError,
    _MilvusCAPI,
    vector_engine_t,
)
from memoryhub.storage.vector_engine.base import BaseVectorEngine, VectorSearchResult

logger = logging.getLogger(__name__)

# 生产环境固定维度
_PRODUCTION_DIMENSION = 768


class MilvusVectorEngine(BaseVectorEngine):
    """
    Milvus 向量引擎（基于麒麟 C API SDK）。

    使用方式:
        engine = MilvusVectorEngine(
            app_id="test-app-id", mock=True, collection="memoryhub", dimension=768
        )
        engine.insert("mem_001", "文本", [0.1] * 768)
        results = engine.hybrid_search([0.1] * 768, build_sparse_vector("查询"), 5)
        engine.close()
    """

    def __init__(
        self,
        app_id: str = "",
        so_path: Optional[str] = None,
        mock: bool = False,
        host: str = "127.0.0.1",
        port: int = 19530,
        collection: str = "memoryhub",
        dimension: int = 768,
        connect: bool = True,
        search_timeout_ms: int = 120,
    ):
        """
        参数:
            so_path: 动态库显式路径；mock=True 时默认指向项目内 mock 库
            app_id: 部署平台提供的非空应用标识
            mock: 是否使用项目内 mock 动态库（非麒麟环境测试用）
            host: Milvus 服务地址
            port: Milvus 服务端口
            collection: 集合名
            dimension: 稠密向量维度；生产环境固定为 768
            connect: 是否在构造时完成 connect + collection 准备；
                False 时仅加载库并创建句柄（由调用方自行 connect）
            search_timeout_ms: 查询超时毫秒数；超时时返回稳定错误码 milvus.timeout
        """
        self._validate_app_id(app_id)
        self._validate_dimension(dimension)
        self._app_id = app_id
        self._api = _MilvusCAPI(so_path=so_path, mock=mock)
        self._handle: Optional[vector_engine_t] = self._api.create()
        self.collection = collection
        self.dimension = dimension
        self._connected = False
        self._closed = False
        self.search_timeout_ms = max(0, search_timeout_ms)

        # 内存中的 scalar fields 映射：memory_id -> metadata。
        # 当前 C API 不直接暴露 scalar 字段接口，因此由 Python 层维护，
        # 供 hybrid_search 的 filters 做后过滤；后续 C API 支持 scalar 字段后，
        # 可改为从 Milvus 返回结果直接读取。
        self._metadata_store: dict[str, dict[str, Any]] = {}

        # C API 会话不一定是线程安全的，且不支持中断阻塞调用。
        # 使用单线程执行器串行化所有 C API 操作，并通过 future.result(timeout)
        # 实现超时检测（无法真正终止 C 侧线程，但可返回稳定超时错误）。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="milvus_engine")
        self._executor_shutdown = False

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

        def _connect():
            self._api.connect(self._handle, self._app_id, host, port)
            self._connected = True
            try:
                self._api.create_collection(self._handle, self.collection, self.dimension)
            except MilvusEngineError as exc:
                # C API 没有 has_collection，create 报"已存在"则视为正常
                if "already exists" not in str(exc):
                    raise
            self._api.load_collection(self._handle, self.collection)

        self._run_with_timeout(_connect, "connect", timeout_ms=30000)

    # ---- BaseVectorEngine 接口 ----

    def insert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """插入一条记忆（稀疏向量由 C 侧根据 text 生成）。metadata 暂存于内存中。"""
        self._ensure_open()
        if len(vector) != self.dimension:
            raise ValueError(
                f"向量维度不一致: 期望 {self.dimension}, 实际 {len(vector)}"
            )
        if metadata is not None:
            self._metadata_store[memory_id] = dict(metadata)
        self._run_with_timeout(
            lambda: self._api.insert(self._handle, self.collection, memory_id, text, vector),
            "insert",
            timeout_ms=30000,
        )

    def upsert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """插入或更新单条记忆；语义与 insert 相同（Milvus ID 主键幂等）。"""
        self.insert(memory_id, text, vector, metadata=metadata)

    def upsert_batch(
        self,
        items: list[tuple[str, str, list[float], Optional[dict[str, Any]]]],
    ) -> list[str]:
        """
        批量 upsert。

        参数:
            items: [(memory_id, text, vector, metadata?), ...]

        返回:
            失败项的 memory_id 列表；调用方应将这些记录标记为 pending_index
        """
        self._ensure_open()
        failed: list[str] = []
        for memory_id, text, vector, metadata in items:
            try:
                self.upsert(memory_id, text, vector, metadata=metadata)
            except MilvusEngineError as exc:
                logger.warning("milvus upsert_batch item failed: %s: %s", memory_id, exc)
                failed.append(memory_id)
        return failed

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """稠密向量检索。filters 暂未支持（保留参数）。"""
        self._ensure_open()
        self._check_dimension(query_vector)

        def _search():
            return json.loads(
                self._api.dense_search(
                    self._handle, self.collection, query_vector, top_k
                )
            )

        payload = self._run_with_timeout(
            _search, "dense_search", timeout_ms=self.search_timeout_ms
        )
        return self._parse_results(payload)

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """混合检索（稠密 + 稀疏，C 侧 RRF 融合）。

        参数:
            filters: 可选 scalar 过滤条件，例如
                {"memory_type": "knowledge", "status": "active"}。
                当前由 Python 层对搜索结果做后过滤；C API 支持 scalar 字段后
                可下推到 Milvus。
        """
        self._ensure_open()
        self._check_dimension(dense_vector)

        def _search():
            return json.loads(
                self._api.hybrid_search(
                    self._handle, self.collection, dense_vector, sparse_terms, top_k
                )
            )

        payload = self._run_with_timeout(
            _search, "hybrid_search", timeout_ms=self.search_timeout_ms
        )
        results = self._parse_results(payload)
        if filters:
            results = self._apply_filters(results, filters)
        return results

    def delete(self, memory_id: str) -> None:
        """删除一条记忆（删除不存在的 ID 不报错）。"""
        self._ensure_open()

        def _delete():
            self._api.delete(self._handle, self.collection, memory_id)

        self._run_with_timeout(_delete, "delete", timeout_ms=30000)
        self._metadata_store.pop(memory_id, None)

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

        # 关闭执行器，不再接受新任务；已经运行的尽力等待
        if not self._executor_shutdown:
            self._executor_shutdown = True
            self._executor.shutdown(wait=False, cancel_futures=True)

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
    def _validate_app_id(app_id: str) -> None:
        """在动态库加载前拒绝缺失的 Milvus 应用标识。"""
        if not isinstance(app_id, str) or not app_id.strip():
            raise MilvusEngineError("milvus.app_id must be a non-empty string")

    @staticmethod
    def _validate_dimension(dimension: int) -> None:
        """生产 schema 要求维度固定为 768。"""
        if dimension != _PRODUCTION_DIMENSION:
            raise MilvusEngineError(
                f"milvus.schema_dimension_mismatch: 期望 {_PRODUCTION_DIMENSION}, 实际 {dimension}"
            )

    def _run_with_timeout(self, fn, operation: str, timeout_ms: int):
        """在单线程执行器中运行 C API 调用，并施加超时。

        注意：ctypes 无法真正中断已阻塞的 C 调用，超时返回后原线程可能
        仍在后台执行。生产部署应依赖 SDK 原生超时或异步 API。
        """
        if self._closed or self._executor_shutdown:
            raise MilvusEngineError("向量引擎已关闭")
        if timeout_ms <= 0:
            timeout_ms = 1
        try:
            future = self._executor.submit(fn)
            return future.result(timeout=timeout_ms / 1000.0)
        except TimeoutError:
            logger.warning(
                "milvus_timeout_alert: %s",
                {
                    "operation": operation,
                    "timeout_ms": timeout_ms,
                    "code": "milvus.timeout",
                },
            )
            raise MilvusEngineError(f"milvus.timeout: {operation} 超过 {timeout_ms}ms") from None
        except MilvusEngineError:
            raise
        except Exception as exc:
            raise MilvusEngineError(f"milvus.call_failed: {operation} 失败: {exc}") from None

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

    def _apply_filters(
        self, results: list[VectorSearchResult], filters: dict[str, Any]
    ) -> list[VectorSearchResult]:
        """用内存中的 scalar fields 对搜索结果做后过滤。"""
        filtered = []
        for result in results:
            meta = self._metadata_store.get(result.memory_id, {})
            # 合并 C 侧返回的 metadata（如果有）
            meta = {**meta, **dict(result.metadata)}
            if all(meta.get(key) == value for key, value in filters.items()):
                filtered.append(result)
        return filtered
