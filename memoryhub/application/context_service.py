"""vNext Context Service: assembles structured context from raw recall results.

The service is the orchestration layer for S3-04..S3-06 components.  Given a
retrieval plan and per-channel candidates it produces an explainable,
budget-respecting ``ContextPayload``.  Every stage records why memories were
kept or dropped so that downstream Activation/Trace can be audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoryhub.adapter.vnext_schemas import (
    ContextPayload,
    MemoryRetrievalRequest,
    RetrievedMemory,
)
from memoryhub.domain.contracts import LifecycleLayer
from memoryhub.retrieval.context_builder import BudgetManager, StructuredContextBuilder
from memoryhub.retrieval.fusion import FusionResult, ReciprocalRankFusion
from memoryhub.retrieval.planner import RetrievalPlan
from memoryhub.retrieval.reranker import VNextReranker
from memoryhub.retrieval.scope_resolver import ScopeResolution, ScopeResolver
from memoryhub.storage.authority_repository import AuthorityRepository


@dataclass(frozen=True, slots=True)
class ContextAssemblyResult:
    """Full traceable output of the context assembly pipeline."""

    context: ContextPayload
    fusion: FusionResult | None = None
    scope_resolution: ScopeResolution | None = None
    stage_dropped: dict[str, dict[str, str]] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


class ContextService:
    """Build structured context from a retrieval plan and channel candidates.

    The service is deliberately composed of replaceable stages:

    1. **Fusion** -- deduplicate and combine per-channel scores.
    2. **Rerank** -- apply relevance, scope, confidence, freshness, health.
    3. **Scope resolution** -- remove blocked statuses and resolve conflicts.
    4. **Budget** -- protect hard constraints and current state, trim soft memory.
    5. **Render** -- produce a structured ``ContextPayload``.

    Callers may supply their own stage implementations; sensible defaults are
    provided for the vNext pipeline.
    """

    def __init__(
        self,
        *,
        fusion_engine: ReciprocalRankFusion | None = None,
        reranker: VNextReranker | None = None,
        scope_resolver: ScopeResolver | None = None,
        budget_manager: BudgetManager | None = None,
        authority_repository: AuthorityRepository | None = None,
        repair_callback: Any | None = None,
    ) -> None:
        self.fusion_engine = fusion_engine or ReciprocalRankFusion()
        self.reranker = reranker or VNextReranker()
        self.scope_resolver = scope_resolver or ScopeResolver()
        self.authority_repository = authority_repository
        self.repair_callback = repair_callback
        # A supplied manager is an explicit application policy.  Otherwise the
        # request owns the budget, so it must be constructed per retrieval.
        self.budget_manager = budget_manager

    def build_context(
        self,
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel_results: dict[str, list[RetrievedMemory]],
        *,
        working_state: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        conflict_notes: list[str] | None = None,
    ) -> ContextAssemblyResult:
        """Assemble context with full traceability."""
        stage_dropped: dict[str, dict[str, str]] = {}

        # 1. Fusion
        fusion = self.fusion_engine.fuse(
            channel_results,
            top_k=plan.top_k * 2 or 20,
            channel_weights=self._channel_weights(plan.intent.value),
        )

        # 2. Rerank
        reranked = self.reranker.rerank(
            fusion.memories,
            query=request.query,
            scope_level=request.scope_level,
            scope=request.scope,
            task_id=request.task_id,
            top_k=plan.top_k,
            intent=plan.intent.value,
            intent_type_boosts=self._intent_type_boosts(plan.intent.value),
        )

        # 3. Scope resolution
        if plan.authority_checked and self.authority_repository is not None:
            scope_resolver = ScopeResolver(
                authority_repository=self.authority_repository,
                authority_checked=True,
                repair_callback=self.repair_callback,
            )
        else:
            scope_resolver = self.scope_resolver
        scope_resolution = scope_resolver.resolve(
            reranked,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            preferred_scope_level=request.scope_level,
            preferred_scope=request.scope,
        )
        if scope_resolution.dropped:
            stage_dropped["scope"] = {
                memory.memory_id: reason
                for memory, reason in scope_resolution.dropped
            }
        if scope_resolution.invalid:
            stage_dropped["authority"] = {
                result.memory.memory_id: result.reason
                for result in scope_resolution.invalid
            }

        # 4/5. Budget + structured context
        context_builder = StructuredContextBuilder(
            budget_manager=self.budget_manager
            or BudgetManager(token_budget=request.token_budget)
        )
        context = context_builder.build(
            scope_resolution.selected,
            working_state=working_state or {},
            constraints=constraints or [],
            conflict_notes=conflict_notes or [],
        )
        if context.dropped_reasons:
            stage_dropped["budget"] = dict(context.dropped_reasons)

        trace = {
            "intent": plan.intent.value,
            "enabled_channels": plan.enabled_channels,
            "authority_checked": plan.authority_checked,
            "fusion_candidates": fusion.total_candidates,
            "fusion_deduplicated": fusion.deduplicated_count,
            "reranked_count": len(reranked),
            "scope_selected_count": len(scope_resolution.selected),
            "scope_invalid_count": len(scope_resolution.invalid),
            "budget_tokens": context.selected_tokens,
            "budget_remaining": max(0, request.token_budget - context.selected_tokens),
            "relevant_memory_ids": context.relevant_memory_ids,
        }

        return ContextAssemblyResult(
            context=context,
            fusion=fusion,
            scope_resolution=scope_resolution,
            stage_dropped=stage_dropped,
            trace=trace,
        )

    @staticmethod
    def _channel_weights(intent: str) -> dict[str, float]:
        """Keep intent-specific channel priority explicit and explainable."""
        defaults = {
            "working": 1.0,
            "episode": 1.0,
            "authority": 1.0,
            "keyword": 1.0,
            "metadata": 1.0,
            "vector": 1.0,
        }
        preferred = {
            "CURRENT_STATE": ("working", "episode", "authority", "vector"),
            "TASK_HISTORY": ("episode", "working", "authority", "vector"),
            "PREFERENCE": ("authority", "keyword", "metadata", "vector"),
            "SEMANTIC_FACT": ("authority", "vector", "keyword", "metadata"),
            "PROCEDURE": ("authority", "episode", "keyword", "vector"),
            "EXPERIENCE": ("episode", "authority", "vector", "keyword"),
        }.get(intent, ())
        for rank, channel in enumerate(preferred):
            defaults[channel] = 1.35 - 0.1 * rank
        return defaults

    @staticmethod
    def _intent_type_boosts(intent: str) -> dict[str, dict[str, float]]:
        """Intent-aware type boosts that protect structurally important layers.

        These boosts are multipliers on the weighted rerank score (capped at 1.0).
        They compensate for the deliberately low default weights of WORKING/EPISODE
        so that state/history queries can keep their primary source memories in
        the top_k that reaches the context budget.
        """
        return {
            "CURRENT_STATE": {"WORKING": 2.0},
            "TASK_HISTORY": {"EPISODE": 2.0},
            "PREFERENCE": {"PREFERENCE": 1.5},
            "SEMANTIC_FACT": {"SEMANTIC": 1.5},
            "PROCEDURE": {"PROCEDURAL": 1.5},
            "EXPERIENCE": {"EPISODIC": 1.5},
            "MIXED": {"WORKING": 1.5, "EPISODE": 1.5},
        }

    @staticmethod
    def extract_working_state(
        working_snapshot: Any | None,
    ) -> dict[str, Any]:
        """Convert a WorkingSnapshot to the context current_state map."""
        if working_snapshot is None:
            return {}
        if hasattr(working_snapshot, "model_dump"):
            data = working_snapshot.model_dump(mode="json")
        else:
            data = dict(working_snapshot) if isinstance(working_snapshot, dict) else {}
        return {
            "goal": data.get("current_goal", ""),
            "current_step": data.get("current_step", ""),
            "pending_steps": data.get("pending_steps", []),
            "active_entities": data.get("active_entities", []),
        }

    @staticmethod
    def extract_constraints(
        working_snapshot: Any | None,
        episode_snapshot: Any | None = None,
    ) -> list[str]:
        """Collect hard constraints from working and episode snapshots."""
        constraints: list[str] = []
        for snapshot in (working_snapshot, episode_snapshot):
            if snapshot is None:
                continue
            if hasattr(snapshot, "model_dump"):
                data = snapshot.model_dump(mode="json")
            elif isinstance(snapshot, dict):
                data = snapshot
            else:
                continue
            constraints.extend(data.get("constraints", []))
        return constraints

    @staticmethod
    def is_hard_protected_memory(memory: RetrievedMemory) -> bool:
        """Return whether a memory must be protected from budget trimming."""
        if memory.layer is LifecycleLayer.WORKING:
            return True
        if memory.memory_type.value == "PROCEDURAL":
            return True
        return False


__all__ = ["ContextAssemblyResult", "ContextService"]
