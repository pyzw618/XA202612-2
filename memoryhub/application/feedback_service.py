"""Redacted Agent Usage and Utility Feedback Shadow.

Usage is an observability signal, not an Authority write.  The shadow keeps
only identifiers, categorical usage kinds and bounded numeric signals.  It
returns utility proposals for evaluation; it never edits memory content,
status, version or any repository row.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
from memoryhub.observability.trace_policy import TraceCategory
from memoryhub.observability.trace_store import TraceStore


class UsageKind(str, Enum):
    INCLUDED = "INCLUDED"
    REFERENCED = "REFERENCED"
    ACTION_INFLUENCED = "ACTION_INFLUENCED"
    OUTCOME = "OUTCOME"
    CORRECTION = "CORRECTION"


class AgentUsageTrace(BaseModel):
    """One typed usage signal with no query or memory正文 fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    usage_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    usage_kind: UsageKind
    utility_signal: float = Field(default=0.0, ge=-1.0, le=1.0)
    outcome_code: str = Field(default="UNSPECIFIED", min_length=1, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UtilityFeedback(BaseModel):
    """Explicit outcome/correction feedback retained only in the shadow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_id: str = Field(min_length=1)
    usage_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    memory_id: str = Field(min_length=1)
    usage_kind: UsageKind
    accepted: bool
    utility_signal: float = Field(ge=-1.0, le=1.0)
    correction_code: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UtilityUpdateProposal(BaseModel):
    """A deterministic, non-authoritative utility proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    user_id: str
    memory_id: str
    sample_count: int = Field(ge=1)
    baseline_utility: float = Field(ge=0.0, le=1.0)
    proposed_utility: float = Field(ge=0.0, le=1.0)
    reason_codes: list[str] = Field(default_factory=list)


class UtilityFeedbackShadowReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    usages: int = Field(ge=0)
    feedback: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    proposals: list[UtilityUpdateProposal] = Field(default_factory=list)
    shadow_only: bool = True
    authority_mutations: int = Field(default=0, ge=0)


class UtilityFeedbackShadow:
    """Collect usage and feedback and derive bounded utility proposals."""

    def __init__(self, *, trace_store: TraceStore | None = None) -> None:
        self.trace_store = trace_store or TraceStore()
        self._usages: list[AgentUsageTrace] = []
        self._feedback: list[UtilityFeedback] = []

    @property
    def usages(self) -> list[AgentUsageTrace]:
        return list(self._usages)

    @property
    def feedback(self) -> list[UtilityFeedback]:
        return list(self._feedback)

    def record_usage(
        self,
        *,
        trace_id: str,
        query_id: str,
        task_id: str | None,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        usage_kind: UsageKind | str,
        utility_signal: float = 0.0,
        outcome_code: str = "UNSPECIFIED",
    ) -> AgentUsageTrace:
        kind = UsageKind(usage_kind)
        usage = AgentUsageTrace(
            usage_id=f"usage-{uuid.uuid4().hex}",
            trace_id=trace_id,
            query_id=query_id,
            task_id=task_id or "global",
            tenant_id=tenant_id,
            user_id=user_id,
            memory_id=memory_id,
            usage_kind=kind,
            utility_signal=utility_signal,
            outcome_code=outcome_code,
        )
        self._usages.append(usage)
        self._record_trace(usage)
        return usage

    def record_feedback(
        self,
        *,
        usage_id: str,
        trace_id: str,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        usage_kind: UsageKind | str,
        accepted: bool,
        utility_signal: float,
        correction_code: str = "",
    ) -> UtilityFeedback:
        kind = UsageKind(usage_kind)
        if kind not in {UsageKind.OUTCOME, UsageKind.CORRECTION}:
            raise ValueError("feedback usage_kind must be OUTCOME or CORRECTION")
        item = UtilityFeedback(
            feedback_id=f"feedback-{uuid.uuid4().hex}",
            usage_id=usage_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            memory_id=memory_id,
            usage_kind=kind,
            accepted=accepted,
            utility_signal=utility_signal,
            correction_code=correction_code,
        )
        self._feedback.append(item)
        self._record_feedback_trace(item)
        return item

    def report(self) -> UtilityFeedbackShadowReport:
        grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for usage in self._usages:
            grouped[(usage.tenant_id, usage.user_id, usage.memory_id)].append(
                usage.utility_signal
            )
        for item in self._feedback:
            grouped[(item.tenant_id, item.user_id, item.memory_id)].append(
                item.utility_signal
            )

        proposals: list[UtilityUpdateProposal] = []
        for (tenant_id, user_id, memory_id), signals in sorted(grouped.items()):
            average = sum(signals) / len(signals)
            proposed = min(1.0, max(0.0, 0.5 + average / 2.0))
            reasons = ["SHADOW_UTILITY_ONLY", "NO_AUTHORITY_MUTATION"]
            if average < 0:
                reasons.append("NEGATIVE_FEEDBACK")
            elif average > 0:
                reasons.append("POSITIVE_FEEDBACK")
            proposals.append(
                UtilityUpdateProposal(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    memory_id=memory_id,
                    sample_count=len(signals),
                    baseline_utility=0.5,
                    proposed_utility=proposed,
                    reason_codes=reasons,
                )
            )

        counts = {kind.value: 0 for kind in UsageKind}
        for usage in self._usages:
            counts[usage.usage_kind.value] += 1
        return UtilityFeedbackShadowReport(
            usages=len(self._usages),
            feedback=len(self._feedback),
            by_kind={key: value for key, value in counts.items() if value},
            proposals=proposals,
        )

    def _record_trace(self, usage: AgentUsageTrace) -> None:
        self.trace_store.record(
            TraceSpan(
                span_id=f"span-usage-{usage.usage_id}",
                trace_id=usage.trace_id,
                kind=TraceSpanKind.RETRIEVAL,
                category=TraceCategory.RETRIEVAL,
                layer="AGENT_USAGE",
                tenant_id=usage.tenant_id,
                user_id=usage.user_id,
                ids={
                    "usage_id": usage.usage_id,
                    "query_id": usage.query_id,
                    "task_id": usage.task_id,
                    "memory_id": usage.memory_id,
                },
                classification={
                    "usage_kind": usage.usage_kind.value,
                    "outcome_code": usage.outcome_code,
                    "shadow_only": True,
                },
                scores={"utility_signal": usage.utility_signal},
            )
        )

    def _record_feedback_trace(self, item: UtilityFeedback) -> None:
        self.trace_store.record(
            TraceSpan(
                span_id=f"span-feedback-{item.feedback_id}",
                trace_id=item.trace_id,
                kind=TraceSpanKind.RETRIEVAL,
                category=TraceCategory.RETRIEVAL,
                layer="UTILITY_FEEDBACK",
                tenant_id=item.tenant_id,
                user_id=item.user_id,
                ids={
                    "feedback_id": item.feedback_id,
                    "usage_id": item.usage_id,
                    "memory_id": item.memory_id,
                },
                classification={
                    "usage_kind": item.usage_kind.value,
                    "accepted": item.accepted,
                    "correction_code": item.correction_code,
                    "shadow_only": True,
                },
                scores={"utility_signal": item.utility_signal},
            )
        )


__all__ = [
    "AgentUsageTrace",
    "UsageKind",
    "UtilityFeedback",
    "UtilityFeedbackShadow",
    "UtilityFeedbackShadowReport",
    "UtilityUpdateProposal",
]
