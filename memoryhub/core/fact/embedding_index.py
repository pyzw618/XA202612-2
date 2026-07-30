"""
轻量向量索引 — 候选粗筛

优先使用 sentence-transformers；不安装则降级为字符 n-gram Jaccard 相似度。
用于归一化阶段：从大量实体/谓词中快速选出 top-k 候选，再交给 LLM 精判。

改进：
  - 向量匹配：每个 alias 单独 embed，搜索时取 max similarity（防止长尾别名稀释强信号）
  - 关键词匹配：字符 bigram 包含度评分，弥补向量对纯字面重叠不敏感的盲区
  - 混合评分：0.6 × vector_score + 0.4 × keyword_score
"""

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# 尝试加载 sentence-transformers
_ST_MODEL = None
_ST_DIM = 384

try:
    from sentence_transformers import SentenceTransformer
    _ST_MODEL = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    _ST_DIM = _ST_MODEL.get_sentence_embedding_dimension()
    logger.info(f"sentence-transformers 已加载, dim={_ST_DIM}")
except Exception:
    logger.info("sentence-transformers 不可用，使用字符 n-gram 相似度")


def _embed(texts: list[str]) -> list[list[float]]:
    """统一嵌入接口"""
    if _ST_MODEL is not None:
        emb = _ST_MODEL.encode(texts, normalize_embeddings=True)
        return emb.tolist()
    else:
        return [_char_ngram_vector(t) for t in texts]


def _char_ngram_vector(text: str, n: int = 3) -> list[float]:
    """字符 n-gram 出现频次 → 固定维度向量（256 维）"""
    text = text.lower()
    grams: dict[str, int] = {}
    for i in range(len(text) - n + 1):
        g = text[i:i + n]
        grams[g] = grams.get(g, 0) + 1
    vec = [0.0] * 256
    for g, cnt in grams.items():
        idx = hash(g) % 256
        vec[idx] += cnt
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_sim(a: list[float], b: list[float]) -> float:
    """余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, dot)  # 已归一化，直接点积


# ─── 关键词匹配：字符 bigram 包含度 ─────────────────────────────────────

def _char_bigrams(text: str) -> set[str]:
    """提取字符 bigram 集合"""
    t = text.lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else {t}


def bigram_containment(query: str, candidate: str) -> float:
    """
    查询的 bigram 中有多大比例出现在候选中。
    非对称：衡量"查询在多大程度上被候选覆盖"。

    例: query="比亚迪汽车", candidate="比亚迪股份有限公司"
        q_bigrams = {"比亚", "亚迪", "迪汽", "汽车"}
        → 交集 {"比亚", "亚迪"} → 2/4 = 0.5
    """
    q_grams = _char_bigrams(query)
    if not q_grams:
        return 0.0
    c_grams = _char_bigrams(candidate)
    intersection = q_grams & c_grams
    return len(intersection) / len(q_grams)


# ─── 向量索引（per-alias embedding + max-pooling）───────────────────────

class EmbeddingIndex:
    """
    实体/谓词的向量索引。

    每个条目存储多个别名各自的 embedding，
    搜索时对每个别名分别计算相似度，取最大值（max-pooling）。
    同时计算关键词 bigram 包含度，与向量分加权融合。

    用法:
        idx = EmbeddingIndex()
        idx.add("entity:org:byd", "比亚迪股份有限公司", ["比亚迪", "BYD"])
        idx.add("entity:org:huawei", "华为技术有限公司", ["华为", "Huawei"])
        candidates = idx.search("比亚迪汽车", top_k=5)
        # → [(entity_id, hybrid_score), ...]
    """

    def __init__(self, vector_weight: float = 0.6):
        """
        Args:
            vector_weight: 向量得分在混合评分中的权重（0-1），
                           剩余 (1 - vector_weight) 给关键词得分。
        """
        self._items: list[dict] = []  # [{id, names[], embeddings[]}]
        self._vector_weight = vector_weight

    def add(self, item_id: str, canonical_name: str, aliases: list[str] = None):
        """
        添加或更新索引条目。
        每个别名单独 embed，搜索时 max-pooling。
        """
        # 收集所有名字（去重）
        names = [canonical_name]
        if aliases:
            for a in aliases:
                if a and a != canonical_name and a not in names:
                    names.append(a)

        # 移除旧条目
        self.remove(item_id)

        # 每个名字单独 embed
        embeddings = _embed(names)  # [emb_for_name1, emb_for_name2, ...]
        self._items.append({
            "id": item_id,
            "names": names,
            "embeddings": embeddings,
        })

    def remove(self, item_id: str):
        self._items = [it for it in self._items if it["id"] != item_id]

    def search(
        self,
        query: str,
        top_k: int = 5,
        type_filter: list[str] = None,
    ) -> list[tuple[str, float]]:
        """
        混合搜索：向量 max-pooling + 关键词 bigram 包含度。

        Args:
            query: 查询文本
            top_k: 返回几个候选
            type_filter: 可选，按 ID 前缀过滤（如 ["entity:organization:"]）

        Returns:
            [(item_id, hybrid_score), ...] 按得分降序
        """
        if not self._items:
            return []

        q_emb = _embed([query])[0]
        scored = []

        for it in self._items:
            if type_filter:
                if not any(it["id"].startswith(prefix) for prefix in type_filter):
                    continue

            # 向量得分：所有别名 embedding 与 query 的 max similarity
            vec_score = max(cosine_sim(q_emb, emb) for emb in it["embeddings"])

            # 关键词得分：所有名字与 query 的 best bigram 包含度
            kw_score = max(bigram_containment(query, name) for name in it["names"])

            # 混合
            hybrid = self._vector_weight * vec_score + (1 - self._vector_weight) * kw_score
            scored.append((it["id"], hybrid))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def __len__(self):
        return len(self._items)
