"""
Search Engine — BM25 + FAISS 双路检索引擎。

- BM25: 基于分词匹配的全文检索，擅长精确关键词匹配
- FAISS: 基于语义向量的近似检索，擅长语义相似度搜索

两者可以独立使用，也可以混合（Hybrid）打分。
"""

import os
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


# ---------- 中文分词 ----------

try:
    import jieba
except ImportError:
    jieba = None


def _tokenize(text: str) -> List[str]:
    """
    中文分词：jieba 精确模式 + 英文/数字保留。

    例：
      "数据库登录密码" → ["数据库", "登录", "密码"]
      "我的系统密码是Admin@123" → ["系统", "密码", "Admin", "123"]
    """
    if jieba is None:
        # 降级：简易正则分词
        import re
        return re.findall(r'[一-鿿]|[a-zA-Z0-9]+', text.lower())

    # jieba 分词 + 过滤空字符和纯标点
    tokens = []
    for word in jieba.cut(text.lower()):
        word = word.strip()
        if word and not _is_punct_only(word):
            tokens.append(word)
    return tokens


def _is_punct_only(s: str) -> bool:
    """判断字符串是否仅由标点/空白构成。"""
    import re
    return not re.search(r'[a-zA-Z0-9一-鿿]', s)


# ---------- BM25 检索器 ----------

class BM25Retriever:
    """
    BM25 全文检索器。

    对记忆库中所有文本建立倒排索引，查询时返回 BM25 打分排序结果。
    """

    def __init__(self, tokenizer=_tokenize):
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
        if not texts:
            self._bm25 = None
            return
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


# ---------- FAISS 单集合引擎 ----------

class FaissRetriever:
    """
    FAISS 向量检索器 — 管理单个集合。

    使用内积索引（IndexFlatIP），L2 归一化后内积等价于余弦相似度。
    """

    def __init__(self, dim: int = 768, name: str = "default"):
        self.dim = dim
        self.name = name
        self._index = None
        self._id_to_idx: dict = {}
        self._idx_to_id: dict = {}
        self._removed_ids: set = set()  # 已删除的 record_id，搜索时过滤

    # ---- 构建 ----

    def index(self, records: List):
        """
        用带 Embedding 的记录构建索引。
        记录需有 .id 和 .embedding 属性。
        """
        if faiss is None:
            raise ImportError("faiss-cpu 未安装")

        vectors = []
        valid_records = []

        for r in records:
            if isinstance(r, dict):
                emb = r.get("embedding")
                rid = r.get("id", "")
            else:
                emb = getattr(r, "embedding", None)
                rid = getattr(r, "id", None) or getattr(r, "memory_id", None) or ""

            if emb is not None and len(emb) == self.dim:
                vectors.append(emb)
                valid_records.append((rid, emb))

        if not vectors:
            raise ValueError(f"集合 '{self.name}' 没有可用的向量数据")

        np_vectors = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(np_vectors)

        self._index = faiss.IndexFlatIP(self.dim)
        self._index.add(np_vectors)

        self._id_to_idx = {}
        self._idx_to_id = {}
        for idx, (rid, _) in enumerate(valid_records):
            self._id_to_idx[rid] = idx
            self._idx_to_id[idx] = rid

    def index_from_arrays(self, ids: List[str], vectors: List[List[float]]):
        """直接用 id 列表和向量列表构建索引（不需要 record 对象）。"""
        if faiss is None:
            raise ImportError("faiss-cpu 未安装")
        if not vectors:
            raise ValueError(f"集合 '{self.name}' 没有可用的向量数据")

        np_vectors = np.array(vectors, dtype=np.float32)
        faiss.normalize_L2(np_vectors)

        self._index = faiss.IndexFlatIP(self.dim)
        self._index.add(np_vectors)

        self._id_to_idx = {}
        self._idx_to_id = {}
        for idx, rid in enumerate(ids):
            self._id_to_idx[rid] = idx
            self._idx_to_id[idx] = rid

    # ---- 搜索 ----

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        if self._index is None:
            raise RuntimeError(f"集合 '{self.name}' 索引未构建")
        q = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(q)
        # 多取一些，应对过滤后不够 top_k 的情况
        fetch_k = min(top_k + len(self._removed_ids) + 5, self._index.ntotal)
        distances, indices = self._index.search(q, fetch_k)
        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx in self._idx_to_id:
                rid = self._idx_to_id[idx]
                if rid not in self._removed_ids:
                    results.append((rid, float(dist)))
            if len(results) >= top_k:
                break
        return results

    def remove(self, record_id: str):
        """将指定 ID 从搜索结果中排除（向量仍留索引中，搜索时过滤）。"""
        self._removed_ids.add(record_id)

    def remove_batch(self, record_ids: List[str]):
        """批量排除。"""
        self._removed_ids.update(record_ids)

    @property
    def active_count(self) -> int:
        """有效向量数（排除已删除）。"""
        return (self._index.ntotal if self._index else 0) - len(self._removed_ids)

    # ---- 持久化 ----

    def save(self, path: str):
        if self._index is None:
            raise RuntimeError(f"集合 '{self.name}' 索引未构建，无法保存")
        faiss.write_index(self._index, path)
        import json as _json
        meta_path = path + ".meta"
        with open(meta_path, "w", encoding="utf-8") as f:
            _json.dump({
                "name": self.name,
                "dim": self.dim,
                "id_to_idx": self._id_to_idx,
                "idx_to_id": {str(k): v for k, v in self._idx_to_id.items()},
            }, f)

    def load(self, path: str):
        if faiss is None:
            raise ImportError("faiss-cpu 未安装")
        self._index = faiss.read_index(path)
        import json as _json
        meta_path = path + ".meta"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = _json.load(f)
        self.name = meta.get("name", self.name)
        self.dim = meta["dim"]
        self._id_to_idx = meta["id_to_idx"]
        self._idx_to_id = {int(k): v for k, v in meta["idx_to_id"].items()}

    @property
    def is_ready(self) -> bool:
        return self._index is not None

    def __len__(self) -> int:
        return self._index.ntotal if self._index else 0


# ---------- FAISS 多集合管理器 ----------

class MultiCollectionFAISS:
    """
    管理多个 FAISS 集合（preferences / knowledge）。

    用法:
        mc = MultiCollectionFAISS(dim=768, index_dir="data/")
        mc.build("preferences", pref_rows)
        mc.build("knowledge", know_rows)
        mc.save_all()

        results = mc.search("preferences", query_vec, top_k=5)
        results = mc.search_all(query_vec, top_k=5)  # 跨集合搜索
    """

    def __init__(self, dim: int = 768, index_dir: str = ""):
        self.dim = dim
        self._index_dir = index_dir
        self._collections: dict[str, FaissRetriever] = {}

    # ---- 构建 ----

    def build(self, name: str, records: List):
        """为指定集合构建索引。"""
        retriever = FaissRetriever(dim=self.dim, name=name)
        retriever.index(records)
        self._collections[name] = retriever

    def build_from_arrays(self, name: str, ids: List[str], vectors: List[List[float]]):
        """用 id 和向量数组为指定集合构建索引。"""
        retriever = FaissRetriever(dim=self.dim, name=name)
        retriever.index_from_arrays(ids, vectors)
        self._collections[name] = retriever

    # ---- 搜索 ----

    def search(self, collection: str, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        """在指定集合中搜索。"""
        if collection not in self._collections:
            raise KeyError(f"集合 '{collection}' 不存在。可用: {list(self._collections.keys())}")
        return self._collections[collection].search(query_vector, top_k)

    def search_all(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        """
        跨所有集合搜索，返回融合结果。
        每个集合取 top_k 条，合并后按分数排序返回 top_k。
        """
        all_results = []
        for name, retriever in self._collections.items():
            try:
                hits = retriever.search(query_vector, top_k)
                all_results.extend(hits)
            except RuntimeError:
                continue
        all_results.sort(key=lambda x: x[1], reverse=True)
        return all_results[:top_k]

    # ---- 持久化 ----

    def save_all(self):
        """保存全部集合到磁盘。"""
        if not self._index_dir:
            return
        os.makedirs(self._index_dir, exist_ok=True)
        for name, retriever in self._collections.items():
            path = os.path.join(self._index_dir, f"faiss_{name}.index")
            retriever.save(path)

    def load_all(self) -> List[str]:
        """
        从磁盘加载所有已保存的集合。
        返回加载成功的集合名列表。
        """
        if not self._index_dir or not os.path.isdir(self._index_dir):
            return []

        loaded = []
        import glob
        for path in sorted(glob.glob(os.path.join(self._index_dir, "faiss_*.index"))):
            name = os.path.basename(path).replace("faiss_", "").replace(".index", "")
            retriever = FaissRetriever(dim=self.dim, name=name)
            try:
                retriever.load(path)
                self._collections[name] = retriever
                loaded.append(name)
            except Exception:
                pass
        return loaded

    # ---- 查询 ----

    def has(self, name: str) -> bool:
        return name in self._collections

    def list_collections(self) -> List[str]:
        return list(self._collections.keys())

    def get(self, name: str) -> Optional[FaissRetriever]:
        return self._collections.get(name)

    def remove(self, collection: str, record_id: str):
        """从指定集合中移除一条向量。"""
        if collection in self._collections:
            self._collections[collection].remove(record_id)

    @property
    def is_ready(self) -> bool:
        return len(self._collections) > 0


# ---------- 工具函数 ----------

def _attr(obj, name: str, default=""):
    """统一从对象属性或 dict key 中取值。"""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------- 统一搜索入口 ----------

class MemorySearchEngine:
    """
    统一搜索入口，整合 BM25 + 多集合 FAISS。

    支持两种模式:
      1. 单集合（向后兼容）: 传入 MemoryStore，所有记录一个索引
      2. 多集合（推荐）: 传入 PreferenceRepository + KnowledgeRepository

    用法:
        engine = MemorySearchEngine(store=memory_store)
        # 或
        engine = MemorySearchEngine(pref_repo=pref_repo, know_repo=know_repo)

        engine.build_index()
        engine.search_faiss("密码", query_vec, collection="preferences")
        engine.search_hybrid("密码", query_vec, collection="preferences")
    """

    def __init__(
        self,
        store=None,
        pref_repo=None,
        know_repo=None,
        embedding_dim: int = 768,
        index_dir: Optional[str] = None,
    ):
        self.store = store                           # 向后兼容
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.bm25 = BM25Retriever()

        if index_dir is None:
            from .memory_store import DEFAULT_DB_DIR
            index_dir = DEFAULT_DB_DIR
        self._index_dir = index_dir
        self._faiss_path = os.path.join(index_dir, "faiss.index")  # 旧路径兼容

        # 多集合 FAISS
        self.faiss = MultiCollectionFAISS(dim=embedding_dim, index_dir=index_dir)

    # ---- 构建索引 ----

    def build_index(self):
        """根据数据源重建全部索引并持久化。"""
        os.makedirs(self._index_dir, exist_ok=True)

        # ---- BM25: 合并所有文本 ----
        all_texts = []
        if self.store:
            all_texts.extend(r.content for r in self.store.get_all())
        if self.pref_repo:
            all_texts.extend(r.content for r in self.pref_repo.find_active())
        if self.know_repo:
            all_texts.extend(r.content for r in self.know_repo.find_active())
        self.bm25.index(all_texts)

        # ---- FAISS: 按集合分别建索引 ----
        if self.pref_repo:
            self._build_faiss_collection("preferences", self.pref_repo)
        if self.know_repo:
            self._build_faiss_collection("knowledge", self.know_repo)

        # 向后兼容：旧单集合模式
        if self.store and not self.pref_repo and not self.know_repo:
            records = self.store.get_all()
            if records:
                self.faiss.build("memories", records)

        self.faiss.save_all()

    def _build_faiss_collection(self, name: str, repo):
        """从 Repository 中提取向量并构建 FAISS 集合。"""
        import numpy as _np
        ids = []
        vectors = []
        for row in repo.find_active():
            if row.embedding is not None:
                emb = _np.frombuffer(row.embedding, dtype=_np.float32).tolist()
                ids.append(row.memory_id)
                vectors.append(emb)
        if ids:
            self.faiss.build_from_arrays(name, ids, vectors)

    def load_index(self) -> bool:
        """从磁盘加载已持久化的 FAISS 索引 + 重建 BM25。"""
        loaded = self.faiss.load_all()

        # 兼容旧格式
        if not loaded and os.path.exists(self._faiss_path):
            try:
                old = FaissRetriever(dim=self.faiss.dim, name="memories")
                old.load(self._faiss_path)
                self.faiss._collections["memories"] = old
                loaded = ["memories"]
            except Exception:
                pass

        # BM25 始终重建
        all_texts = []
        if self.store:
            all_texts.extend(r.content for r in self.store.get_all())
        if self.pref_repo:
            all_texts.extend(r.content for r in self.pref_repo.find_active())
        if self.know_repo:
            all_texts.extend(r.content for r in self.know_repo.find_active())
        self.bm25.index(all_texts)

        return len(loaded) > 0

    # ---- 搜索 ----

    def search_bm25(self, query: str, top_k: int = 5) -> List[dict]:
        """纯 BM25 关键词搜索。"""
        records = self._get_all_records()
        hits = self.bm25.search(query, top_k=top_k)
        return [
            {
                "record_id": _attr(records[idx], "id"),
                "content": _attr(records[idx], "content"),
                "score": round(score, 4),
                "method": "bm25",
            }
            for idx, score in hits
        ]

    def search_faiss(
        self,
        query_vector: List[float],
        top_k: int = 5,
        collection: str = "",
        **kwargs,  # 兼容旧版 query_text 参数
    ) -> List[dict]:
        """
        FAISS 向量搜索。
        collection: 指定集合名（如 "preferences", "knowledge"），空则跨所有集合搜索。
        """
        if collection and self.faiss.has(collection):
            hits = self.faiss.search(collection, query_vector, top_k)
        else:
            hits = self.faiss.search_all(query_vector, top_k)

        results = []
        for rid, score in hits:
            record = self._lookup_record(rid)
            if record:
                content = _attr(record, "content")
                results.append({
                    "record_id": rid,
                    "content": content,
                    "score": round(score, 4),
                    "method": "faiss",
                    "collection": collection or "all",
                })
        return results

    def search_hybrid(
        self,
        query_text: str,
        query_vector: List[float],
        top_k: int = 5,
        collection: str = "",
        bm25_weight: float = 0.3,
        faiss_weight: float = 0.7,
    ) -> List[dict]:
        """混合检索：BM25 + FAISS 加权融合。"""
        records = self._get_all_records()

        # BM25
        bm25_hits = self.bm25.search(query_text, top_k=len(records))

        # FAISS
        if collection and self.faiss.has(collection):
            faiss_hits = self.faiss.search(collection, query_vector, top_k=len(records))
        else:
            faiss_hits = self.faiss.search_all(query_vector, top_k=len(records))

        # 归一化 BM25
        bm25_map: dict = {}
        bm25_raw = [s for _, s in bm25_hits]
        bm25_max = max(bm25_raw) if bm25_raw else 1.0
        bm25_min = min(bm25_raw) if bm25_raw else 0.0
        for idx, score in bm25_hits:
            rid = _attr(records[idx], "id")
            if bm25_max > bm25_min:
                bm25_map[rid] = (score - bm25_min) / (bm25_max - bm25_min)
            else:
                bm25_map[rid] = 0.5

        # FAISS → [0, 1]
        faiss_map: dict = {}
        for rid, score in faiss_hits:
            faiss_map[rid] = (score + 1.0) / 2.0

        # 加权融合
        all_ids = set(bm25_map.keys()) | set(faiss_map.keys())
        fused = []
        for rid in all_ids:
            b = bm25_map.get(rid, 0.0)
            f = faiss_map.get(rid, 0.0)
            fused.append((rid, bm25_weight * b + faiss_weight * f))

        fused.sort(key=lambda x: x[1], reverse=True)
        top = fused[:top_k]

        results = []
        for rid, score in top:
            record = self._lookup_record(rid)
            if record:
                content = _attr(record, "content")
                results.append({
                    "record_id": rid,
                    "content": content,
                    "score": round(score, 4),
                    "method": "hybrid",
                    "collection": collection or "all",
                })
        return results

    # ---- 内部 ----

    def _lookup_record(self, rid: str):
        """在 Store 或 Repo 中按 ID 查找记录。"""
        if self.store:
            return self.store.get_by_id(rid)
        if self.pref_repo:
            r = self.pref_repo.get_by_id(rid)
            if r:
                return r
        if self.know_repo:
            r = self.know_repo.get_by_id(rid)
            if r:
                return r
        return None

    def _get_all_records(self) -> List:
        if self.store:
            return self.store.get_all()
        records = []
        if self.pref_repo:
            records.extend(self.pref_repo.find_active())
        if self.know_repo:
            records.extend(self.know_repo.find_active())
        return records
