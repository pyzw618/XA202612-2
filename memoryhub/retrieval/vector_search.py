"""
向量检索模块

基于 FAISS 的语义向量检索。
"""

from memoryhub.adapter.schemas import SearchResult


class VectorSearcher:
    """
    FAISS 向量检索器

    使用方式:
        searcher = VectorSearcher(index_path="data/vector_index")
        results = searcher.search(query_vector, top_k=5)
    """

    def __init__(self, index_path: str = "", dimension: int = 1024):
        """
        参数:
            index_path: FAISS 索引文件路径
            dimension: 向量维度
        """
        self.index_path = index_path
        self.dimension = dimension
        self.index = None
        self.id_map: dict[int, str] = {}  # FAISS 内部 ID → memory_id

    def load_index(self) -> None:
        """加载 FAISS 索引"""
        raise NotImplementedError

    def save_index(self) -> None:
        """保存 FAISS 索引到磁盘"""
        raise NotImplementedError

    def add(self, memory_id: str, vector: list[float]) -> None:
        """
        添加向量到索引

        数据流: 新记忆写入 → embedding → add → FAISS 索引

        参数:
            memory_id: 记忆 ID
            vector: embedding 向量
        """
        raise NotImplementedError

    def batch_add(self, items: list[tuple[str, list[float]]]) -> None:
        """批量添加向量"""
        raise NotImplementedError

    def search(self, query_vector: list[float], top_k: int = 5) -> list[SearchResult]:
        """
        向量检索

        数据流:
            query_vector → FAISS search → 返回 top_k 最近邻

        参数:
            query_vector: 查询向量
            top_k: 返回数量

        返回:
            SearchResult 列表（score 为相似度分数）
        """
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        """
        删除向量

        注意: FAISS 原生不支持高效删除，可使用 IDMap 或定期重建索引

        返回:
            是否成功
        """
        raise NotImplementedError

    def batch_delete(self, memory_ids: list[str]) -> int:
        """批量删除向量，返回成功删除数量"""
        raise NotImplementedError

    def rebuild_index(self) -> None:
        """重建索引（清理已删除的向量）"""
        raise NotImplementedError

    def size(self) -> int:
        """返回索引中的向量数量"""
        raise NotImplementedError
