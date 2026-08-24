"""Context budget management and structured context assembly.

The ``BudgetManager`` enforces a token budget while protecting hard
constraints and the current task state.  It partitions the budget into
categories so that critical signals cannot be starved by low-relevance
long-term memories.

The ``StructuredContextBuilder`` turns the budget-approved materials into a
serializable ``ContextPayload`` that downstream consumers can render as text,
JSON, or LLM prompt sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoryhub.adapter.vnext_schemas import ContextPayload, RetrievedMemory
from memoryhub.domain.contracts import MemoryType


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    """Per-category token budgets."""

    current_state: int = 256
    constraints: int = 256
    procedures: int = 512
    long_term_memory: int = 768
    conflict_notes: int = 128
    buffer: int = 64

    def total(self) -> int:
        return (
            self.current_state
            + self.constraints
            + self.procedures
            + self.long_term_memory
            + self.conflict_notes
            + self.buffer
        )


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Result of applying a budget to a set of context materials."""

    selected_memories: list[RetrievedMemory] = field(default_factory=list)
    selected_working_state: dict[str, Any] = field(default_factory=dict)
    selected_constraints: list[str] = field(default_factory=list)
    selected_procedures: list[RetrievedMemory] = field(default_factory=list)
    conflict_notes: list[str] = field(default_factory=list)
    dropped_reasons: dict[str, str] = field(default_factory=dict)
    tokens_by_category: dict[str, int] = field(default_factory=dict)
    total_tokens: int = 0
    remaining_budget: int = 0


def estimate_tokens(obj: Any) -> int:
    """Best-effort token estimate without an external tokenizer.

    Uses a conservative heuristic: 1 token per ~3 UTF-8 characters for
    English/Chinese mixed text.  This is intentionally simple so the budget
    logic can be unit-tested without model dependencies.
    """
    if obj is None:
        return 0
    if isinstance(obj, (int, float, bool)):
        return 1
    if isinstance(obj, dict):
        text = " ".join(f"{k}: {v}" for k, v in obj.items())
    elif isinstance(obj, list):
        text = " ".join(str(item) for item in obj)
    else:
        text = str(obj)
    # Conservative: every 3 characters ~ 1 token, at least 1 token.
    return max(1, len(text.encode("utf-8")) // 3)


class BudgetManager:
    """Protect hard constraints and current state while trimming soft memories."""

    DEFAULT_ALLOCATION: BudgetAllocation = BudgetAllocation()

    def __init__(
        self,
        token_budget: int = 2000,
        allocation: BudgetAllocation | None = None,
    ) -> None:
        self.token_budget = max(128, token_budget)
        self.allocation = allocation or self._scale_allocation(self.token_budget)

    def apply(
        self,
        memories: list[RetrievedMemory],
        *,
        working_state: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        conflict_notes: list[str] | None = None,
    ) -> BudgetResult:
        """Select materials that fit within the token budget.

        Selection order:
        1. Working state (current goal/step/entities) -- hard protected.
        2. Constraints -- hard protected.
        3. Procedures -- high priority long-term memory.
        4. Long-term memories -- ranked by score, trimmed when over budget.
        5. Conflict notes -- only if budget remains.
        """
        working_state = working_state or {}
        constraints = constraints or []
        conflict_notes = conflict_notes or []

        dropped: dict[str, str] = {}
        tokens_by_category: dict[str, int] = {}

        # 1. Current state is protected.
        current_state_tokens = estimate_tokens(working_state)
        tokens_by_category["current_state"] = current_state_tokens

        # 2. Constraints are protected.
        constraint_tokens = estimate_tokens(constraints)
        tokens_by_category["constraints"] = constraint_tokens

        # Compute remaining budget for long-term materials.
        protected_tokens = (
            current_state_tokens
            + constraint_tokens
            + self.allocation.buffer
        )
        remaining = self.token_budget - protected_tokens

        # 3. Procedures get a dedicated quota.
        procedures: list[RetrievedMemory] = []
        procedure_budget = min(self.allocation.procedures, max(0, remaining))
        procedure_candidates = [
            m for m in memories if m.memory_type is MemoryType.PROCEDURAL
        ]
        for candidate in procedure_candidates:
            cost = estimate_tokens(candidate.content)
            if cost <= procedure_budget:
                procedures.append(candidate)
                procedure_budget -= cost
                remaining -= cost
            else:
                dropped[candidate.memory_id] = (
                    "procedure exceeds remaining procedure quota"
                )
        tokens_by_category["procedures"] = sum(
            estimate_tokens(p.content) for p in procedures
        )

        # 4. Long-term memories ranked by score, subject to remaining budget.
        selected_memories: list[RetrievedMemory] = []
        long_term_budget = min(
            self.allocation.long_term_memory,
            max(0, remaining - self.allocation.conflict_notes),
        )
        other_candidates = [
            m
            for m in memories
            if m.memory_type is not MemoryType.PROCEDURAL
        ]
        # Preserve input order (already reranked) but sort by score defensively.
        other_candidates.sort(key=lambda m: m.score, reverse=True)

        for candidate in other_candidates:
            cost = estimate_tokens(candidate.content)
            if cost <= long_term_budget:
                selected_memories.append(candidate)
                long_term_budget -= cost
                remaining -= cost
            else:
                reason = "exceeds long-term memory quota"
                dropped[candidate.memory_id] = reason
        tokens_by_category["long_term_memory"] = sum(
            estimate_tokens(m.content) for m in selected_memories
        )

        # 5. Conflict notes only if budget remains.
        selected_conflict_notes: list[str] = []
        note_budget = max(0, remaining)
        for note in conflict_notes:
            cost = estimate_tokens(note)
            if cost <= note_budget:
                selected_conflict_notes.append(note)
                note_budget -= cost
            else:
                # Conflict notes are not keyed by memory_id; use a synthetic key.
                dropped[f"conflict:{len(dropped)}"] = "conflict note exceeds remaining budget"
        tokens_by_category["conflict_notes"] = sum(
            estimate_tokens(n) for n in selected_conflict_notes
        )

        total = sum(tokens_by_category.values()) + self.allocation.buffer
        return BudgetResult(
            selected_memories=selected_memories,
            selected_working_state=working_state,
            selected_constraints=constraints,
            selected_procedures=procedures,
            conflict_notes=selected_conflict_notes,
            dropped_reasons=dropped,
            tokens_by_category=tokens_by_category,
            total_tokens=total,
            remaining_budget=max(0, self.token_budget - total),
        )

    @classmethod
    def _scale_allocation(cls, token_budget: int) -> BudgetAllocation:
        """Scale default allocation proportionally when budget differs."""
        default = cls.DEFAULT_ALLOCATION
        default_total = default.total()
        if default_total == 0 or token_budget >= default_total:
            return default
        ratio = token_budget / default_total
        return BudgetAllocation(
            current_state=int(default.current_state * ratio),
            constraints=int(default.constraints * ratio),
            procedures=int(default.procedures * ratio),
            long_term_memory=int(default.long_term_memory * ratio),
            conflict_notes=int(default.conflict_notes * ratio),
            buffer=int(default.buffer * ratio),
        )


class StructuredContextBuilder:
    """Assemble a deterministic, explainable ContextPayload."""

    def __init__(self, budget_manager: BudgetManager | None = None) -> None:
        self.budget_manager = budget_manager or BudgetManager()

    def build(
        self,
        memories: list[RetrievedMemory],
        *,
        working_state: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        conflict_notes: list[str] | None = None,
    ) -> ContextPayload:
        """Build the structured context and render a compatible text view."""
        budget_result = self.budget_manager.apply(
            memories,
            working_state=working_state,
            constraints=constraints,
            conflict_notes=conflict_notes,
        )
        rendered = self._render(budget_result)
        original_tokens = sum(estimate_tokens(m.content) for m in memories)
        original_tokens += estimate_tokens(working_state)
        original_tokens += estimate_tokens(constraints)
        original_tokens += estimate_tokens(conflict_notes)

        relevant_memory_ids = [
            m.memory_id for m in budget_result.selected_memories
        ] + [m.memory_id for m in budget_result.selected_procedures]
        source_ids = sorted(
            {
                source_id
                for m in budget_result.selected_memories + budget_result.selected_procedures
                for source_id in m.source_ids
            }
        )

        return ContextPayload(
            current_state=budget_result.selected_working_state,
            constraints=budget_result.selected_constraints,
            relevant_memory_ids=relevant_memory_ids,
            conflict_notes=budget_result.conflict_notes,
            source_ids=source_ids,
            rendered_context=rendered,
            original_tokens=original_tokens,
            selected_tokens=sum(budget_result.tokens_by_category.values()),
            dropped_reasons=budget_result.dropped_reasons,
        )

    @staticmethod
    def _render(result: BudgetResult) -> str:
        parts: list[str] = []

        current = result.selected_working_state
        if current:
            parts.append("# Current State")
            for key, value in current.items():
                parts.append(f"{key}: {value}")
            parts.append("")

        if result.selected_constraints:
            parts.append("# Constraints")
            for constraint in result.selected_constraints:
                parts.append(f"- {constraint}")
            parts.append("")

        if result.selected_procedures:
            parts.append("# Procedures")
            for proc in result.selected_procedures:
                parts.append(f"- [{proc.memory_id}] {proc.content}")
            parts.append("")

        if result.selected_memories:
            parts.append("# Relevant Memory")
            for memory in result.selected_memories:
                line = (
                    f"- [{memory.memory_id}] ({memory.memory_type.value}) "
                    f"score={memory.score} {memory.content}"
                )
                parts.append(line)
            parts.append("")

        if result.conflict_notes:
            parts.append("# Conflict Notes")
            for note in result.conflict_notes:
                parts.append(f"- {note}")
            parts.append("")

        return "\n".join(parts).strip()


__all__ = [
    "BudgetAllocation",
    "BudgetManager",
    "BudgetResult",
    "StructuredContextBuilder",
    "estimate_tokens",
]
