"""
实体归一化 + 谓词归一化

实体归一化流水线（严格同类型匹配，不做跨类型链接）:
  1. 同 type alias 精确匹配 (O(1))
  2. 同 type canonical_name 精确匹配
  3. 关键词 bigram 包含度匹配（高分则直接命中，跳过 LLM）
  4. 向量 max-pooling 粗筛 → top-5 候选 → LLM 精判
  5. 创建新实体（写入 LLM 提取时顺带生成的别名）

谓词归一化流水线:
  1. alias 精确匹配
  2. 向量粗筛 → top-k → LLM 精判
  3. 创建新谓词
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .llm import build_chat_client

from .models import Entity, PredicateDef
from .store import FactStore
from .embedding_index import EmbeddingIndex, bigram_containment
from .prompts import (
    ENTITY_NORMALIZE_SYSTEM, ENTITY_NORMALIZE_USER,
    PREDICATE_NORMALIZE_SYSTEM, PREDICATE_NORMALIZE_USER,
    ALIAS_GENERATION_SYSTEM, ALIAS_GENERATION_USER,
)

logger = logging.getLogger(__name__)

_DEFAULT_ONTOLOGY = Path(__file__).parent / "predicate_ontology.json"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
VECTOR_SEARCH_LIMIT = 50  # 同类型实体全量发给LLM（量小，不截断）

# 关键词匹配阈值：bigram 包含度 >= 此值 → 直接命中，不调 LLM
# 实体名较长，设 0.85；谓词名较短，谓词类内部用自己的较低阈值
KEYWORD_CONFIDENT_THRESHOLD = 0.85
PREDICATE_KEYWORD_THRESHOLD = 0.45  # 谓词短，阈值放低


def _build_llm_client(api_key: str = "", llm_client=None):
    return build_chat_client(
        api_key=api_key, llm_client=llm_client, base_url=DEEPSEEK_BASE_URL
    )


# ─── 实体归一化 ───────────────────────────────────────────────────────

class EntityNormalizer:
    """
    分层策略（严格同类型，不跨类型链接）：
    1. 同 type 内别名精确匹配
    2. 同 type 内 canonical_name 精确匹配
    3. 关键词 bigram 包含度 ≥ 阈值 → 直接命中
    4. 向量 max-pooling → 高分+无歧义 → 直接命中
                        → 中等分 → LLM 精判
    5. 创建新实体
    """

    # 向量直接命中阈值：按嵌入模式自适应
    # sentence-transformers 语义向量分辨力强，阈值可以更高
    # char n-gram 分值整体偏低，阈值要放低但 gap 要求更严
    VEC_THRESHOLD_ST = 0.88    # 语义向量阈值
    VEC_THRESHOLD_FALLBACK = 0.78  # char n-gram 阈值
    VEC_MIN_GAP = 0.12         # top-1 与 top-2 的最小分差（防歧义）

    def __init__(self, store: FactStore, api_key: str = "", llm_client=None):
        self.store = store
        self._llm = _build_llm_client(api_key, llm_client)
        self._index = EmbeddingIndex()
        self._using_st = self._check_st_available()
        self._vec_threshold = self.VEC_THRESHOLD_ST if self._using_st else self.VEC_THRESHOLD_FALLBACK
        self._build_index()

    @staticmethod
    def _check_st_available() -> bool:
        try:
            from sentence_transformers import SentenceTransformer
            return True
        except Exception:
            return False

    def _build_index(self):
        """从 DB 加载已有实体到向量索引"""
        import sqlite3
        rows = self.store._conn.execute("SELECT * FROM entities").fetchall()
        for row in rows:
            aliases = json.loads(row["aliases"])
            self._index.add(
                item_id=row["entity_id"],
                canonical_name=row["canonical_name"],
                aliases=aliases,
            )
        logger.info(f"实体索引已构建: {len(self._index)} 条")

    def normalize(self, text: str, entity_type: str, user_id: str = "default") -> str:
        """
        Args:
            text: 原始文本中的实体名
            entity_type: LLM 判定的实体类型
        """
        text = text.strip()
        if not text:
            return Entity.make_id(entity_type, "unknown", user_id)

        # ── 1. 同 type 内精确匹配 aliases ──
        matches = self.store.find_entity_by_name(text, entity_type, user_id=user_id)
        if matches:
            eid = matches[0].entity_id
            self._add_alias_if_new(eid, text, user_id=user_id)
            return eid

        # ── 2. 同 type 内精确匹配 canonical_name ──
        all_same = self.store.list_entities_by_type(entity_type, user_id=user_id)
        for ent in all_same:
            if ent.canonical_name.strip().lower() == text.lower():
                self._add_alias_if_new(ent.entity_id, text, user_id=user_id)
                return ent.entity_id

        # ── 3. 关键词 bigram 包含度 → 高分直接命中 ──
        keyword_hit = self._keyword_match(text, entity_type, user_id=user_id)
        if keyword_hit:
            eid = keyword_hit
            self._add_alias_if_new(eid, text, user_id=user_id)
            logger.info(f"关键词直接命中: '{text}' → {eid}")
            return eid

        # ── 4. 向量粗筛 → 高分直接命中 / 否则 LLM 精判 ──
        type_prefix = f"entity:{entity_type.lower()}:"
        candidates = self._index.search(
            text, top_k=max(VECTOR_SEARCH_LIMIT, len(self._index)),
            type_filter=[type_prefix],
        )
        candidates = [
            item for item in candidates
            if self.store.get_entity(item[0], user_id=user_id) is not None
        ][:VECTOR_SEARCH_LIMIT]
        if candidates:
            # 高分 + 无歧义 → 直接命中，跳过 LLM
            if self._vector_confident(candidates):
                eid = candidates[0][0]
                self._add_alias_if_new(eid, text, user_id=user_id)
                logger.info(f"向量直接命中: '{text}' → {eid} (score={candidates[0][1]:.3f})")
                return eid
            # 否则 LLM 精判（低分也可能匹配，LLM 说了算）
            eid = self._llm_disambiguate(text, entity_type, candidates, user_id=user_id)
            if eid:
                self._add_alias_if_new(eid, text, user_id=user_id)
                return eid

        # ── 5. 创建新实体 ──
        return self._create_entity(text, entity_type, user_id=user_id)

    def _vector_confident(self, candidates: list[tuple[str, float]]) -> bool:
        """
        向量 top-1 是否足够高且无歧义，可以跳过 LLM 直接命中。

        条件: top-1 ≥ 阈值 AND (top-1 - top-2) ≥ gap
        如果只有 1 个候选，gap 条件自动满足。
        """
        if not candidates:
            return False
        top1_score = candidates[0][1]
        if top1_score < self._vec_threshold:
            return False
        if len(candidates) >= 2:
            gap = top1_score - candidates[1][1]
            if gap < self.VEC_MIN_GAP:
                return False
        return True

    def _keyword_match(self, text: str, entity_type: str, user_id: str = "default") -> Optional[str]:
        """
        关键词匹配：遍历同类型实体的所有名字，
        bigram 包含度 ≥ KEYWORD_CONFIDENT_THRESHOLD 的直接返回实体 ID。
        阈值设得较高（0.85），确保只在高置信度时跳过 LLM。
        """
        best_eid = None
        best_score = 0.0

        for ent in self.store.list_entities_by_type(entity_type, user_id=user_id):
            # 组装该实体的所有名字
            names = [ent.canonical_name] + ent.aliases
            for name in names:
                score = bigram_containment(text, name)
                if score > best_score:
                    best_score = score
                    best_eid = ent.entity_id

        if best_score >= KEYWORD_CONFIDENT_THRESHOLD and best_eid:
            return best_eid
        return None

    def _create_entity(self, text: str, entity_type: str, user_id: str = "default") -> str:
        """创建新实体，知名类型用 LLM 生成别名 + 后续归一化命中时自动追加"""
        # 只对 Organization/Location 调 LLM 生成别名（人名的别名不可靠，靠实际使用长出来）
        guessed_aliases = self._generate_aliases(text, entity_type) \
            if entity_type in ("Organization", "Location") else []

        seen = {text}
        all_aliases = [text]
        for a in guessed_aliases:
            a = a.strip()
            if a and a not in seen:
                all_aliases.append(a)
                seen.add(a)

        entity = Entity(
            entity_id=Entity.make_id(entity_type, text, user_id),
            canonical_name=text,
            entity_type=entity_type,
            aliases=all_aliases,
            user_id=user_id,
        )
        self.store.upsert_entity(entity)
        self._index.add(entity.entity_id, entity.canonical_name, entity.aliases)
        logger.info(f"创建新实体: {entity.entity_id} ('{text}', {entity_type}), aliases={all_aliases}")
        return entity.entity_id

    def _generate_aliases(self, name: str, entity_type: str) -> list[str]:
        """LLM 为知名实体生成常见别名，不确定时返回空列表"""
        try:
            resp = self._llm.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": ALIAS_GENERATION_SYSTEM},
                    {"role": "user", "content": ALIAS_GENERATION_USER.format(
                        name=name, entity_type=entity_type,
                    )},
                ],
                temperature=0.0, max_tokens=128,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            aliases = data.get("aliases", [])
            if isinstance(aliases, list):
                return [a for a in aliases if isinstance(a, str) and a.strip()]
        except Exception:
            pass
        return []

    def _llm_disambiguate(self, name: str, entity_type: str,
                          candidates: list[tuple[str, float]],
                          user_id: str = "default") -> Optional[str]:
        """只在 top-k 候选中让 LLM 判断"""
        existing_str = ""
        for cid, score in candidates:
            ent = self.store.get_entity(cid, user_id=user_id)
            if ent:
                existing_str += (
                    f"  ID: {ent.entity_id} | 规范名: {ent.canonical_name} "
                    f"| 别名: {ent.aliases} | 相似度: {score:.3f}\n"
                )

        if not existing_str:
            return None

        try:
            resp = self._llm.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": ENTITY_NORMALIZE_SYSTEM},
                    {"role": "user", "content": ENTITY_NORMALIZE_USER.format(
                        entity_type=entity_type, name=name,
                        existing_entities=existing_str,
                    )},
                ],
                temperature=0.0, max_tokens=256,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            if data.get("is_new"):
                return None
            eid = data.get("entity_id", "")
            if self.store.get_entity(eid, user_id=user_id):
                logger.info(f"LLM 匹配实体: '{name}' → {eid}")
                return eid
        except Exception as e:
            logger.warning(f"实体 LLM 归一化失败: {e}")
        return None

    def _add_alias_if_new(self, entity_id: str, alias: str, user_id: str = "default"):
        entity = self.store.get_entity(entity_id, user_id=user_id)
        if entity and alias not in entity.aliases:
            entity.aliases.append(alias)
            self.store.upsert_entity(entity)
            self._index.add(entity.entity_id, entity.canonical_name, entity.aliases)

    def add_alias(self, entity_id: str, alias: str, user_id: str = "default"):
        self._add_alias_if_new(entity_id, alias, user_id=user_id)


# ─── 谓词归一化 ──────────────────────────────────────────────────────

class PredicateNormalizer:
    """
    与实体归一化同构的流水线：
    1. alias 精确匹配
    2. 关键词 bigram 包含度 ≥ 阈值 → 直接命中
    3. 向量 max-pooling → 高分+无歧义 → 直接命中
                        → 中等分 → LLM 精判
                        → 低分 → 跳过LLM，直接新建
    4. 创建新谓词
    """

    VEC_THRESHOLD_ST = 0.90      # 语义向量高分阈值（谓词短，阈值比实体略高）
    VEC_THRESHOLD_FALLBACK = 0.82
    VEC_MIN_GAP = 0.12

    def __init__(self, store: FactStore, ontology_path: Optional[str] = None, api_key: str = "", llm_client=None):
        self.store = store
        self._llm = _build_llm_client(api_key, llm_client)
        self._alias_to_id: dict[str, str] = {}
        self._index = EmbeddingIndex()
        self._using_st = EntityNormalizer._check_st_available()
        self._vec_threshold = self.VEC_THRESHOLD_ST if self._using_st else self.VEC_THRESHOLD_FALLBACK
        self._load_ontology(ontology_path)
        self._build_index()

    def _vector_confident(self, candidates: list[tuple[str, float]]) -> bool:
        if not candidates:
            return False
        top1_score = candidates[0][1]
        if top1_score < self._vec_threshold:
            return False
        if len(candidates) >= 2:
            gap = top1_score - candidates[1][1]
            if gap < self.VEC_MIN_GAP:
                return False
        return True

    def _load_ontology(self, path: Optional[str] = None):
        path = Path(path or _DEFAULT_ONTOLOGY)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"无法加载谓词本体文件 {path}: {e}，使用空本体")
            data = {"predicates": []}
        for entry in data.get("predicates", []):
            pred = PredicateDef(**entry)
            self.store.upsert_predicate(pred)
            for alias in pred.aliases:
                self._alias_to_id[alias] = pred.predicate_id
        logger.info(f"加载 {len(data.get('predicates', []))} 个种子谓词")

    def _build_index(self):
        for pred in self.store.list_predicates():
            self._index.add(pred.predicate_id, pred.canonical_name, pred.aliases)
        logger.info(f"谓词索引已构建: {len(self._index)} 条")

    def normalize(self, text: str) -> str:
        text = text.strip()

        # 1. 精确匹配
        if text in self._alias_to_id:
            pid = self._alias_to_id[text]
            self._add_alias_if_new(pid, text)
            return pid

        # 2. 关键词 bigram 包含度 → 高分直接命中
        keyword_hit = self._keyword_match(text)
        if keyword_hit:
            self._add_alias_if_new(keyword_hit, text)
            logger.info(f"关键词直接命中谓词: '{text}' → {keyword_hit}")
            return keyword_hit

        # 3. 向量粗筛 → 高分直接命中 / 否则 LLM 精判
        candidates = self._index.search(text, top_k=VECTOR_SEARCH_LIMIT)
        if candidates:
            # 高分 + 无歧义 → 直接命中
            if self._vector_confident(candidates):
                pid = candidates[0][0]
                self._add_alias_if_new(pid, text)
                logger.info(f"向量直接命中谓词: '{text}' → {pid} (score={candidates[0][1]:.3f})")
                return pid
            # 否则 LLM 精判（低分也可能匹配，LLM 说了算）
            pid = self._llm_disambiguate(text, candidates)
            if pid:
                self._add_alias_if_new(pid, text)
                return pid

        # 4. 创建新谓词
        return self._create_predicate(text)

    def _keyword_match(self, text: str) -> Optional[str]:
        """遍历所有谓词的别名，bigram 包含度 ≥ 阈值直接返回"""
        best_pid = None
        best_score = 0.0

        for pred in self.store.list_predicates():
            names = [pred.canonical_name] + pred.aliases
            for name in names:
                score = bigram_containment(text, name)
                if score > best_score:
                    best_score = score
                    best_pid = pred.predicate_id

        if best_score >= PREDICATE_KEYWORD_THRESHOLD and best_pid:
            return best_pid
        return None

    def _create_predicate(self, text: str) -> str:
        pred = PredicateDef(
            predicate_id=PredicateDef.make_id(text),
            canonical_name=text,
            aliases=[text],
            single_value=True,
        )
        self.store.upsert_predicate(pred)
        self._alias_to_id[text] = pred.predicate_id
        self._index.add(pred.predicate_id, pred.canonical_name, pred.aliases)
        logger.info(f"创建新谓词: {pred.predicate_id} ('{text}')")
        return pred.predicate_id

    def _llm_disambiguate(self, pred_text: str,
                          candidates: list[tuple[str, float]]) -> Optional[str]:
        existing_str = ""
        for cid, score in candidates:
            pred = self.store.get_predicate(cid)
            if pred:
                existing_str += (
                    f"  ID: {pred.predicate_id} | 规范名: {pred.canonical_name} "
                    f"| 别名: {pred.aliases} | 相似度: {score:.3f}\n"
                )

        if not existing_str:
            return None

        try:
            resp = self._llm.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": PREDICATE_NORMALIZE_SYSTEM},
                    {"role": "user", "content": PREDICATE_NORMALIZE_USER.format(
                        pred_text=pred_text, existing_predicates=existing_str,
                    )},
                ],
                temperature=0.0, max_tokens=256,
            )
            raw = resp.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            if data.get("is_new"):
                return None
            pid = data.get("predicate_id", "")
            if self.store.get_predicate(pid):
                logger.info(f"LLM 匹配谓词: '{pred_text}' → {pid}")
                return pid
        except Exception as e:
            logger.warning(f"谓词 LLM 归一化失败: {e}")
        return None

    def _add_alias_if_new(self, predicate_id: str, alias: str):
        pred = self.store.get_predicate(predicate_id)
        if pred and alias not in pred.aliases:
            pred.aliases.append(alias)
            self.store.upsert_predicate(pred)
            self._alias_to_id[alias] = predicate_id
            self._index.add(pred.predicate_id, pred.canonical_name, pred.aliases)

    def get(self, predicate_id: str) -> Optional[PredicateDef]:
        return self.store.get_predicate(predicate_id)
