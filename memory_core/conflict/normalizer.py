from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple


ATTRIBUTE_PATTERNS: Sequence[Tuple[str, Sequence[str]]] = (
    ("deadline", ("截止", "报名时间", "提交时间", "ddl", "DDL")),
    ("response_latency", ("响应时间", "响应延迟", "检索延迟", "延迟", "耗时")),
    ("recall_rate", ("召回率", "recall")),
    ("accuracy", ("准确率", "正确率", "accuracy")),
    ("count_limit", ("人数", "数量", "总人数", "成员数")),
    ("preference", ("偏好", "习惯", "风格", "输出格式")),
    ("deployment", ("部署", "端侧", "本地", "云端")),
    ("storage", ("存储", "数据库", "记忆库")),
    ("retrieval_method", ("检索方式", "检索方法", "混合检索", "BM25", "向量检索")),
    ("forgetting", ("遗忘", "删除", "清除", "不再记住")),
    ("security_policy", ("安全策略", "敏感信息", "脱敏", "PII", "隐私")),
    ("tool", ("工具", "调用", "命令", "终端")),
    ("version", ("版本", "V10", "V11", "SP1")),
    ("support_status", ("支持", "允许", "禁止", "启用", "关闭", "禁用")),
)

ENTITY_PATTERNS: Sequence[Tuple[str, Sequence[str]]] = (
    ("Agent本体", ("Agent本体", "智能体本体", "基线模型")),
    ("报名", ("报名", "截止")),
    ("记忆检索", ("检索", "召回", "rerank", "BM25", "FAISS", "HNSW")),
    ("偏好记忆", ("偏好", "用户画像", "输出格式", "习惯")),
    ("知识冲突处理", ("知识冲突", "冲突检测", "新旧知识", "知识融合")),
    ("精准遗忘", ("精准遗忘", "主动遗忘", "删除记忆", "不再记住")),
    ("存储模块", ("长期记忆", "SQLite", "数据库", "存储", "记忆库")),
    ("安全合规", ("敏感信息", "PII", "脱敏", "隐私", "安全策略")),
    ("部署环境", ("部署", "端侧", "银河麒麟", "麒麟OS", "麒麟 OS")),
    ("Agent本体", ("Agent", "智能体", "大模型")),
)

SCOPE_PATTERNS: Sequence[Tuple[str, Sequence[str]]] = (
    ("技术报告", ("技术报告", "报告", "论文", "文档")),
    ("代码", ("代码", "Python", "Java", "C++", "脚本")),
    ("PPT", ("PPT", "幻灯片", "展示", "答辩")),
    ("面试", ("面试", "自我介绍")),
    ("全局", ("默认", "全局", "长期")),
)

POSITIVE_WORDS = (
    "支持",
    "允许",
    "启用",
    "开启",
    "需要",
    "必须",
    "可以",
    "已完成",
    "可用",
    "保留",
)
NEGATIVE_WORDS = (
    "不支持",
    "不能",
    "不允许",
    "禁止",
    "禁用",
    "关闭",
    "无需",
    "不需要",
    "未完成",
    "不可用",
    "不再",
)
UPDATE_WORDS = ("改为", "调整为", "更新为", "变更为", "延长到", "缩短到", "替换为", "不再", "取消")


@dataclass(frozen=True)
class NumericValue:
    op: str
    value: float
    unit: str
    raw: str

    def normalized_unit(self) -> str:
        if self.unit in ("毫秒", "ms", "MS"):
            return "ms"
        if self.unit in ("秒", "s", "S"):
            return "s"
        if self.unit in ("%", "％", "百分比"):
            return "%"
        if self.unit.upper() in ("GB", "G"):
            return "GB"
        if self.unit.upper() in ("MB", "M"):
            return "MB"
        return self.unit

    def normalized_value(self) -> float:
        unit = self.normalized_unit()
        if unit == "s":
            return self.value * 1000.0
        return self.value


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip()


def contains_any(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def extract_by_patterns(text: str, patterns: Sequence[Tuple[str, Sequence[str]]], default: str = "") -> str:
    compact = normalize_text(text)
    for label, words in patterns:
        if contains_any(compact, words):
            return label
    return default


def extract_entity(text: str) -> str:
    return extract_by_patterns(text, ENTITY_PATTERNS)


def extract_attribute(text: str) -> str:
    return extract_by_patterns(text, ATTRIBUTE_PATTERNS)


def extract_scope(text: str) -> str:
    return extract_by_patterns(text, SCOPE_PATTERNS)


def extract_dates(text: str, default_year: int = 2026) -> List[str]:
    compact = normalize_text(text)
    dates: List[str] = []
    for year, month, day in re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", compact):
        dates.append(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    for year, month, day in re.findall(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", compact):
        dates.append(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    for month, day in re.findall(r"(?<!\d)(\d{1,2})月(\d{1,2})日", compact):
        candidate = f"{default_year:04d}-{int(month):02d}-{int(day):02d}"
        if candidate not in dates:
            dates.append(candidate)
    return dates


def extract_numeric_values(text: str) -> List[NumericValue]:
    compact = normalize_text(text)
    values: List[NumericValue] = []
    pattern = re.compile(
        r"(<=|>=|≤|≥|<|>|=|不超过|不少于|不低于|不高于|至少|至多|小于|大于|低于|高于|等于|为)?"
        r"(\d+(?:\.\d+)?)"
        r"\s*(ms|毫秒|秒|s|%|％|GB|G|MB|M|个|人|次|条)?"
        r"(以上|以下|以内|内)?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(compact):
        raw_op = match.group(1) or match.group(4) or "="
        op = normalize_op(raw_op)
        unit = match.group(3) or ""
        raw = match.group(0)
        values.append(NumericValue(op=op, value=float(match.group(2)), unit=unit, raw=raw))
    return values


def normalize_op(op: str) -> str:
    mapping = {
        "≤": "<=",
        "不超过": "<=",
        "不高于": "<=",
        "至多": "<=",
        "以下": "<=",
        "以内": "<=",
        "内": "<=",
        "低于": "<",
        "小于": "<",
        "≥": ">=",
        "不少于": ">=",
        "不低于": ">=",
        "至少": ">=",
        "以上": ">=",
        "高于": ">",
        "大于": ">",
        "等于": "=",
        "为": "=",
    }
    return mapping.get(op, op)


def extract_bool_polarity(text: str) -> Optional[bool]:
    compact = normalize_text(text)
    if contains_any(compact, NEGATIVE_WORDS):
        return False
    if contains_any(compact, POSITIVE_WORDS):
        return True
    return None


def has_update_intent(text: str) -> bool:
    return contains_any(normalize_text(text), UPDATE_WORDS)


def extract_symbolic_values(text: str) -> List[str]:
    compact = normalize_text(text)
    symbols = [
        "BM25",
        "FAISS",
        "HNSW",
        "SQLite",
        "PostgreSQL",
        "Milvus",
        "Chroma",
        "向量检索",
        "关键词检索",
        "混合检索",
        "端侧",
        "云端",
        "本地",
        "表格",
        "Markdown",
        "JSON",
        "中文",
        "英文",
        "简洁",
        "详细",
        "V10",
        "V11",
        "API模型",
        "本地模型",
    ]
    found = []
    lower = compact.lower()
    for symbol in symbols:
        if symbol.lower() in lower:
            found.append(symbol)
    return found


def char_jaccard(a: str, b: str) -> float:
    left = set(normalize_text(a))
    right = set(normalize_text(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def scopes_compatible(a: str, b: str) -> bool:
    if not a or not b:
        return True
    if a == b:
        return True
    return "全局" in (a, b)
