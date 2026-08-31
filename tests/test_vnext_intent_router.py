from __future__ import annotations

import pytest

from memoryhub.domain.contracts import LifecycleLayer, MemoryType, RetrievalIntent
from memoryhub.retrieval.intent_router import IntentRouter, RoutedIntent


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


def test_router_supports_seven_intents(router: IntentRouter) -> None:
    intents = router.supported_intents()
    expected = {
        RetrievalIntent.CURRENT_STATE,
        RetrievalIntent.TASK_HISTORY,
        RetrievalIntent.PREFERENCE,
        RetrievalIntent.SEMANTIC_FACT,
        RetrievalIntent.PROCEDURE,
        RetrievalIntent.EXPERIENCE,
        RetrievalIntent.MIXED,
    }
    assert set(intents) == expected


def test_current_state_intent_from_task_query(router: IntentRouter) -> None:
    routed = router.route("我当前的任务是什么", task_id="task-1")
    assert routed.intent is RetrievalIntent.CURRENT_STATE
    assert routed.confidence >= router.HIGH_CONFIDENCE_THRESHOLD
    assert routed.target_layers == [LifecycleLayer.WORKING]
    assert routed.target_types == []
    assert "current" in routed.reason.lower() or "任务" in routed.reason


def test_current_state_intent_for_empty_query_with_task_id(router: IntentRouter) -> None:
    routed = router.route("", task_id="task-1")
    assert routed.intent is RetrievalIntent.CURRENT_STATE
    assert routed.confidence == 1.0


def test_task_history_intent(router: IntentRouter) -> None:
    routed = router.route("这个任务之前做过什么")
    assert routed.intent is RetrievalIntent.TASK_HISTORY
    assert routed.target_layers == [LifecycleLayer.EPISODE]


def test_preference_intent(router: IntentRouter) -> None:
    routed = router.route("正式报告用 DOCX 还是 Markdown")
    assert routed.intent is RetrievalIntent.PREFERENCE
    assert routed.target_types == [MemoryType.PREFERENCE]


def test_semantic_fact_intent(router: IntentRouter) -> None:
    routed = router.route("什么是项目周报")
    assert routed.intent is RetrievalIntent.SEMANTIC_FACT
    assert routed.target_types == [MemoryType.SEMANTIC]


def test_procedure_intent(router: IntentRouter) -> None:
    routed = router.route("生成项目周报的步骤和流程是什么")
    assert routed.intent is RetrievalIntent.PROCEDURE
    assert routed.target_types == [MemoryType.PROCEDURAL]


def test_experience_intent(router: IntentRouter) -> None:
    routed = router.route("之前有没有遇到过类似的问题")
    assert routed.intent is RetrievalIntent.EXPERIENCE
    assert routed.target_types == [MemoryType.EPISODIC]


def test_intent_hint_overrides_rules(router: IntentRouter) -> None:
    # "步骤" alone would trigger PROCEDURE, but hint says SEMANTIC_FACT.
    routed = router.route("部署步骤", intent_hint=RetrievalIntent.SEMANTIC_FACT)
    assert routed.intent is RetrievalIntent.SEMANTIC_FACT
    assert routed.confidence >= router.HIGH_CONFIDENCE_THRESHOLD


def test_mixed_when_intents_are_close(router: IntentRouter) -> None:
    # "what" triggers SEMANTIC_FACT and "steps" triggers PROCEDURE at similar
    # strength, so the sentence should not be collapsed to a single intent.
    routed = router.route("what are the preferred steps for this workflow?")
    assert routed.intent is RetrievalIntent.MIXED
    assert routed.confidence >= router.MIXED_THRESHOLD
    intents_in_mix = {i for i, _ in routed.mixed_intents}
    assert RetrievalIntent.SEMANTIC_FACT in intents_in_mix
    assert RetrievalIntent.PROCEDURE in intents_in_mix


def test_low_confidence_defaults_to_mixed(router: IntentRouter) -> None:
    routed = router.route("hello world")
    assert routed.intent is RetrievalIntent.MIXED
    assert routed.confidence < router.HIGH_CONFIDENCE_THRESHOLD
    assert LifecycleLayer.WORKING in routed.target_layers
    assert LifecycleLayer.LONG_TERM in routed.target_layers


def test_routed_intent_validates_confidence_range() -> None:
    with pytest.raises(ValueError, match="confidence"):
        RoutedIntent(intent=RetrievalIntent.MIXED, confidence=1.5)


def test_llm_scorer_is_used_but_rule_fallback_on_exception() -> None:
    def bad_scorer(query: str) -> tuple[RetrievalIntent, float]:
        raise RuntimeError("llm unavailable")

    r = IntentRouter(llm_scorer=bad_scorer)
    routed = r.route("我当前的任务是什么", task_id="task-1")
    assert routed.intent is RetrievalIntent.CURRENT_STATE


def test_llm_scorer_confidence_is_respected() -> None:
    def strong_scorer(query: str) -> tuple[RetrievalIntent, float]:
        return RetrievalIntent.EXPERIENCE, 0.95

    r = IntentRouter(llm_scorer=strong_scorer)
    routed = r.route("any query")
    assert routed.intent is RetrievalIntent.EXPERIENCE
    assert routed.confidence >= 0.95


def test_common_natural_chinese_queries_route_without_hints() -> None:
    router = IntentRouter()
    cases = {
        "我现在做到哪里了": RetrievalIntent.CURRENT_STATE,
        "我现在进展到哪了": RetrievalIntent.CURRENT_STATE,
        "当前做到哪一步了": RetrievalIntent.CURRENT_STATE,
        "之前这个问题是怎么处理的": RetrievalIntent.TASK_HISTORY,
        "之前遇到过类似问题吗": RetrievalIntent.TASK_HISTORY,
        "上次是怎么解决的": RetrievalIntent.TASK_HISTORY,
        "我一般用 Maven 还是 Gradle": RetrievalIntent.PREFERENCE,
        "我平时更喜欢用什么": RetrievalIntent.PREFERENCE,
        "我之前偏好什么": RetrievalIntent.PREFERENCE,
        "这个项目数据库用什么": RetrievalIntent.SEMANTIC_FACT,
        "项目现在用的是什么数据库": RetrievalIntent.SEMANTIC_FACT,
        "这个项目的技术栈是什么": RetrievalIntent.SEMANTIC_FACT,
    }
    for query, expected in cases.items():
        assert router.route(query).intent is expected, query
