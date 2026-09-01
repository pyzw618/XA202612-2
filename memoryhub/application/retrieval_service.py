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
from datetime import datetime, timezone
from typing import Any

from memoryhub.adapter.vnext_schemas import (
    ContextPayload,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    RetrievedMemory,
)
from memoryhub.application.context_service import ContextAssemblyResult, ContextService
from memoryhub.application.feedback_service import (
    FeedbackEvent,
    UsageKind,
    UtilityStabilityUpdater,
)
from memoryhub.domain.contracts import (
    Activation,
    ActivationStatus,
    EvolutionStatus,
    RetrievalIntent,
)
from memoryhub.retrieval.intent_router import IntentRouter, RoutedIntent
from memoryhub.retrieval.planner import RetrievalPlan, RetrievalPlanner
from memoryhub.retrieval.scope_resolver import ScopeResolver
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.vnext_repositories import CandidateRepository

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
        score_updater: UtilityStabilityUpdater | None = None,
        evolution_service: Any | None = None,
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
        self.score_updater = score_updater or UtilityStabilityUpdater(
            trace_store=trace_store
        )
        self.evolution_service = evolution_service

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
        channel_metrics: dict[str, dict[str, float | int]] = {}
        for channel in plan.enabled_channels:
            channel_started_at = time.perf_counter()
            executor = self.channel_executors.get(channel)
            if executor is None:
                # No executor registered: treat as empty result rather than fail.
                channel_results[channel] = []
                channel_metrics[channel] = {"count": 0, "latency_ms": 0.0}
                continue
            try:
                channel_results[channel] = executor(request, plan, channel)
            except Exception:
                # Degrade gracefully: record an empty result for this channel.
                channel_results[channel] = []
            channel_metrics[channel] = {
                "count": len(channel_results[channel]),
                "latency_ms": round((time.perf_counter() - channel_started_at) * 1000, 3),
            }

        # 4/5/6. Context assembly (fusion → rerank → scope → budget)
        assembly = self.context_service.build_context(
            request=request,
            plan=plan,
            channel_results=channel_results,
            working_state=working_state,
            constraints=constraints,
            conflict_notes=conflict_notes,
        )
        assembly.trace["channel_metrics"] = channel_metrics

        # 7. Activation logging for selected memories
        activations = self._record_activations(
            request,
            query_id,
            routed.intent,
            assembly,
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

        # Build response
        selected = assembly.context.relevant_memory_ids
        response = MemoryRetrievalResponse(
            request_id=request.request_id,
            trace_id=trace_id,
            retrieval_log_id=retrieval_log_id,
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

    def record_usage_feedback(
        self,
        *,
        retrieval_id: str,
        memory_ids: list[str],
        tenant_id: str,
        user_id: str,
        task_id: str = "",
        session_id: str = "",
        usage_source: str = "agent",
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        """Record that specific memories from a retrieval were actually used.

        This is the strong-evidence path: the caller explicitly identifies the
        memories the agent depended on. Only memories that passed scope checks
        and were selected into context may be marked USED.
        """
        result: dict[str, Any] = {
            "retrieval_id": retrieval_id,
            "memory_ids": list(memory_ids),
            "marked": [],
            "rejected": [],
            "untrusted": [],
        }
        if not memory_ids:
            return result
        if self.retrieval_log_repository is None or self.activation_repository is None:
            return result
        try:
            log = self.retrieval_log_repository.get(retrieval_log_id=retrieval_id)
        except Exception:
            return result
        if log is None:
            return result
        if log.tenant_id != tenant_id or log.user_id != user_id:
            result["rejected"].extend(memory_ids)
            return result
        selected = set(log.plan.get("selected_memory_ids", []))
        query_id = log.query_id
        trace_id = log.trace_id
        for memory_id in memory_ids:
            if memory_id not in selected:
                result["untrusted"].append(memory_id)
                continue
            try:
                _, newly_marked = self.activation_repository.mark_used(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    query_id=query_id,
                    memory_id=memory_id,
                    used_at=datetime.now(timezone.utc),
                )
                result["marked"].append(memory_id)
            except Exception:
                result["rejected"].append(memory_id)
                continue
            if self.usage_feedback_service is not None and newly_marked:
                try:
                    self.usage_feedback_service.record_usage(
                        trace_id=trace_id,
                        query_id=query_id,
                        task_id=task_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        memory_id=memory_id,
                        usage_kind=UsageKind.ACTION_INFLUENCED,
                        utility_signal=0.0,
                        outcome_code="USED",
                    )
                except Exception:
                    pass
        return result

    def record_feedback_event(self, event: FeedbackEvent) -> dict[str, object]:
        """Validate, attribute and optionally evolve memory based on a feedback event."""
        if self.retrieval_log_repository is None or self.activation_repository is None:
            return {"feedback_id": event.feedback_id, "status": "unavailable"}
        log = self.retrieval_log_repository.get(retrieval_log_id=event.retrieval_id)
        if log is None or log.tenant_id != event.tenant_id or log.user_id != event.user_id:
            return {
                "feedback_id": event.feedback_id,
                "status": "rejected",
                "reason": "scope_mismatch_or_retrieval_not_found",
            }
        selected = set(log.plan.get("selected_memory_ids", []))
        recorded_scope = {
            "project_id": log.plan.get("project_id", ""),
            "task_id": log.plan.get("task_id", ""),
            "session_id": log.plan.get("session_id", ""),
            "scope": log.plan.get("scope", ""),
        }
        for field in ("project_id", "task_id", "session_id"):
            value = getattr(event, field)
            if value and recorded_scope[field] and value != recorded_scope[field]:
                return {
                    "feedback_id": event.feedback_id,
                    "status": "rejected",
                    "reason": f"{field}_scope_mismatch",
                }
        requested = list(dict.fromkeys(event.memory_ids))
        if any(memory_id not in selected for memory_id in requested):
            return {
                "feedback_id": event.feedback_id,
                "status": "rejected",
                "reason": "memory_not_selected",
                "untrusted_memory_ids": [m for m in requested if m not in selected],
            }
        used = set()
        for memory_id in requested:
            activation = self.activation_repository.get(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                query_id=log.query_id,
                memory_id=memory_id,
            )
            if activation is not None and activation.status == "USED":
                used.add(memory_id)
        shadow = self.usage_feedback_service
        if shadow is None or not hasattr(shadow, "record_event"):
            return {"feedback_id": event.feedback_id, "status": "unavailable"}
        result = shadow.record_event(event, used_memory_ids=used)
        rejected_memories: list[str] = []
        evolution_results: list[dict[str, object]] = []
        for feedback_id in result.get("feedback_ids", []):
            item = next(
                (value for value in shadow.feedback if value.feedback_id == feedback_id),
                None,
            )
            if item is None or self.authority_repository is None:
                continue

            # Authority path: update scores and, if the memory exists, apply
            # an evolution signal.  Missing/inactive memories are ignored here
            # so that feedback on Candidates is handled separately below.
            try:
                current = self.authority_repository.get(
                    tenant_id=item.tenant_id,
                    user_id=item.user_id,
                    memory_id=item.memory_id,
                    include_inactive=True,
                )
                if current is not None and current.evolution_status is EvolutionStatus.DELETED:
                    rejected_memories.append(item.memory_id)
                    continue
                self.score_updater.update_authority(item, self.authority_repository)
                if current is not None and self.evolution_service is not None:
                    updated = self.authority_repository.get(
                        tenant_id=item.tenant_id,
                        user_id=item.user_id,
                        memory_id=item.memory_id,
                        include_inactive=True,
                    )
                    if updated is not None:
                        evo_result = self.evolution_service.apply_feedback_signal(
                            item, updated
                        )
                        if evo_result.action not in {"NOOP", "REJECTED"}:
                            evolution_results.append(
                                {
                                    "memory_id": item.memory_id,
                                    "action": evo_result.action,
                                    "previous_status": (
                                        evo_result.previous_envelope.evolution_status.value
                                        if evo_result.previous_envelope
                                        else ""
                                    ),
                                    "new_status": (
                                        evo_result.new_envelope.evolution_status.value
                                        if evo_result.new_envelope
                                        else ""
                                    ),
                                }
                            )
            except (KeyError, ValueError):
                pass

            # Candidate feedback path: strong negative moves Candidate to REVIEW.
            if self.db is not None and self._is_negative_feedback(item):
                try:
                    candidate_repo = CandidateRepository(self.db)
                    candidate = candidate_repo.get(
                        tenant_id=item.tenant_id,
                        user_id=item.user_id,
                        candidate_id=item.memory_id,
                    )
                    if candidate is not None and candidate.status in {
                        "ACCUMULATING",
                        "CONFIRMED",
                    }:
                        candidate_repo.transition(
                            tenant_id=item.tenant_id,
                            user_id=item.user_id,
                            candidate_id=item.memory_id,
                            status="REVIEW",
                        )
                except (KeyError, ValueError):
                    pass

        response: dict[str, object] = {
            "feedback_id": event.feedback_id,
            "status": "accepted",
            **result,
        }
        if rejected_memories:
            response["rejected_memory_ids"] = rejected_memories
            response["rejected_reason"] = "memory_deleted"
        if evolution_results:
            response["evolution"] = evolution_results
        return response

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
        # Recall is observable only after scope/authority validation.  Raw
        # fusion candidates can include deleted or invalid projections and
        # must never receive an activation record.
        recalled_memories = (
            assembly.scope_resolution.selected if assembly.scope_resolution else []
        )
        for rank, memory in enumerate(recalled_memories, start=1):
            activation = Activation(
                activation_id=f"act-{uuid.uuid4().hex}",
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                query_id=query_id,
                memory_id=memory.memory_id,
                task_id=request.task_id or "global",
                intent=intent,
                status=ActivationStatus.RECALLED,
                rank=rank,
                initial_score=memory.score,
                reranked_score=memory.score,
                included_in_context=False,
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
                        included_in_context=False,
                    )
                except Exception:
                    # Observability writes must not fail retrieval.
                    pass
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
                    "channel_metrics": assembly.trace.get("channel_metrics", {}),
                    "selected_memory_ids": list(assembly.context.relevant_memory_ids),
                    "project_id": (
                        request.scope.split(":", 1)[1]
                        if request.scope.startswith("PROJECT:")
                        else ""
                    ),
                    "task_id": request.task_id,
                    "session_id": request.session_id,
                    "scope": request.scope,
                },
                candidate_count=assembly.trace.get("fusion_candidates", 0),
                selected_count=len(assembly.context.relevant_memory_ids),
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
                    "channel_metrics": assembly.trace.get("channel_metrics", {}),
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
    def _is_negative_feedback(item: Any) -> bool:
        from memoryhub.application.feedback_service import FeedbackType

        feedback_type = getattr(item, "feedback_type", None)
        return feedback_type in {
            FeedbackType.EXPLICIT_NEGATIVE,
            FeedbackType.USER_CORRECTION,
        }

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
