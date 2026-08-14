"""
LLM 三元组提取器 — DeepSeek API
"""

import json
import logging
import re

from memoryhub.core.memory.llm import StructuredLLMAdapter

from .llm import build_chat_client
from .models import EntityType, RawTriple
from .prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_TEMPLATE

logger = logging.getLogger(__name__)

# DeepSeek 默认配置


class TripleExtractor:
    """
    三元组提取器 — 调用 DeepSeek API。

    用法:
        extractor = TripleExtractor(api_key="sk-xxx")
        triples = extractor.extract("苹果公司总部位于库比蒂诺。")
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        llm_client=None,
    ):
        self.model = model
        self._adapter = (
            StructuredLLMAdapter(llm_client)
            if callable(getattr(llm_client, "generate", None))
            else None
        )
        self._client = build_chat_client(
            api_key=api_key, llm_client=llm_client, base_url=base_url
        )
        self.last_error: Exception | None = None

    def extract(self, text: str, source_id: str = "") -> list[RawTriple]:
        """
        从文本提取三元组列表。

        优先走 LLM；当 LLM 不可用或未返回三元组时，回退到确定性规则抽取，
        保证本地无 API key 时客观事实仍可写入（FCT-01）。两者都失败时
        记录 last_error 供 propose() 上报，而不静默吞掉。

        Args:
            text: 输入文本
            source_id: 来源标识（用于追踪）

        Returns:
            RawTriple 列表，提取失败返回空列表
        """
        self.last_error = None
        if not text.strip():
            return []

        user_message = EXTRACTION_USER_TEMPLATE.format(text=text)

        try:
            if self._adapter is not None:
                raw_output = self._adapter.generate_text(
                    task_name="fact_triple_extraction",
                    system_prompt=EXTRACTION_SYSTEM_PROMPT,
                    prompt=user_message,
                    temperature=0.0,
                )
            else:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.0,
                    max_tokens=4096,
                )
                raw_output = response.choices[0].message.content or ""
            triples = self._parse_response(raw_output, source_id)
            if triples:
                return triples
            logger.info(f"[{source_id}] LLM 未返回三元组，回退规则抽取")
            return self._rule_extract(text, source_id)

        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            triples = self._rule_extract(text, source_id)
            if not triples:
                # 同时失败才上报错误，避免无 LLM 环境静默丢失事实
                self.last_error = e
            return triples

    def _rule_extract(self, text: str, source_id: str = "") -> list[RawTriple]:
        """确定性规则抽取：识别中英文客观陈述（属性/位置/成立时间）。

        刻意保守：只匹配带明确谓词锚点（…的X是…、…位于…、…成立于…、
        is the X of、located in、founded in）的陈述句，避免把任意文本拆成噪声三元组。
        """
        triples: list[RawTriple] = []
        for pattern, predicate_group in self._RULE_PATTERNS:
            flags = re.IGNORECASE if pattern.startswith(r"(?P<subj>[A-Za-z]") else 0
            for match in re.finditer(pattern, text, flags):
                subj = re.sub(r"[.。！？!?；;，,\s]+$", "", match.group("subj").strip())
                pred = (
                    match.group("pred").strip().lower()
                    if predicate_group == "pred" and match.groupdict().get("pred")
                    else predicate_group
                )
                obj = re.sub(r"[.。！？!?；;，,\s]+$", "", match.group("obj").strip())
                if not subj or not pred or not obj:
                    continue
                # “is the X of” 句式：主语与宾语互换（Tim Cook is the CEO of Apple）
                if pattern == self._EN_ROLE_PATTERN:
                    subj, obj = obj, subj
                evidence = match.group(0).strip()
                triples.append(
                    RawTriple(
                        subject_text=subj,
                        subject_type=self._guess_entity_type(subj),
                        predicate_text=pred,
                        object_text=obj,
                        object_type=self._guess_entity_type(obj, predicate=pred),
                        evidence=evidence,
                        confidence=0.7,
                    )
                )
        return triples

    _CN_ATTR_PATTERNS = (
        r"(?P<subj>.{2,}?)的(?P<pred>负责人|创始人|所有者|老板|经理|CEO|状态|名称|类型|版本|更新时间|创建时间|地址|邮箱|电话)\s*是\s*(?P<obj>[^。！？!?；;，,]{2,})",
        r"(?P<subj>.{2,}?)的(?P<pred>负责人|创始人|所有者|老板|经理|CEO)\s*为\s*(?P<obj>[^。！？!?；;，,]{2,})",
    )
    _CN_LOC_PATTERNS = (
        r"(?P<subj>.{2,}?)\s*位于\s*(?P<obj>[^。！？!?；;，,]{2,})",
        r"(?P<subj>.{2,}?)\s*坐落于\s*(?P<obj>[^。！？!?；;，,]{2,})",
    )
    _CN_DATE_PATTERNS = (
        r"(?P<subj>.{2,}?)\s*成立于\s*(?P<obj>[^。！？!?；;，,]{2,})",
        r"(?P<subj>.{2,}?)\s*创建于\s*(?P<obj>[^。！？!?；;，,]{2,})",
    )
    _EN_ROLE_PATTERN = (
        r"(?P<subj>[A-Za-z][A-Za-z0-9 ._-]{1,60})\s+is\s+the\s+"
        r"(?P<pred>ceo|founder|owner|head|manager|leader)\s+of\s+"
        r"(?P<obj>[A-Za-z][A-Za-z0-9 ._-]{1,60})"
    )
    _EN_LOC_PATTERNS = (
        r"(?P<subj>[A-Za-z][A-Za-z0-9 ._-]{1,60})\s+is\s+located\s+in\s+"
        r"(?P<obj>[^.!??;?,]{1,60})",
        r"(?P<subj>[A-Za-z][A-Za-z0-9 ._-]{1,60})\s+is\s+based\s+in\s+"
        r"(?P<obj>[^.!??;?,]{1,60})",
    )
    _EN_DATE_PATTERNS = (
        r"(?P<subj>[A-Za-z][A-Za-z0-9 ._-]{1,60})\s+was\s+founded\s+in\s+(?P<obj>[^.!?]{1,40})",
        r"(?P<subj>[A-Za-z][A-Za-z0-9 ._-]{1,60})\s+was\s+established\s+in\s+(?P<obj>[^.!?]{1,40})",
    )
    _RULE_PATTERNS = tuple(
        [(p, "pred") for p in _CN_ATTR_PATTERNS]
        + [(p, "位于") for p in _CN_LOC_PATTERNS]
        + [(p, "成立于") for p in _CN_DATE_PATTERNS]
        + [(_EN_ROLE_PATTERN, "pred")]
        + [(p, "located in") for p in _EN_LOC_PATTERNS]
        + [(p, "founded in") for p in _EN_DATE_PATTERNS]
    )

    _PERSON_PREDICATES = (
        "负责人",
        "创始人",
        "所有者",
        "老板",
        "经理",
        "ceo",
        "founder",
        "owner",
        "head",
        "manager",
        "leader",
    )

    @classmethod
    def _guess_entity_type(cls, text: str, predicate: str = "") -> str:
        """无 LLM 时的轻量实体类型启发式（仅用于规则降级路径）。"""
        value = text.strip()
        if re.match(r"^(?:19|20)\d{2}年?$", value) or re.match(
            r"^\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?$", value
        ):
            return EntityType.DATE.value
        if re.search(
            r"(公司|集团|有限公司|大学|研究院|政府|银行|协会|组织|机构|企业|部门|corporation|inc\.?|ltd\.?|company|university|organization|government|department)",
            value,
            re.IGNORECASE,
        ):
            return EntityType.ORGANIZATION.value
        if re.search(
            r"(市|省|区|县|镇|乡|国|洲|city|province|county|state|region|country)",
            value,
            re.IGNORECASE,
        ):
            return EntityType.LOCATION.value
        if predicate.lower() in cls._PERSON_PREDICATES:
            return EntityType.PERSON.value
        if any(
            kw in predicate.lower() for kw in ("位于", "坐落", "located", "based in")
        ):
            return EntityType.LOCATION.value
        return EntityType.OTHER.value

    def _parse_response(self, raw: str, source_id: str) -> list[RawTriple]:
        """解析 LLM 返回的 JSON，验证字段完整性和类型合法性"""
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"JSON 解析失败，原始输出: {raw[:300]}")
            return []

        triples_data = data.get("triples", [])
        if not isinstance(triples_data, list):
            return []

        valid_types = set(EntityType.choices())
        results: list[RawTriple] = []
        required = [
            "subject",
            "subject_type",
            "predicate",
            "object",
            "object_type",
            "evidence",
            "confidence",
        ]

        for item in triples_data:
            missing = [f for f in required if f not in item]
            if missing:
                logger.warning(f"丢弃不完整三元组（缺字段 {missing}）: {item}")
                continue

            # 校验实体类型合法性
            st = item["subject_type"].strip()
            ot = item["object_type"].strip()
            if st not in valid_types:
                st = EntityType.OTHER.value
            if ot not in valid_types:
                ot = EntityType.OTHER.value

            c = item["confidence"]
            if not isinstance(c, (int, float)) or c < 0 or c > 1:
                c = 0.5

            results.append(
                RawTriple(
                    subject_text=item["subject"].strip(),
                    subject_type=st,
                    predicate_text=item["predicate"].strip(),
                    object_text=item["object"].strip(),
                    object_type=ot,
                    evidence=item["evidence"].strip(),
                    confidence=float(c),
                )
            )

        logger.info(f"[{source_id}] 提取 {len(results)} 个三元组")
        return results


def get_extractor(api_key: str = "") -> TripleExtractor:
    """工厂函数：用 DeepSeek 默认配置创建提取器"""
    return TripleExtractor(api_key=api_key)
