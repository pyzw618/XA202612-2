"""Tests for S3-06 Context Budget Manager and Structured Context Builder."""

from __future__ import annotations

from memoryhub.adapter.vnext_schemas import RetrievedMemory
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType
from memoryhub.retrieval.context_builder import (
    BudgetManager,
    StructuredContextBuilder,
    estimate_tokens,
)


def _memory(
    memory_id: str,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    content: dict | None = None,
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=memory_type,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        content_version=1,
        evolution_status="ACTIVE",
        content=content or {"text": f"content of {memory_id}"},
        score=0.5,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


class TestTokenEstimation:
    def test_empty_returns_zero(self):
        assert estimate_tokens(None) == 0
        assert estimate_tokens("") == 1  # minimum token

    def test_text_estimate(self):
        # ~12 bytes -> 4 tokens (byte//3)
        assert estimate_tokens("hello world!") == 4

    def test_dict_estimate(self):
        value = {"text": "hello world!"}
        assert estimate_tokens(value) >= 1


class TestBudgetManager:
    def test_working_state_and_constraints_always_kept(self):
        manager = BudgetManager(token_budget=200)
        working = {"goal": "make report", "current_step": "gather data"}
        constraints = ["use docx"]
        result = manager.apply([], working_state=working, constraints=constraints)
        assert result.selected_working_state == working
        assert result.selected_constraints == constraints
        assert result.total_tokens > 0

    def test_procedures_get_dedicated_quota(self):
        manager = BudgetManager(token_budget=500)
        proc = _memory(
            "proc1",
            MemoryType.PROCEDURAL,
            content={"text": "step one step two step three"},
        )
        result = manager.apply([proc])
        assert len(result.selected_procedures) == 1
        assert result.tokens_by_category["procedures"] > 0

    def test_long_term_memory_trimmed_when_over_budget(self):
        # Very small budget forces trimming.
        manager = BudgetManager(token_budget=300)
        constraints = ["use docx"] * 50
        memories = [
            _memory(f"m{i}", content={"text": "x" * 200}) for i in range(10)
        ]
        result = manager.apply(memories, constraints=constraints)
        assert len(result.dropped_reasons) > 0
        assert len(result.selected_memories) < len(memories)

    def test_budget_result_tracks_tokens(self):
        manager = BudgetManager(token_budget=2000)
        result = manager.apply([], working_state={"goal": "x"})
        assert result.total_tokens <= 2000
        assert result.remaining_budget >= 0


class TestStructuredContextBuilder:
    def test_builds_context_payload(self):
        manager = BudgetManager(token_budget=2000)
        builder = StructuredContextBuilder(budget_manager=manager)
        memories = [
            _memory(
                "m1",
                content={"text": "prefer markdown for reports"},
            ),
        ]
        payload = builder.build(
            memories,
            working_state={"goal": "write report"},
            constraints=["use markdown"],
            conflict_notes=["global vs project preference"],
        )
        assert payload.current_state["goal"] == "write report"
        assert "use markdown" in payload.constraints
        assert "m1" in payload.relevant_memory_ids
        assert payload.rendered_context
        assert payload.original_tokens >= payload.selected_tokens

    def test_rendered_context_has_sections(self):
        manager = BudgetManager(token_budget=2000)
        builder = StructuredContextBuilder(budget_manager=manager)
        proc = _memory(
            "p1",
            MemoryType.PROCEDURAL,
            content={"text": "do this"},
        )
        payload = builder.build(
            [proc],
            working_state={"goal": "fix bug"},
            constraints=["backup first"],
        )
        assert "# Current State" in payload.rendered_context
        assert "# Constraints" in payload.rendered_context
        assert "# Procedures" in payload.rendered_context

    def test_source_ids_collected(self):
        builder = StructuredContextBuilder()
        m = _memory("m1", content={"text": "x"})
        payload = builder.build([m])
        assert "src:m1" in payload.source_ids


class TestBudgetScaling:
    def test_small_budget_scales_allocation(self):
        manager = BudgetManager(token_budget=256)
        assert manager.allocation.total() <= 256
        # Current state and constraints should still be represented, even if tiny.
        assert manager.allocation.current_state > 0
