"""
Search Engine — BM25 + FAISS 双路检索引擎。

- BM25: 基于分词匹配的全文检索，擅长精确关键词匹配
- FAISS: 基于语义向量的近似检索，擅长语义相似度搜索

两者可以独立使用，也可以混合（Hybrid）打分。
"""

import numpy as np
from typing import List, Tuple, Optional

try:
    import faiss
except ImportError:
    faiss = None

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

try:
    from .memory_store import MemoryStore, MemoryRecord
except ImportError:
    from memory_store import MemoryStore, MemoryRecord


# ---------- 简易中文分词 ----------

def _simple_tokenize(text: str) -> List[str]:
    """
    简易分词：按非字母数字字符切分 + 单字拆开（中文场景）。
    生产环境建议替换为 jieba 分词。
    """
    import re
    # 先按空白/标点切分
    tokens = re.findall(r'[一-鿿]|[a-zA-Z0-9]+', text.lower())
    return tokens


# ---------- BM25 检索器 ----------

class BM25Retriever:
    """
    BM25 全文检索器。

    对记忆库中所有文本建立倒排索引，查询时返回 BM25 打分排序结果。
    """

    def __init__(self, tokenizer=_simple_tokenize):
        self._tokenizer = tokenizer
        self._bm25 = None
        self._corpus: List[str] = []
        self._tokenized_corpus: List[List[str]] = []

    def index(self, texts: List[str]):
        """基于文本列表构建 BM25 索引。"""
        self._corpus = list(texts)
        self._tokenized_corpus = [self._tokenizer(t) for t in texts]
        if BM25Okapi is None:
            raise ImportError("rank-bm25 未安装，请执行: pip install rank-bm25")
        self._bm25 = BM25Okapi(self._tokenized_corpus)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        """
        搜索并返回 [(corpus_index, score), ...]，按分数降序。
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 索引未构建，请先调用 index()")
        tokenized_query = self._tokenizer(query)
        scores = self._bm25.get_scores(tokenized_query)
        # 按分数排序取 top_k
        if top_k >= len(scores):
            top_indices = list(range(len(scores)))
        else:
            top_indices = np.argsort(scores)[::-1][:top_k]
        return [(int(i), float(scores[i])) for i in top_indices]

    @property
    def is_ready(self) -> bool:
        return self._bm25 is not None


# ---------- FAISS 检索器 ----------

class FaissRetriever:
    """
    FAISS 向量检索器。

    使用内积索引（IndexFlatIP），适合 Embedding 向量相似度搜索。
    L2 归一化后内积等价于余弦相似度。
    """

    def __init__(self, dim: int = 768):
        self.dim = dim
        self._index = None
        self._id_to_idx: dict = {}   # record_id → faiss 内部序号
        self._idx_to_id: dict = {}   # faiss 内部序号 → record_id

    def index(self, records: List[MemoryRecord]):
        """
        用带 Embedding 的记录构建 FAISS 索引。
        自动做 L2 归一化，使内积等价于余弦相似度。
        """
        if faiss is None:
            raise ImportError("faiss-cpu 未安装，请执行: pip install faiss-cpu")

        vectors = []
        valid_records = []

        for r in records:
            if r.embedding is not None and len(r.embedding) == self.dim:
                vectors.append(r.embedding)
                valid_records.append(r)

        if not vectors:
            raise ValueError("没有可用的向量数据，请先为记录生成 Embedding")

        np_vectors = np.array(vectors, dtype=np.float32)
        # L2 归一化 → 内积 = 余弦相似度
        faiss.normalize_L2(np_vectors)

        self._index = faiss.IndexFlatIP(self.dim)  # Inner Product
        self._index.add(np_vectors)

        # 建立双向映射
        self._id_to_idx = {}
        self._idx_to_id = {}
        for idx, r in enumerate(valid_records):
            self._id_to_idx[r.id] = idx
            self._idx_to_id[idx] = r.id

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        """
        用查询向量搜索，返回 [(record_id, similarity_score), ...]。
        score 范围 [-1, 1]，越接近 1 越相似。
        """
        if self._index is None:
            raise RuntimeError("FAISS 索引未构建，请先调用 index()")

        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)

        distances, indices = self._index.search(q, min(top_k, self._index.ntotal))
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx in self._idx_to_id:
                results.append((self._idx_to_id[idx], float(dist)))
        return results

    @property
    def is_ready(self) -> bool:
        return self._index is not None


# ---------- 统一搜索入口 ----------

class MemorySearchEngine:
    """
    统一搜索入口，整合 BM25 和 FAISS 双路检索。

    用法:
        store = MemoryStore()
        engine = MemorySearchEngine(store)
        engine.build_index()                    # 建立双路索引
        results = engine.search("系统密码")      # 默认 Hybrid 模式
    """

    def __init__(self, store: MemoryStore, embedding_dim: int = 768):
        self.store = store
        self.bm25 = BM25Retriever()
        self.faiss = FaissRetriever(dim=embedding_dim)

    def build_index(self):
        """根据 store 中的数据重新构建 BM25 和 FAISS 索引。"""
        records = self.store.get_all()

        # BM25 索引
        texts = [r.content for r in records]
        self.bm25.index(texts)

        # FAISS 索引
        self.faiss.index(records)

    def search_bm25(self, query: str, top_k: int = 5) -> List[dict]:
        """纯 BM25 关键词搜索。"""
        records = self.store.get_all()
        hits = self.bm25.search(query, top_k=top_k)
        return [
            {
                "record_id": records[idx].id,
                "content": records[idx].content,
                "score": round(score, 4),
                "method": "bm25",
            }
            for idx, score in hits
        ]

    def search_faiss(
        self,
        query_text: str,
        query_vector: List[float],
        top_k: int = 5,
    ) -> List[dict]:
        """纯 FAISS 语义向量搜索。"""
        hits = self.faiss.search(query_vector, top_k=top_k)
        results = []
        for rid, score in hits:
            record = self.store.get_by_id(rid)
            if record:
                results.append({
                    "record_id": rid,
                    "content": record.content,
                    "score": round(score, 4),
                    "method": "faiss",
                })
        return results

    def search_hybrid(
        self,
        query_text: str,
        query_vector: List[float],
        top_k: int = 5,
        bm25_weight: float = 0.3,
        faiss_weight: float = 0.7,
    ) -> List[dict]:
        """
        混合检索：BM25 关键词 + FAISS 语义，加权融合排序。

        Args:
            bm25_weight: BM25 分数权重（默认 0.3）
            faiss_weight: FAISS 分数权重（默认 0.7）
        """
        # BM25 结果
        bm25_hits = self.bm25.search(query_text, top_k=len(self.store))
        # FAISS 结果
        faiss_hits = self.faiss.search(query_vector, top_k=len(self.store))

        # 将 BM25 分数归一化到 [0, 1]
        records = self.store.get_all()
        bm25_map: dict = {}
        bm25_raw = [s for _, s in bm25_hits]
        bm25_max = max(bm25_raw) if bm25_raw else 1.0
        bm25_min = min(bm25_raw) if bm25_raw else 0.0
        for idx, score in bm25_hits:
            rid = records[idx].id
            if bm25_max > bm25_min:
                bm25_map[rid] = (score - bm25_min) / (bm25_max - bm25_min)
            else:
                bm25_map[rid] = 0.5

        # FAISS 分数（已经是 cosine similarity in [-1,1]，映射到 [0,1]）
        faiss_map: dict = {}
        for rid, score in faiss_hits:
            faiss_map[rid] = (score + 1.0) / 2.0  # [-1,1] → [0,1]

        # 加权融合
        all_ids = set(bm25_map.keys()) | set(faiss_map.keys())
        fused = []
        for rid in all_ids:
            b = bm25_map.get(rid, 0.0)
            f = faiss_map.get(rid, 0.0)
            fused_score = bm25_weight * b + faiss_weight * f
            fused.append((rid, fused_score))

        fused.sort(key=lambda x: x[1], reverse=True)
        top = fused[:top_k]

        results = []
        for rid, score in top:
            record = self.store.get_by_id(rid)
            if record:
                results.append({
                    "record_id": rid,
                    "content": record.content,
                    "score": round(score, 4),
                    "method": "hybrid",
                })
        return results
