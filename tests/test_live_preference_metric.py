"""偏好提取判分逻辑的离线单元测试。

核心要求：判分必须基于**规格字段**而非文本字面量。旧 showcase 数据集用
"expected_output 是抽取器固定输出串 + 子串匹配"判分，同义改写被判错、抄来的
标签必然判对，本模块的比较方式正是要避免这一点。
"""

from __future__ import annotations

import pytest

from evaluation.live.metrics_preference import (
    build_event,
    canonical_target,
    canonical_value,
    case_user,
    compare_case,
)
from evaluation.live.seeding import EvalUser

USER = EvalUser(user_id="run", run_tag="run")


def _case(**overrides):
    case = {
        "case_id": "c1",
        "block": "rule_hit",
        "input_text": "以后都用 Markdown 写周报",
        "expected_found": True,
        "expected_type_any_of": ["format_preference"],
        "expected_target": "output_format",
        "expected_value": "MARKDOWN",
        "expected_global": True,
    }
    case.update(overrides)
    return case


def _pref(**overrides):
    pref = {
        "memory_id": "m1",
        "preference_type": "format_preference",
        "text": "偏好使用 MARKDOWN 格式进行数据输出。",
        "payload": {"action": "set_format", "target": "output_format", "value": "markdown"},
        "is_global": True,
        "extract_source": "explicit_feedback",
    }
    pref.update(overrides)
    return pref


# ------------------------------------------------------------ 归一化


def test_target_synonyms_normalise_to_one_form() -> None:
    assert canonical_target("format") == canonical_target("output_format") == "output_format"
    assert canonical_target("敏感数据") == "sensitive_data"


def test_value_normalisation_is_case_insensitive() -> None:
    assert canonical_value("markdown") == canonical_value("MARKDOWN") == "MARKDOWN"
    assert canonical_value("restricted") == "FORBIDDEN"


# ------------------------------------------------------------ 判定


def test_paraphrased_text_still_matches_on_spec_fields() -> None:
    """文本措辞不同但类型/target/value 一致 → 判对。"""
    observed = [_pref(text="用户希望所有输出都采用 Markdown 排版")]
    assert compare_case(_case(), observed)["correct"] is True


def test_type_mismatch_fails() -> None:
    observed = [_pref(preference_type="safety_preference")]
    result = compare_case(_case(), observed)
    assert result["correct"] is False
    assert result["reason"] == "fields_mismatch"


def test_value_mismatch_fails() -> None:
    observed = [_pref(payload={"target": "output_format", "value": "html"})]
    assert compare_case(_case(), observed)["correct"] is False


def test_target_mismatch_fails() -> None:
    observed = [_pref(payload={"target": "sensitive_data", "value": "markdown"})]
    assert compare_case(_case(), observed)["correct"] is False


def test_global_tri_state_is_not_asserted_when_none() -> None:
    case = _case(expected_global=None)
    assert compare_case(case, [_pref(is_global=False)])["correct"] is True
    assert compare_case(case, [_pref(is_global=True)])["correct"] is True


def test_global_is_asserted_when_boolean() -> None:
    assert compare_case(_case(expected_global=False), [_pref(is_global=True)])["correct"] is False
    assert compare_case(_case(expected_global=False), [_pref(is_global=False)])["correct"] is True


def test_hard_negative_requires_absence() -> None:
    case = _case(block="hard_negative", expected_found=False, expected_type_any_of=[])
    clean = compare_case(case, [])
    assert clean["correct"] is True and clean["reason"] == "no_preference_expected"

    noisy = compare_case(case, [_pref()])
    assert noisy["correct"] is False and noisy["reason"] == "over_extraction"


def test_nothing_extracted_is_not_a_pass() -> None:
    result = compare_case(_case(), [])
    assert result["correct"] is False
    assert result["reason"] == "nothing_extracted"


def test_diagnostic_similarity_is_recorded_but_not_scored() -> None:
    """文本相似度只作诊断，不参与判分——措辞不同也应判对。"""
    low_overlap = [_pref(text="完全不同的用词表述")]
    result = compare_case(_case(), low_overlap)
    assert result["correct"] is True
    assert result["diagnostic_text_similarity"] >= 0.0


def test_match_across_multiple_candidates() -> None:
    observed = [
        _pref(memory_id="m0", preference_type="safety_preference"),
        _pref(memory_id="m1"),
    ]
    result = compare_case(_case(), observed)
    assert result["correct"] is True
    assert result["matched_memory_id"] == "m1"


# ------------------------------------------------------------ 身份隔离


def test_case_users_are_distinct_per_case() -> None:
    """逐条派生的身份必须互不相同，否则会命中冲突/合并机制导致漏报。"""
    a = case_user(USER, "c1")
    b = case_user(USER, "c2")
    assert a.user_id != b.user_id
    assert a.user_id.startswith(USER.user_id)
    assert b.run_tag.startswith(USER.run_tag)


def test_event_source_hash_is_unique_per_case() -> None:
    first = build_event("c1", "文本", USER)
    second = build_event("c2", "文本", USER)
    assert first["source_hash"] != second["source_hash"]
    assert len(first["source_hash"]) == 64


def test_event_carries_eval_user_and_no_structured_payload() -> None:
    """事件不得携带结构化偏好载荷——那会绕过抽取，得到无意义的满分。"""
    event = build_event("c1", "文本", USER)
    assert event["user_id"] == USER.user_id
    assert "preferences" not in (event.get("payload") or {})
    assert "knowledge" not in (event.get("payload") or {})
