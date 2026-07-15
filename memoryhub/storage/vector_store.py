"""
FAISS 向量存储管理

管理 FAISS 索引的创建、持久化和 CRUD。
"""

from pathlib import Path


class VectorStore:
    """
    FAISS 向量存储管理器

    使用方式:
        store = VectorStore("data/vector_index", dimension=1024)
        store.init_index()
        store.add("mem_001", [0.1, 0.2, ...])
        results = store.search([0.1, 0.2, ...], top_k=5)
    """

    def __init__(self, index_path: str = "data/vector_index", dimension: int = 1024):
        """
        参数:
            index_path: 索引文件目录
            dimension: 向量维度（需与 embedding 模型一致）
        """
        self.index_path = Path(index_path)
        self.dimension = dimension
        self.index = None
        self.id_map: dict[int, str] = {}
        self.reverse_map: dict[str, int] = {}

    def init_index(self, index_type: str = "flat") -> None:
        """
        初始化 FAISS 索引

        参数:
            index_type: 索引类型
                - "flat": 暴力搜索（精确，适合小数据量 <10k）
                - "ivf": 倒排索引（适合中等数据量）
                - "hnsw": HNSW 图索引（适合大数据量，召回率高）

        数据流: 应用启动 → init_index → 加载已有索引或创建新索引
        """
        raise NotImplementedError

    def add(self, memory_id: str, vector: list[float]) -> None:
        """
        添加单条向量

        数据流: 新记忆 → embedding → add → FAISS 索引 + ID 映射

        参数:
            memory_id: 记忆 ID
            vector: embedding 向量
        """
        raise NotImplementedError

    def batch_add(self, items: list[tuple[str, list[float]]]) -> None:
        """
        批量添加向量

        参数:
            items: [(memory_id, vector), ...]
        """
        raise NotImplementedError

    def search(self, query_vector: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        """
        向量检索

        参数:
            query_vector: 查询向量
            top_k: 返回数量

        返回:
            [(memory_id, similarity_score), ...]
        """
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        """
        删除向量

        注意: FAISS IndexFlatL2 不支持高效删除，
        使用 IndexIDMap 或定期 rebuild_index 实现。

        返回:
            是否成功
        """
        raise NotImplementedError

    def batch_delete(self, memory_ids: list[str]) -> int:
        """批量删除，返回成功数量"""
        raise NotImplementedError

    def rebuild_index(self) -> None:
        """
        重建索引（清理已删除向量）

        数据流: 定期维护 → rebuild_index → 创建新索引 → 替换旧索引
        """
        raise NotImplementedError

    def save(self) -> None:
        """持久化索引到磁盘"""
        raise NotImplementedError

    def load(self) -> None:
        """从磁盘加载索引"""
        raise NotImplementedError

    def size(self) -> int:
        """返回索引中的向量数量"""
        raise NotImplementedError
