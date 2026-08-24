"""Tests for S3-07 Context Service end-to-end assembly."""

from __future__ import annotations

import pytest

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.context_service import ContextService
from memoryhub.domain.contracts import (
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.context_builder import BudgetManager
from memoryhub.retrieval.planner import RetrievalPlan


def _memory(
    memory_id: str,
    *,
    score: float = 0.5,
    version: int = 1,
    layer: LifecycleLayer = LifecycleLayer.LONG_TERM,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
    status: str = "ACTIVE",
    normalized_key: str = "",
    content: dict | None = None,
) -> RetrievedMemory:
    content = content or {"text": f"content of {memory_id}"}
    if normalized_key:
        content["normalized_key"] = normalized_key
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=memory_type,
        layer=layer,
        scope_level=scope_level,
        scope=scope,
        content_version=version,
        evolution_status=status,
        content=content,
        score=score,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


@pytest.fixture
def request_obj():
    return MemoryRetrievalRequest(
        request_id="r1",
        tenant_id="tenant-1",
        user_id="user-1",
        query="how to format report",
        task_id="task-1",
        intent_hint=RetrievalIntent.PREFERENCE,
        token_budget=1000,
    )


@pytest.fixture
def plan():
    return RetrievalPlan(
        intent=RetrievalIntent.PREFERENCE,
        enabled_channels=["vector", "metadata"],
        top_k=5,
    )


class TestContextService:
    def test_end_to_end_assembly(self, request_obj, plan):
        service = ContextService(
            budget_manager=BudgetManager(token_budget=1000)
        )
        channel_results = {
            "vector": [
                _memory(
                    "m1",
                    score=0.9,
                    memory_type=MemoryType.PREFERENCE,
                    content={"text": "use markdown"},
                ),
                _memory(
                    "m2",
                    score=0.7,
                    memory_type=MemoryType.SEMANTIC,
                    content={"text": "markdown is a format"},
                ),
            ],
            "metadata": [
                _memory(
                    "m1",
                    score=0.5,
                    memory_type=MemoryType.PREFERENCE,
                    content={"text": "use markdown"},
                ),
            ],
        }
        result = service.build_context(
            request=request_obj,
            plan=plan,
            channel_results=channel_results,
            working_state={"goal": "write report", "current_step": "format"},
            constraints=["use docx"],
        )

        assert result.context is not None
        # m1 appears in two channels; it should be deduplicated.
        ids = result.context.relevant_memory_ids
        assert len(ids) == len(set(ids))
        assert "m1" in ids
        assert result.context.rendered_context
        assert result.context.selected_tokens <= request_obj.token_budget
        assert result.trace["fusion_candidates"] == 3
        assert result.trace["fusion_deduplicated"] == 2

    def test_deleted_memory_dropped_from_context(self, request_obj, plan):
        service = ContextService()
        channel_results = {
            "vector": [
                _memory("m1", status="DELETED"),
                _memory("m2", status="ACTIVE"),
            ],
        }
        result = service.build_context(
            request=request_obj,
            plan=plan,
            channel_results=channel_results,
        )
        ids = result.context.relevant_memory_ids
        assert "m1" not in ids
        assert "m2" in ids
        assert "authority" in result.stage_dropped
        assert "DELETED" in result.stage_dropped["authority"]["m1"]

    def test_conflict_resolution_keeps_narrower_scope(self, request_obj, plan):
        service = ContextService()
        channel_results = {
            "vector": [
                _memory(
                    "global_pref",
                    memory_type=MemoryType.PREFERENCE,
                    scope_level=MemoryScope.GLOBAL,
                    scope="GLOBAL",
                    normalized_key="format",
                ),
                _memory(
                    "project_pref",
                    memory_type=MemoryType.PREFERENCE,
                    scope_level=MemoryScope.PROJECT,
                    scope="PROJECT:p1",
                    normalized_key="format",
                ),
            ],
        }
        result = service.build_context(
            request=request_obj,
            plan=plan,
            channel_results=channel_results,
        )
        ids = result.context.relevant_memory_ids
        assert "project_pref" in ids
        assert "global_pref" not in ids
        assert result.scope_resolution is not None
        assert len(result.scope_resolution.dropped) == 1

    def test_hard_constraints_preserved_under_budget_pressure(
        self, request_obj, plan
    ):
        # Tiny budget still must keep working state and constraints.
        service = ContextService(
            budget_manager=BudgetManager(token_budget=256)
        )
        channel_results = {
            "vector": [
                _memory(
                    "m1",
                    memory_type=MemoryType.PREFERENCE,
                    content={"text": "x" * 1000},
                ),
            ],
        }
        result = service.build_context(
            request=request_obj,
            plan=plan,
            channel_results=channel_results,
            working_state={"goal": "finish report"},
            constraints=["must use docx"],
        )
        assert result.context.current_state["goal"] == "finish report"
        assert "must use docx" in result.context.constraints
        assert result.context.selected_tokens <= request_obj.token_budget

    def test_trace_contains_stage_metrics(self, request_obj, plan):
        service = ContextService()
        result = service.build_context(
            request=request_obj,
            plan=plan,
            channel_results={"vector": [_memory("m1")]},
        )
        trace = result.trace
        assert "fusion_candidates" in trace
        assert "reranked_count" in trace
        assert "scope_selected_count" in trace
        assert "budget_tokens" in trace
