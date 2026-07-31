"""
向量检索模块

基于 FAISS 的语义向量检索。
"""

import json
import os

import numpy as np

from memoryhub.adapter.schemas import SearchResult

try:
    import faiss
except ImportError:
    faiss = None


class VectorSearcher:
    """
    FAISS 向量检索器

    使用内积索引（IndexFlatIP），L2 归一化后内积等价于余弦相似度。

    使用方式:
        searcher = VectorSearcher(index_path="data/vector_index", dimension=1024)
        searcher.add(memory_id, vector)
        results = searcher.search(query_vector, top_k=5)
    """

    def __init__(self, index_path: str = "", dimension: int = 1024):
        """
        参数:
            index_path: FAISS 索引文件路径（为空则仅内存索引）
            dimension: 向量维度
        """
        self.index_path = index_path
        self.dimension = dimension
        self.index = None
        self.id_map: dict[int, str] = {}  # FAISS 内部 ID → memory_id
        self.reverse_map: dict[str, int] = {}  # memory_id → FAISS 内部 ID
        self._removed_ids: set[str] = set()  # 已标记删除的 memory_id，搜索时过滤
        self._metadata: dict[str, dict] = {}  # memory_id → 附带元数据
        self._vectors: dict[str, list[float]] = {}  # memory_id → 原始向量（用于重建）

    def load_index(self) -> None:
        """从 index_path 加载 FAISS 索引及元数据"""
        if faiss is None:
            raise ImportError("faiss-cpu 未安装，请执行: pip install faiss-cpu")
        if not self.index_path or not os.path.exists(self.index_path):
            raise FileNotFoundError(f"索引文件不存在: {self.index_path}")

        self.index = faiss.read_index(self.index_path)
        meta_path = self.index_path + ".meta"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.dimension = meta["dimension"]
        self.id_map = {int(k): v for k, v in meta["id_map"].items()}
        self.reverse_map = {v: int(k) for k, v in meta["id_map"].items()}
        self._removed_ids = set(meta.get("removed_ids", []))
        self._metadata = meta.get("metadata", {})
        self._vectors = meta.get("vectors", {})

    def save_index(self) -> None:
        """保存 FAISS 索引和元数据到磁盘"""
        if faiss is None:
            raise ImportError("faiss-cpu 未安装，请执行: pip install faiss-cpu")
        if self.index is None:
            raise RuntimeError("索引未构建，无法保存")
        if not self.index_path:
            raise ValueError("未设置 index_path，无法保存")

        directory = os.path.dirname(self.index_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        faiss.write_index(self.index, self.index_path)
        meta_path = self.index_path + ".meta"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "dimension": self.dimension,
                    "id_map": {str(k): v for k, v in self.id_map.items()},
                    "removed_ids": sorted(self._removed_ids),
                    "metadata": self._metadata,
                    "vectors": self._vectors,
                },
                f,
            )

    def add(self, memory_id: str, vector: list[float], metadata: dict | None = None) -> None:
        """
        添加向量到索引

        数据流: 新记忆写入 → embedding → add → FAISS 索引

        参数:
            memory_id: 记忆 ID
            vector: embedding 向量
            metadata: 可选元数据（memory_type/scope/confidence 等），随检索结果返回
        """
        self._ensure_index()
        self._check_dimension(vector)

        if memory_id in self.reverse_map:
            # 重复添加视为更新：先标记删除旧向量，再追加新向量
            self._removed_ids.add(memory_id)

        np_vector = np.array([vector], dtype=np.float32)
        faiss.normalize_L2(np_vector)
        self.index.add(np_vector)

        internal_id = self.index.ntotal - 1
        self.id_map[internal_id] = memory_id
        self.reverse_map[memory_id] = internal_id
        self._removed_ids.discard(memory_id)
        self._vectors[memory_id] = list(vector)
        if metadata is not None:
            self._metadata[memory_id] = dict(metadata)

    def batch_add(self, items: list[tuple[str, list[float]]]) -> None:
        """批量添加向量"""
        for memory_id, vector in items:
            self.add(memory_id, vector)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[SearchResult]:
        """
        向量检索

        数据流:
            query_vector → FAISS search → 返回 top_k 最近邻

        参数:
            query_vector: 查询向量
            top_k: 返回数量

        返回:
            SearchResult 列表（score 为余弦相似度，范围 [-1, 1]）
        """
        if self.index is None or self.index.ntotal == 0:
            return []
        self._check_dimension(query_vector)

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)

        # 多取一些，补偿被删除标记过滤掉的条目
        fetch_k = min(top_k + len(self._removed_ids) + 5, self.index.ntotal)
        distances, indices = self.index.search(q, fetch_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx not in self.id_map:
                continue
            memory_id = self.id_map[idx]
            if memory_id in self._removed_ids:
                continue
            metadata = self._metadata.get(memory_id, {})
            results.append(
                SearchResult(
                    memory_id=memory_id,
                    memory_type=metadata.get("memory_type", ""),
                    content=metadata.get("content", ""),
                    score=float(dist),
                    source="vector",
                    metadata=dict(metadata),
                )
            )
            if len(results) >= top_k:
                break
        return results

    def delete(self, memory_id: str) -> bool:
        """
        删除向量（标记为 removed，搜索时过滤，不立即重建索引）

        返回:
            是否存在并成功标记删除
        """
        if memory_id not in self.reverse_map or memory_id in self._removed_ids:
            return False
        self._removed_ids.add(memory_id)
        self._vectors.pop(memory_id, None)
        self._metadata.pop(memory_id, None)
        return True

    def batch_delete(self, memory_ids: list[str]) -> int:
        """批量删除向量，返回成功删除数量"""
        return sum(1 for memory_id in memory_ids if self.delete(memory_id))

    def rebuild_index(self) -> None:
        """重建索引（清理已删除的向量）"""
        active = [
            (memory_id, vector)
            for memory_id, vector in self._vectors.items()
            if memory_id not in self._removed_ids
        ]
        self.index = None
        self.id_map = {}
        self.reverse_map = {}
        self._removed_ids = set()
        self._vectors = {}
        self.batch_add(active)

    def size(self) -> int:
        """返回索引中的有效向量数量（排除已删除）"""
        total = self.index.ntotal if self.index is not None else 0
        return total - len(self._removed_ids)

    # ---- 内部 ----

    def _ensure_index(self) -> None:
        if faiss is None:
            raise ImportError("faiss-cpu 未安装，请执行: pip install faiss-cpu")
        if self.index is None:
            self.index = faiss.IndexFlatIP(self.dimension)

    def _check_dimension(self, vector: list[float]) -> None:
        if len(vector) != self.dimension:
            raise ValueError(
                f"向量维度不一致: 期望 {self.dimension}, 实际 {len(vector)}"
            )
