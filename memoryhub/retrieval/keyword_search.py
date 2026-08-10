"""
关键词检索模块

基于 BM25 的关键词检索。
"""

import json
import re

import numpy as np

from memoryhub.adapter.schemas import SearchResult

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None

try:
    import jieba
except ImportError:
    jieba = None


def _is_punct_only(s: str) -> bool:
    """判断字符串是否仅由标点/空白构成。"""
    return not re.search(r"[a-zA-Z0-9一-鿿]", s)


def _tokenize(text: str) -> list[str]:
    """
    中文分词：jieba 精确模式 + 英文/数字保留。

    与旧版 src/search_engine.py 的 _tokenize 保持一致。

    例：
      "数据库登录密码" → ["数据库", "登录", "密码"]
      "我的系统密码是Admin@123" → ["系统", "密码", "Admin", "123"]
    """
    if jieba is None:
        # 降级：简易正则分词
        return re.findall(r"[一-鿿]|[a-zA-Z0-9]+", text.lower())

    tokens = []
    for word in jieba.cut(text.lower()):
        word = word.strip()
        if word and not _is_punct_only(word):
            tokens.append(word)
    return tokens


class KeywordSearcher:
    """
    BM25 关键词检索器

    使用方式:
        searcher = KeywordSearcher()
        searcher.build_index([(memory_id, content, metadata_json), ...])
        results = searcher.search("项目周报", top_k=5)
    """

    def __init__(self):
        self.index = None  # BM25 索引
        self.doc_map: dict[int, str] = {}  # 内部 doc_id → memory_id
        self._docs: dict[str, tuple[str, dict]] = {}  # memory_id → (content, metadata)
        self._tokenized_corpus: list[list[str]] = []

    def build_index(self, documents: list[tuple[str, str, str]]) -> None:
        """
        构建 BM25 索引

        参数:
            documents: [(memory_id, content, metadata_json), ...]

        数据流:
            存储中的所有记忆 → build_index → BM25 索引
        """
        if BM25Okapi is None:
            raise ImportError("rank-bm25 未安装，请执行: pip install rank-bm25")

        self._docs = {}
        for memory_id, content, metadata_json in documents:
            self._docs[memory_id] = (content, self._parse_metadata(metadata_json))
        self._rebuild()

    def add_document(self, memory_id: str, content: str, metadata: str = "") -> None:
        """添加单条文档到索引（增量场景下直接重建，数据量小可接受）"""
        self._docs[memory_id] = (content, self._parse_metadata(metadata))
        self._rebuild()

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
        if self.index is None or not self.doc_map:
            return []

        tokenized_query = _tokenize(query)
        if not tokenized_query:
            return []

        scores = self.index.get_scores(tokenized_query)
        if top_k >= len(scores):
            top_indices = list(range(len(scores)))
            top_indices.sort(key=lambda i: scores[i], reverse=True)
        else:
            top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            idx = int(idx)
            score = float(scores[idx])
            memory_id = self.doc_map.get(idx)
            if memory_id is None:
                continue
            content, metadata = self._docs[memory_id]
            results.append(
                SearchResult(
                    memory_id=memory_id,
                    memory_type=metadata.get("memory_type", ""),
                    content=content,
                    score=score,
                    source="keyword",
                    metadata=dict(metadata),
                )
            )
        return results

    def delete(self, memory_id: str) -> bool:
        """删除文档，返回是否存在并成功删除"""
        if memory_id not in self._docs:
            return False
        del self._docs[memory_id]
        self._rebuild()
        return True

    def update(self, memory_id: str, content: str, metadata: str = "") -> None:
        """更新文档"""
        self._docs[memory_id] = (content, self._parse_metadata(metadata))
        self._rebuild()

    def _rebuild(self) -> None:
        """根据当前文档集重建 BM25 索引和 id 映射"""
        self.doc_map = {}
        self._tokenized_corpus = []
        for idx, (memory_id, (content, metadata)) in enumerate(self._docs.items()):
            self.doc_map[idx] = memory_id
            # metadata 一并参与分词，提升可匹配性
            meta_text = " ".join(str(v) for v in metadata.values() if isinstance(v, str))
            self._tokenized_corpus.append(_tokenize(f"{content} {meta_text}".strip()))

        if not self._tokenized_corpus:
            self.index = None
            return
        self.index = BM25Okapi(self._tokenized_corpus)

    @staticmethod
    def _parse_metadata(metadata: str | dict) -> dict:
        """metadata 支持 JSON 字符串或 dict，解析失败时返回空 dict"""
        if isinstance(metadata, dict):
            return dict(metadata)
        if not metadata:
            return {}
        try:
            parsed = json.loads(metadata)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
