"""Unified Retrieval Service: S3-08 Activation, Retrieval Log and Trace.

The service is the single retrieval authority for vNext.  All read paths
(REST /search, /context, v2 search, MCP, CLI, SDK) delegate here so they share
identical intent routing, planning, fusion, reranking, scope resolution,
budget management and traceability.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from memoryhub.adapter.vnext_schemas import (
    ContextPayload,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    RetrievedMemory,
)
from memoryhub.application.context_service import ContextAssemblyResult, ContextService
from memoryhub.application.feedback_service import UsageKind
from memoryhub.domain.contracts import (
    Activation,
    ActivationStatus,
    RetrievalIntent,
)
from memoryhub.retrieval.intent_router import IntentRouter, RoutedIntent
from memoryhub.retrieval.planner import RetrievalPlan, RetrievalPlanner
from memoryhub.retrieval.scope_resolver import ScopeResolver
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository

ChannelExecutor = Callable[
    [MemoryRetrievalRequest, RetrievalPlan, str],
    list[RetrievedMemory],
]


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Internal result of the unified retrieval pipeline."""

    response: MemoryRetrievalResponse
    retrieval_log_id: str
    trace_id: str
    activations: list[Activation]


class RetrievalService:
    """Single retrieval service shared by all read entrypoints.

    The pipeline is deterministic and explainable:

    1. Intent routing (rule-based, overrideable by hint)
    2. Planning (channel selection, authority-checked enforcement)
    3. Channel execution (injected per-environment)
    4. Fusion + rerank
    5. Scope/Authority resolution
    6. Context budget assembly
    7. Activation logging + retrieval log + trace span

    Channel executors are callables that take ``(request, plan, channel)`` and
    return an ordered list of ``RetrievedMemory`` candidates.  Production
    injects vector/keyword/metadata/working/episode/authority adapters;
    unit tests inject deterministic mocks.
    """

    def __init__(
        self,
        *,
        intent_router: IntentRouter | None = None,
        planner: RetrievalPlanner | None = None,
        context_service: ContextService | None = None,
        channel_executors: dict[str, ChannelExecutor] | None = None,
        scope_resolver: ScopeResolver | None = None,
        activation_repository: Any | None = None,
        retrieval_log_repository: Any | None = None,
        trace_store: Any | None = None,
        authority_repository: AuthorityRepository | None = None,
        db: Any | None = None,
        usage_feedback_service: Any | None = None,
    ) -> None:
        self.intent_router = intent_router or IntentRouter()
        self.planner = planner or RetrievalPlanner()
        self.authority_repository = authority_repository
        self.db = db
        self.context_service = context_service or ContextService(
            authority_repository=authority_repository,
            repair_callback=self._enqueue_repair,
        )
        self.channel_executors = dict(channel_executors or {})
        if scope_resolver is not None:
            self.scope_resolver = scope_resolver
        elif authority_repository is not None:
            self.scope_resolver = ScopeResolver(
                authority_repository=authority_repository,
                authority_checked=True,
                repair_callback=self._enqueue_repair,
            )
        else:
            self.scope_resolver = ScopeResolver()
        self.activation_repository = activation_repository
        self.retrieval_log_repository = retrieval_log_repository
        self.trace_store = trace_store
        self.usage_feedback_service = usage_feedback_service

    def retrieve(
        self,
        request: MemoryRetrievalRequest,
        *,
        working_state: dict[str, Any] | None = None,
        constraints: list[str] | None = None,
        conflict_notes: list[str] | None = None,
    ) -> RetrievalResult:
        """Execute the full retrieval pipeline and record observability."""
        trace_id = request.request_id
        query_id = request.request_id
        started_at = time.perf_counter()

        # 1. Intent routing
        routed = self.intent_router.route(
            request.query,
            task_id=request.task_id,
            current_goal=request.current_goal,
            current_step=request.current_step,
            active_constraints=request.active_constraints,
            intent_hint=request.intent_hint,
            scope_level=request.scope_level,
        )

        # 2. Planning
        plan = self.planner.plan(request, routed)

        # 3. Channel execution
        channel_results: dict[str, list[RetrievedMemory]] = {}
        for channel in plan.enabled_channels:
            executor = self.channel_executors.get(channel)
            if executor is None:
                # No executor registered: treat as empty result rather than fail.
                channel_results[channel] = []
                continue
            try:
                channel_results[channel] = executor(request, plan, channel)
            except Exception:
                # Degrade gracefully: record an empty result for this channel.
                channel_results[channel] = []

        # 4/5/6. Context assembly (fusion → rerank → scope → budget)
        assembly = self.context_service.build_context(
            request=request,
            plan=plan,
            channel_results=channel_results,
            working_state=working_state,
            constraints=constraints,
            conflict_notes=conflict_notes,
        )

        # 7. Activation logging for selected memories
        activations = self._record_activations(
            request,
            query_id,
            routed.intent,
            assembly,
        )

        # Build response
        selected = assembly.context.relevant_memory_ids
        response = MemoryRetrievalResponse(
            request_id=request.request_id,
            trace_id=trace_id,
            intent=routed.intent,
            retrieval_plan=self._plan_to_dict(plan, routed),
            selected_memories=(
                assembly.scope_resolution.selected if assembly.scope_resolution else []
            ),
            context=assembly.context,
            activations=activations,
            degraded_channels=plan.degraded_channels,
            completeness=self._completeness(plan, channel_results),
            total_count=len(selected),
        )

        latency_ms = (time.perf_counter() - started_at) * 1000
        retrieval_log_id = self._record_retrieval_log(
            request,
            trace_id,
            query_id,
            routed.intent,
            plan,
            assembly,
            latency_ms,
        )

        self._record_trace(
            request,
            trace_id,
            query_id,
            routed,
            plan,
            assembly,
            retrieval_log_id,
            latency_ms,
        )

        return RetrievalResult(
            response=response,
            retrieval_log_id=retrieval_log_id,
            trace_id=trace_id,
            activations=activations,
        )

    def search(
        self,
        request: MemoryRetrievalRequest,
        **kwargs: Any,
    ) -> MemoryRetrievalResponse:
        """Convenience wrapper that returns only the response DTO."""
        return self.retrieve(request, **kwargs).response

    def context(
        self,
        request: MemoryRetrievalRequest,
        **kwargs: Any,
    ) -> ContextPayload:
        """Convenience wrapper that returns only the context payload."""
        return self.retrieve(request, **kwargs).response.context

    def _enqueue_repair(self, memory: RetrievedMemory) -> None:
        """Enqueue a high-priority projection repair without failing retrieval."""
        if self.db is None:
            return
        try:
            with self.db.session() as session:
                MemoryProjectionOutboxRepository(self.db).enqueue(
                    memory_id=memory.memory_id,
                    memory_type=memory.memory_type.value,
                    operation="upsert",
                    payload={
                        "memory_id": memory.memory_id,
                        "memory_type": memory.memory_type.value,
                        "operation": "upsert",
                        "content_version": memory.content_version,
                        "projection_type": "vector",
                    },
                    session=session,
                    tenant_id=memory.tenant_id,
                    user_id=memory.user_id,
                    content_version=memory.content_version,
                    projection_type="vector",
                    priority=10,
                )
        except Exception:
            pass

    def _record_activations(
        self,
        request: MemoryRetrievalRequest,
        query_id: str,
        intent: RetrievalIntent,
        assembly: ContextAssemblyResult,
    ) -> list[Activation]:
        """Create Activation records for every selected memory.

        Activation records the retrieval progression (RECALLED → SELECTED →
        IN_CONTEXT) without changing the memory's lifecycle layer.
        """
        activations: list[Activation] = []
        selected_memories = (
            assembly.scope_resolution.selected if assembly.scope_resolution else []
        )
        for rank, memory in enumerate(selected_memories, start=1):
            included = memory.memory_id in assembly.context.relevant_memory_ids
            status = ActivationStatus.IN_CONTEXT if included else ActivationStatus.SELECTED
            activation = Activation(
                activation_id=f"act-{uuid.uuid4().hex}",
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query_id=query_id,
                memory_id=memory.memory_id,
                task_id=request.task_id or "global",
                intent=intent,
                status=status,
                rank=rank,
                initial_score=memory.score,
                reranked_score=memory.score,
                included_in_context=included,
            )
            activations.append(activation)
            if self.activation_repository is not None:
                try:
                    self.activation_repository.record(
                        activation_id=activation.activation_id,
                        tenant_id=activation.tenant_id,
                        user_id=activation.user_id,
                        query_id=activation.query_id,
                        memory_id=activation.memory_id,
                        task_id=activation.task_id,
                        intent=activation.intent.value,
                        status=activation.status.value,
                        rank=activation.rank,
                        initial_score=activation.initial_score,
                        reranked_score=activation.reranked_score,
                        content_version=memory.content_version,
                        included_in_context=activation.included_in_context,
                    )
                except Exception:
                    # Observability writes must not fail retrieval.
                    pass
            if self.usage_feedback_service is not None:
                self.usage_feedback_service.record_usage(
                    trace_id=request.request_id,
                    query_id=query_id,
                    task_id=request.task_id,
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    memory_id=memory.memory_id,
                    usage_kind=(
                        UsageKind.INCLUDED if included else UsageKind.REFERENCED
                    ),
                    outcome_code=("IN_CONTEXT" if included else "SELECTED"),
                )
        return activations

    def _record_retrieval_log(
        self,
        request: MemoryRetrievalRequest,
        trace_id: str,
        query_id: str,
        intent: RetrievalIntent,
        plan: RetrievalPlan,
        assembly: ContextAssemblyResult,
        latency_ms: float,
    ) -> str:
        """Persist a redacted retrieval log summary."""
        retrieval_log_id = f"rl-{uuid.uuid4().hex}"
        if self.retrieval_log_repository is None:
            return retrieval_log_id
        try:
            self.retrieval_log_repository.record(
                retrieval_log_id=retrieval_log_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query_id=query_id,
                trace_id=trace_id,
                intent=intent.value,
                consistency=request.consistency.value,
                plan={
                    "enabled_channels": plan.enabled_channels,
                    "authority_checked": plan.authority_checked,
                    "required_layers": [layer.value for layer in plan.required_layers],
                    "required_types": [memory_type.value for memory_type in plan.required_types],
                },
                candidate_count=assembly.trace.get("fusion_candidates", 0),
                selected_count=assembly.trace.get("scope_selected_count", 0),
                degraded_channels=plan.degraded_channels,
                latency_ms=round(latency_ms, 3),
            )
        except Exception:
            pass
        return retrieval_log_id

    def _record_trace(
        self,
        request: MemoryRetrievalRequest,
        trace_id: str,
        query_id: str,
        routed: RoutedIntent,
        plan: RetrievalPlan,
        assembly: ContextAssemblyResult,
        retrieval_log_id: str,
        latency_ms: float,
    ) -> None:
        """Write a redacted retrieval trace span when a trace store is available."""
        if self.trace_store is None:
            return
        try:
            from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
            from memoryhub.observability.trace_policy import TraceCategory

            span = TraceSpan(
                span_id=f"span-retrieval-{query_id}",
                trace_id=trace_id,
                kind=TraceSpanKind.RETRIEVAL,
                category=TraceCategory.RETRIEVAL,
                layer="RETRIEVAL",
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                ids={
                    "query_id": query_id,
                    "retrieval_log_id": retrieval_log_id,
                    "task_id": request.task_id,
                },
                classification={
                    "intent": routed.intent.value,
                    "intent_confidence": routed.confidence,
                    "intent_reason": routed.reason,
                    "consistency": request.consistency.value,
                    "enabled_channels": plan.enabled_channels,
                    "degraded_channels": plan.degraded_channels,
                    "authority_checked": plan.authority_checked,
                },
                scores={
                    "fusion_candidates": assembly.trace.get("fusion_candidates", 0),
                    "fusion_deduplicated": assembly.trace.get("fusion_deduplicated", 0),
                    "reranked_count": assembly.trace.get("reranked_count", 0),
                    "scope_selected_count": assembly.trace.get("scope_selected_count", 0),
                    "scope_invalid_count": assembly.trace.get("scope_invalid_count", 0),
                    "budget_tokens": assembly.trace.get("budget_tokens", 0),
                    "latency_ms": round(latency_ms, 3),
                },
            )
            self.trace_store.record(span)
        except Exception:
            pass

    @staticmethod
    def _plan_to_dict(plan: RetrievalPlan, routed: RoutedIntent) -> dict[str, Any]:
        return {
            "intent": plan.intent.value,
            "intent_confidence": routed.confidence,
            "enabled_channels": plan.enabled_channels,
            "degraded_channels": plan.degraded_channels,
            "authority_checked": plan.authority_checked,
            "top_k": plan.top_k,
            "required_layers": [layer.value for layer in plan.required_layers],
            "required_types": [memory_type.value for memory_type in plan.required_types],
            "metadata_filter": plan.metadata_filter,
            "reason": plan.reason,
        }

    @staticmethod
    def _completeness(
        plan: RetrievalPlan,
        channel_results: dict[str, list[RetrievedMemory]],
    ) -> str:
        if plan.degraded_channels:
            return "PARTIAL"
        if not any(channel_results.values()):
            return "NONE"
        return "FULL"


__all__ = ["RetrievalResult", "RetrievalService"]
