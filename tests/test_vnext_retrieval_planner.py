from __future__ import annotations

import pytest

from memoryhub.adapter.vnext_schemas import ConsistencyMode, MemoryRetrievalRequest
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType, RetrievalIntent
from memoryhub.retrieval.intent_router import IntentRouter
from memoryhub.retrieval.planner import RetrievalPlanner


@pytest.fixture
def planner() -> RetrievalPlanner:
    return RetrievalPlanner()


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter()


def _request(
    *,
    query: str = "",
    intent_hint: RetrievalIntent | None = None,
    consistency: ConsistencyMode = ConsistencyMode.EVENTUAL,
) -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id="req-1",
        tenant_id="tenant-a",
        user_id="user-a",
        query=query,
        intent_hint=intent_hint,
        consistency=consistency,
    )


def test_current_state_uses_working_and_metadata(planner: RetrievalPlanner) -> None:
    request = _request(query="我当前的任务是什么")
    routed = IntentRouter().route(request.query, task_id="task-1")
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.CURRENT_STATE
    assert "working" in plan.enabled_channels
    assert "metadata" in plan.enabled_channels
    assert "vector" not in plan.enabled_channels
    assert plan.required_layers == [LifecycleLayer.WORKING]


def test_task_history_uses_episode_and_metadata(planner: RetrievalPlanner) -> None:
    request = _request(query="这个任务之前做过什么")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.TASK_HISTORY
    assert "episode" in plan.enabled_channels
    assert "metadata" in plan.enabled_channels
    assert "vector" not in plan.enabled_channels
    assert plan.required_layers == [LifecycleLayer.EPISODE]


def test_preference_uses_long_term_channels(planner: RetrievalPlanner) -> None:
    request = _request(query="正式报告用 DOCX")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.PREFERENCE
    assert set(plan.enabled_channels) == {"vector", "keyword", "metadata", "authority"}
    assert plan.required_types == [MemoryType.PREFERENCE]


def test_procedure_uses_long_term_channels(planner: RetrievalPlanner) -> None:
    request = _request(query="生成项目周报的步骤和流程")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.PROCEDURE
    assert set(plan.enabled_channels) == {"vector", "keyword", "metadata", "authority"}
    assert plan.required_types == [MemoryType.PROCEDURAL]


def test_experience_uses_episode_plus_long_term_channels(planner: RetrievalPlanner) -> None:
    request = _request(query="之前有没有遇到过类似的问题")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.EXPERIENCE
    assert set(plan.enabled_channels) == {"vector", "keyword", "metadata", "authority", "episode"}
    assert plan.required_types == [MemoryType.EPISODIC]


def test_mixed_enables_all_channels(planner: RetrievalPlanner) -> None:
    request = _request(query="hello world")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.intent is RetrievalIntent.MIXED
    assert set(plan.enabled_channels) == set(RetrievalPlanner.ALL_CHANNELS)
    assert set(plan.required_layers) == {
        LifecycleLayer.WORKING,
        LifecycleLayer.EPISODE,
        LifecycleLayer.LONG_TERM,
    }


def test_authority_checked_adds_authority_channel(planner: RetrievalPlanner) -> None:
    request = _request(
        query="我当前的任务是什么",
        intent_hint=RetrievalIntent.CURRENT_STATE,
        consistency=ConsistencyMode.AUTHORITY_CHECKED,
    )
    routed = IntentRouter().route(request.query, task_id="task-1", intent_hint=request.intent_hint)
    plan = planner.plan(request, routed)

    assert plan.authority_checked is True
    assert "authority" in plan.enabled_channels
    assert "working" in plan.enabled_channels


def test_unavailable_channels_are_reported_as_degraded() -> None:
    planner = RetrievalPlanner(available_channels=["working", "metadata"])
    request = _request(query="我当前的任务是什么")
    routed = IntentRouter().route(request.query, task_id="task-1")
    plan = planner.plan(request, routed)

    assert set(plan.enabled_channels) == {"working", "metadata"}
    # Vector/keyword are not requested for CURRENT_STATE, so they are neither
    # enabled nor degraded; unavailable requested channels are what matter.
    assert "vector" not in plan.enabled_channels
    assert "keyword" not in plan.enabled_channels


def test_degraded_channels_listed_when_requested_channel_missing() -> None:
    planner = RetrievalPlanner(available_channels=["metadata", "authority"])
    request = _request(query="正式报告用 DOCX")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert "vector" in plan.degraded_channels
    assert "keyword" in plan.degraded_channels
    assert set(plan.enabled_channels) == {"metadata", "authority"}
    assert "degraded" in plan.reason


def test_metadata_filter_includes_scope_and_layers() -> None:
    planner = RetrievalPlanner()
    request = MemoryRetrievalRequest(
        request_id="req-1",
        tenant_id="tenant-a",
        user_id="user-a",
        query="preferred format",
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        intent_hint=RetrievalIntent.PREFERENCE,
    )
    routed = IntentRouter().route(
        request.query,
        intent_hint=RetrievalIntent.PREFERENCE,
    )
    plan = planner.plan(request, routed)

    assert plan.metadata_filter["scope_level"] == "PROJECT"
    assert plan.metadata_filter["scope"] == "PROJECT:reporting"
    assert plan.metadata_filter["tenant_id"] == "tenant-a"
    assert plan.metadata_filter["user_id"] == "user-a"


def test_top_k_respects_request_page_size() -> None:
    planner = RetrievalPlanner()
    request = MemoryRetrievalRequest(
        request_id="req-1",
        tenant_id="tenant-a",
        user_id="user-a",
        query="what is X",
        page_size=7,
    )
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert plan.top_k == 7
    assert plan.vector_top_k == 14
    assert plan.keyword_top_k == 14


def test_production_mode_degrades_vector_when_milvus_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a non-Milvus environment by making the import fail.
    monkeypatch.setattr(
        "builtins.__import__",
        lambda name, *args, **kwargs: __builtins__.__import__(name, *args, **kwargs)
        if "milvus_hybrid" not in name
        else (_ for _ in ()).throw(ImportError("no milvus")),
    )
    planner = RetrievalPlanner(production_mode=True, production_requires_milvus=True)
    request = _request(query="什么是项目周报")
    routed = IntentRouter().route(request.query)
    plan = planner.plan(request, routed)

    assert "vector" in plan.degraded_channels
    assert "vector" not in plan.enabled_channels
