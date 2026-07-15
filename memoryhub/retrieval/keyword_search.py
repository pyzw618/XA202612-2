"""
关键词检索模块

基于 BM25 的关键词检索。
"""

from memoryhub.adapter.schemas import SearchResult


class KeywordSearcher:
    """
    BM25 关键词检索器

    使用方式:
        searcher = KeywordSearcher()
        results = searcher.search("项目周报", top_k=5)
    """

    def __init__(self):
        self.index = None  # BM25 索引
        self.doc_map: dict[int, str] = {}  # 内部 doc_id → memory_id

    def build_index(self, documents: list[tuple[str, str, str]]) -> None:
        """
        构建 BM25 索引

        参数:
            documents: [(memory_id, content, metadata_json), ...]

        数据流:
            存储中的所有记忆 → build_index → BM25 索引
        """
        raise NotImplementedError

    def add_document(self, memory_id: str, content: str, metadata: str = "") -> None:
        """添加单条文档到索引"""
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        关键词检索

        数据流:
            query → 分词 → BM25 打分 → 返回 top_k

        参数:
            query: 查询文本
            top_k: 返回数量

        返回:
            SearchResult 列表（score 为 BM25 分数）
        """
        raise NotImplementedError

    def delete(self, memory_id: str) -> bool:
        """删除文档"""
        raise NotImplementedError

    def update(self, memory_id: str, content: str, metadata: str = "") -> None:
        """更新文档"""
        raise NotImplementedError
