"""
FAISS 向量引擎实现。

包装现有 memoryhub.storage.vector_store.VectorStore（不修改其代码），
实现 BaseVectorEngine 接口，作为 development/test 环境的 fallback 引擎。
hybrid_search 在 Python 层实现：dense 路走 FAISS，sparse 路对 insert
时保存的文本用 sparse.py 的稀疏向量做点积，两路 RRF 融合（k=60），
与 mock C 库行为对齐。

注意：FAISS 仅允许在 development、test 环境或显式启用的故障诊断场景中使用；
生产模式（runtime.mode=production）下该 provider 会被启动门禁拒绝。
"""

import json
import logging
import os
from typing import Any, Optional

from memoryhub.storage.vector_engine.base import BaseVectorEngine, VectorSearchResult
from memoryhub.storage.vector_engine.sparse import build_sparse_vector
from memoryhub.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

# RRF 融合常数，与 Milvus RRFRanker / mock C 库一致
_RRF_K = 60


class FAISSVectorEngine(BaseVectorEngine):
    """
    FAISS 向量引擎（包装现有 VectorStore）。

    使用方式:
        engine = FAISSVectorEngine(index_path="data/vector_index", dimension=1024)
        engine.insert("mem_001", "文本", [0.1] * 1024)
        results = engine.search([0.1] * 1024, top_k=5)
        engine.close()

    注意:
        本引擎仅用于 development/test 或显式诊断场景；生产环境请使用
        MilvusVectorEngine。
    """

    def __init__(self, index_path: str = "data/vector_index", dimension: int = 1024):
        """
        参数:
            index_path: FAISS 索引文件路径前缀（不含扩展名）
            dimension: 向量维度
        """
        from memoryhub.config import is_production_mode

        if is_production_mode():
            logger.warning(
                "faiss_vector_engine_initialized_in_production: "
                "provider=faiss is not allowed in production; "
                "use vector_engine.provider=milvus instead"
            )
        self._store = VectorStore(index_path=index_path, dimension=dimension)
        self._store.init_index()
        self._texts_path = str(index_path) + ".texts.json"
        self._texts: dict[str, str] = self._load_texts()
        self._closed = False

    # ---- BaseVectorEngine 接口 ----

    def insert(
        self,
        memory_id: str,
        text: str,
        vector: list[float],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """插入一条记忆。text 保存在内部字典中，供 hybrid_search 稀疏路使用。"""
        self._ensure_open()
        self._store.add(memory_id, vector)
        self._texts[memory_id] = text

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """稠密向量检索。filters 暂未支持（保留参数）。"""
        self._ensure_open()
        return [
            VectorSearchResult(
                memory_id=memory_id,
                content=self._texts.get(memory_id, ""),
                score=score,
                source="dense",
            )
            for memory_id, score in self._store.search(query_vector, top_k)
        ]

    def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_terms: list[tuple[int, float]],
        top_k: int,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """混合检索：dense 路 FAISS + sparse 路稀疏点积，RRF（k=60）融合。

        filters 参数保留以兼容接口；FAISS 引擎不在引擎层做过滤。
        """
        self._ensure_open()
        size = self._store.size()
        if size == 0:
            return []

        # dense 路：对所有有效向量排名，与 mock C 行为对齐
        dense_ranked = [
            memory_id
            for memory_id, _ in self._store.search(dense_vector, size)
        ]

        # sparse 路：对保存文本的稀疏向量做点积
        sparse_scores = []
        for memory_id, text in self._texts.items():
            if memory_id not in self._store.reverse_map:
                continue
            doc_terms = build_sparse_vector(text)
            sparse_scores.append((memory_id, _sparse_dot(sparse_terms, doc_terms)))
        sparse_scores.sort(key=lambda item: item[1], reverse=True)
        sparse_ranked = [memory_id for memory_id, _ in sparse_scores]

        # RRF 融合：score = sum(1 / (k + rank))，rank 从 1 开始
        fused: dict[str, float] = {}
        for rank, memory_id in enumerate(dense_ranked, start=1):
            fused[memory_id] = fused.get(memory_id, 0.0) + 1.0 / (_RRF_K + rank)
        for rank, memory_id in enumerate(sparse_ranked, start=1):
            fused[memory_id] = fused.get(memory_id, 0.0) + 1.0 / (_RRF_K + rank)

        top = sorted(fused.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            VectorSearchResult(
                memory_id=memory_id,
                content=self._texts.get(memory_id, ""),
                score=score,
                source="hybrid",
            )
            for memory_id, score in top
        ]

    def delete(self, memory_id: str) -> None:
        """删除一条记忆（不存在的 ID 不报错）。"""
        self._ensure_open()
        self._store.delete(memory_id)
        self._texts.pop(memory_id, None)

    def persist(self) -> None:
        """持久化 FAISS 索引和文本映射到磁盘。"""
        self._ensure_open()
        self._store.save()
        directory = os.path.dirname(self._texts_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self._texts_path, "w", encoding="utf-8") as f:
            json.dump(self._texts, f, ensure_ascii=False)

    def close(self) -> None:
        """持久化并关闭引擎。幂等。"""
        if self._closed:
            return
        self.persist()
        self._closed = True

    # ---- 内部 ----

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("向量引擎已关闭")

    def _load_texts(self) -> dict[str, str]:
        """加载持久化的文本映射（不存在时返回空）。"""
        if not os.path.exists(self._texts_path):
            return {}
        try:
            with open(self._texts_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _sparse_dot(
    a: list[tuple[int, float]], b: list[tuple[int, float]]
) -> float:
    """两个稀疏向量（已按索引排序）的点积。"""
    b_weights = dict(b)
    return sum(weight * b_weights[index] for index, weight in a if index in b_weights)
