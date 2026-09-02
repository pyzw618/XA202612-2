"""
FAISS 向量存储管理

管理 FAISS 索引的创建、持久化和 CRUD。

注意：FAISS 仅允许在 development、test 环境或显式启用的故障诊断场景中使用；
生产模式（runtime.mode=production）下不可将其作为向量索引事实来源。
"""

import json
import logging
import os
from pathlib import Path

import numpy as np

try:
    import faiss
except ImportError:
    faiss = None

logger = logging.getLogger(__name__)


class VectorStore:
    """
    FAISS 向量存储管理器 — development/test 环境的向量索引实现。

    检索层的 VectorSearcher 从本类加载索引，不自行持久化。

    使用方式:
        store = VectorStore("data/vector_index", dimension=1024)
        store.init_index()
        store.add("mem_001", [0.1, 0.2, ...])
        results = store.search([0.1, 0.2, ...], top_k=5)

    注意:
        本类仅用于 development/test 或显式诊断场景；生产环境请使用
        MilvusVectorEngine。
    """

    def __init__(self, index_path: str = "data/vector_index", dimension: int = 1024):
        from memoryhub.config import is_production_mode

        if is_production_mode():
            logger.warning(
                "faiss_vector_store_initialized_in_production: "
                "FAISS is not a production backend; use Milvus instead"
            )
        self.index_path = Path(index_path)
        self.dimension = dimension
        self.index = None
        self.id_map: dict[int, str] = {}       # faiss 内部序号 → memory_id
        self.reverse_map: dict[str, int] = {}   # memory_id → faiss 内部序号
        self._removed_ids: set[str] = set()     # 已删除的 memory_id，搜索时过滤
        self._next_id: int = 0

    # ---- 索引生命周期 ----

    def init_index(self, index_type: str = "flat") -> None:
        """
        初始化 FAISS 索引。

        先尝试从磁盘加载已有索引，失败则创建新的。

        参数:
            index_type: "flat" | "ivf" | "hnsw"
        """
        if faiss is None:
            raise ImportError("faiss-cpu 未安装，请执行: pip install faiss-cpu")

        # 1. 尝试加载已有索引
        if self.load():
            return

        # 2. 创建新索引
        if index_type == "flat":
            self.index = faiss.IndexFlatIP(self.dimension)
        elif index_type == "ivf":
            quantizer = faiss.IndexFlatIP(self.dimension)
            nlist = min(100, max(4, 16))  # 聚类中心数
            self.index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)
            self.index.train(np.zeros((1, self.dimension), dtype=np.float32))
        elif index_type == "hnsw":
            self.index = faiss.IndexHNSWFlat(self.dimension, 32)
        else:
            raise ValueError(f"不支持的索引类型: {index_type}")

    # ---- CRUD ----

    def add(self, memory_id: str, vector: list[float]) -> None:
        """
        添加单条向量。

        参数:
            memory_id: 记忆 ID
            vector: embedding 向量
        """
        if self.index is None:
            raise RuntimeError("索引未初始化，请先调用 init_index()")

        if len(vector) != self.dimension:
            raise ValueError(f"向量维度 {len(vector)} 不匹配，期望 {self.dimension}")

        arr = np.array([vector], dtype=np.float32)
        faiss.normalize_L2(arr)

        idx = self._next_id
        self.index.add(arr)
        self.id_map[idx] = memory_id
        self.reverse_map[memory_id] = idx
        self._next_id += 1

    def update(self, memory_id: str, vector: list[float]) -> None:
        """Upsert one vector without leaving a stale same-ID vector searchable."""
        if memory_id in self.reverse_map:
            self._removed_ids.add(memory_id)
            self.rebuild_index()
        self.add(memory_id, vector)

    def batch_add(self, items: list[tuple[str, list[float]]]) -> None:
        """
        批量添加向量。

        参数:
            items: [(memory_id, vector), ...]
        """
        if not items:
            return

        ids = []
        vectors = []
        for memory_id, vec in items:
            if len(vec) != self.dimension:
                raise ValueError(f"向量 {memory_id} 维度 {len(vec)} 不匹配")
            ids.append(memory_id)
            vectors.append(vec)

        arr = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(arr)

        start = self._next_id
        self.index.add(arr)
        for i, memory_id in enumerate(ids):
            idx = start + i
            self.id_map[idx] = memory_id
            self.reverse_map[memory_id] = idx
        self._next_id = start + len(ids)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        """
        向量检索。

        参数:
            query_vector: 查询向量
            top_k: 返回数量

        返回:
            [(memory_id, similarity_score), ...]
        """
        if self.index is None:
            raise RuntimeError("索引未初始化，请先调用 init_index()")
        if self.index.ntotal == 0:
            return []

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)

        # 多取一些应对过滤
        fetch_k = min(top_k + len(self._removed_ids) + 5, self.index.ntotal)
        distances, indices = self.index.search(q, fetch_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            rid = self.id_map.get(int(idx))
            if rid and rid not in self._removed_ids:
                results.append((rid, float(dist)))
            if len(results) >= top_k:
                break
        return results

    def delete(self, memory_id: str) -> bool:
        """
        删除向量（标记删除，搜索时过滤）。

        返回:
            是否成功
        """
        if memory_id not in self.reverse_map:
            return False
        self._removed_ids.add(memory_id)
        return True

    def batch_delete(self, memory_ids: list[str]) -> int:
        """批量删除，返回成功数量。"""
        count = 0
        for mid in memory_ids:
            if self.delete(mid):
                count += 1
        return count

    # ---- 维护 ----

    def rebuild_index(self) -> None:
        """
        重建索引，物理清除已删除的向量。

        当 _removed_ids 积累较多时调用，释放磁盘空间。
        """
        if self.index is None:
            return

        # 收集有效向量
        valid_items = []
        for idx in range(self._next_id):
            rid = self.id_map.get(idx)
            if rid and rid not in self._removed_ids:
                # 从当前索引中取出向量
                vec = self.index.reconstruct(idx)
                valid_items.append((rid, vec.tolist()))

        # 重新构建
        self.index = faiss.IndexFlatIP(self.dimension)
        self.id_map = {}
        self.reverse_map = {}
        self._removed_ids = set()
        self._next_id = 0

        if valid_items:
            ids, vectors = zip(*valid_items)
            arr = np.array(vectors, dtype=np.float32)
            faiss.normalize_L2(arr)
            self.index.add(arr)
            for i, rid in enumerate(ids):
                self.id_map[i] = rid
                self.reverse_map[rid] = i
            self._next_id = len(ids)

    def size(self) -> int:
        """返回有效向量数量（扣除已删除）。"""
        if self.index is None:
            return 0
        return self.index.ntotal - len(self._removed_ids)

    # ---- 持久化 ----

    def save(self) -> None:
        """持久化索引和映射到磁盘。"""
        if self.index is None:
            return

        os.makedirs(self.index_path.parent, exist_ok=True)

        # 保存 FAISS 索引
        index_file = str(self.index_path) + ".faiss"
        faiss.write_index(self.index, index_file)

        # 保存映射和元数据
        meta = {
            "dimension": self.dimension,
            "next_id": self._next_id,
            "id_map": {str(k): v for k, v in self.id_map.items()},
            "reverse_map": self.reverse_map,
            "removed_ids": list(self._removed_ids),
        }
        meta_file = str(self.index_path) + ".meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

    def load(self) -> bool:
        """
        从磁盘加载索引和映射。

        返回:
            True 表示加载成功，False 表示文件不存在或加载失败。
        """
        index_file = str(self.index_path) + ".faiss"
        meta_file = str(self.index_path) + ".meta.json"

        if not os.path.exists(index_file) or not os.path.exists(meta_file):
            return False

        try:
            self.index = faiss.read_index(index_file)

            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)

            loaded_dimension = meta.get("dimension")
            if loaded_dimension is not None and loaded_dimension != self.dimension:
                # Dimension mismatch: the configured embedding dimension has changed
                # (or a stale index from another configuration is present). Treat as
                # load failure so init_index builds a fresh index with the configured
                # dimension; stale vectors cannot be searched with a different model.
                logger.warning(
                    "vector_store dimension mismatch: configured=%s, loaded=%s; rebuilding",
                    self.dimension,
                    loaded_dimension,
                )
                self.index = None
                return False

            self.dimension = meta["dimension"]
            self._next_id = meta["next_id"]
            self.id_map = {int(k): v for k, v in meta["id_map"].items()}
            self.reverse_map = meta["reverse_map"]
            self._removed_ids = set(meta.get("removed_ids", []))

            return True
        except Exception:
            # 加载失败，重建
            self.index = None
            return False
