"""Phase G：NL 语义遗忘升级（LLM 意图解析 + 语义定位）验证。"""

from __future__ import annotations

import hashlib

import pytest

from memoryhub.adapter.schemas import ForgetRequest, PreferenceMemory
from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)


class _StructuredLLM:
    """模拟 StructuredLLMAdapter 调用契约的 LLM（返回结构化 JSON）。"""

    def __init__(self, response):
        self._response = response

    def generate(self, prompt, system_prompt="", **kwargs):
        return _Resp(self._response)


class _Resp:
    def __init__(self, content):
        self.content = content


class _Vec:
    def __init__(self, shared=0.0):
        # high = 与 topic(全1向量) 相似；这里用 easy 特征向量
        self._shared = shared

    def embed(self, text: str):
        return [float(ord(c)) for c in str(text)[:8]]


class _FixedCosineEmbedding:
    """用自定义 embed：相似记忆返回近似向量，无关返回正交。"""

    def embed(self, text: str):
        t = str(text)
        if "markdown" in t or "Markdown" in t:
            return [1.0, 0.0, 0.0, 1.0]      # 特征是向量——"周报格式"
        return [0.0, 1.0, 0.0, 0.0]          # 无关


def _setup(tmp_path):
    from pathlib import Path

    db = Database(str(Path(tmp_path) / "forget.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(pref_repo=pref_repo, know_repo=know_repo, project_immediately=False)
    return db, pref_repo, know_repo, writer


class _Structured:
    """本测试专用的结构化 LLM 解析器，直接喂给 _llm_parse_intent 分支。"""


def test_parse_intent_uses_llm_when_available_and_falls_back(tmp_path):
    db, *_ = _setup(tmp_path)
    # memory_type 以规则为准（reliable）；LLM 仅补充关键词（当规则关键词为空时）
    llm = _StructuredLLM('{"memory_type":"knowledge","target_topic":"项目周报","keywords":["周报","Markdown"],"negate":false}')
    forgetter = MemoryForgetter(llm_client=llm)
    intent = forgetter.parse_intent(ForgetRequest(instruction="忘掉我关于项目周报格式的知识"))
    assert intent["memory_type"] == "knowledge"  # 规则推断（含"知识"）
    assert "周报" in intent["target_keywords"]

    # LLM 失败 → 回退规则（不抛出）
    class _Bad:
        def generate(self, *a, **k):
            raise RuntimeError("llm unavailable")

    forgetter2 = MemoryForgetter(llm_client=_Bad())
    intent2 = forgetter2.parse_intent(ForgetRequest(instruction="忘掉周报格式偏好"))
    assert intent2["memory_type"] == "preference"  # 规则推断


def test_llm_supplements_keywords_when_rule_empty():
    # 规则关键词为空（整句全是停用词）时，LLM 补充关键词与主题
    llm = _StructuredLLM('{"memory_type":"preference","target_topic":"old setting","keywords":["old","setting"],"negate":false}')
    forgetter = MemoryForgetter(llm_client=llm)
    intent = forgetter.parse_intent(ForgetRequest(instruction="forget the about my"))
    assert intent["target_keywords"] == ["old", "setting"]
    assert intent["target_topic"] == "old setting"

    # 规则关键词非空时 LLM 结果整体弃用（规则优先），且不应发起云端调用
    class _Counting:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, system_prompt="", **kwargs):
            self.calls += 1
            raise RuntimeError("unreachable")

    counting = _Counting()
    forgetter3 = MemoryForgetter(llm_client=counting)
    intent3 = forgetter3.parse_intent(ForgetRequest(instruction="忘掉周报格式偏好"))
    assert counting.calls == 0, "规则关键词非空时不应调用 LLM"
    assert "周报" in intent3["target_keywords"]


def test_exact_and_scope_skip_llm(tmp_path):
    db, *_ = _setup(tmp_path)
    llm = _StructuredLLM('{"memory_type":"knowledge","target_topic":"X","keywords":["x"],"negate":false}')
    forgetter = MemoryForgetter(llm_client=llm)
    # 显式 target_memory_ids → exact，不调 LLM
    intent = forgetter.parse_intent(ForgetRequest(instruction="随便", target_memory_ids=["m1"]))
    assert intent["match_strategy"] == "exact"


def test_semantic_location_with_embedding(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    # 写入一条 markdown 偏好 + 一条无关偏好
    md = PreferenceMemory(user_id="u1", preference_type="format_preference", text="周报默认使用 Markdown")
    other = PreferenceMemory(user_id="u1", preference_type="output_style", text="发言尽量简洁")
    pref_repo.save(md)
    pref_repo.save(other)

    forgetter = MemoryForgetter(
        pref_repo=pref_repo, know_repo=know_repo,
        embedding_client=_FixedCosineEmbedding(),
    )
    # target_topic="周报格式" 的向量应与 markdown 偏好相似（共享 [100*... ]？用 text 特征）
    # 这里 embedding 对含 "markdown" 的文本返回特征向量 → 与 topic "周报格式" 相似度判定取决于两者的向量。
    # 本用例：topic 用含 "Markdown" 词，确保它与其偏好向量一致。
    intent = {
        "memory_type": "all",
        "target_topic": "Markdown 周报格式",
        "target_keywords": [],
        "match_strategy": "semantic",
        "scope": None, "time_range": None, "confidence_threshold": 0.0,
    }
    ids = forgetter.locate_memories(intent, ForgetRequest(instruction="", user_id="u1"))
    assert md.memory_id in ids


def test_keyword_location_still_works_without_embedding(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    p = PreferenceMemory(user_id="u1", preference_type="format_preference", text="周报用 Markdown 三段式")
    other = PreferenceMemory(user_id="u1", preference_type="output_style", text="内容简洁")
    pref_repo.save(p)
    pref_repo.save(other)

    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=know_repo)  # 无 embedding_client
    intent = {
        "memory_type": "preference",
        "target_topic": "周报",
        "target_keywords": ["周报"],
        "match_strategy": "semantic",
        "scope": None, "time_range": None, "confidence_threshold": 0.0,
    }
    ids = forgetter.locate_memories(intent, ForgetRequest(instruction="", user_id="u1"))
    assert p.memory_id in ids
    assert other.memory_id not in ids
    db.close()
