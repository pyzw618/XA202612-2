"""Redacted Agent Usage and Utility Feedback Shadow.

Usage is an observability signal, not an Authority write.  The shadow keeps
only identifiers, categorical usage kinds and bounded numeric signals.  It
returns utility proposals for evaluation; it never edits memory content,
status, version or any repository row.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


class FeedbackType(str, Enum):
    EXPLICIT_POSITIVE = "EXPLICIT_POSITIVE"
    EXPLICIT_NEGATIVE = "EXPLICIT_NEGATIVE"
    TASK_SUCCESS = "TASK_SUCCESS"
    TASK_FAILURE = "TASK_FAILURE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    USER_CORRECTION = "USER_CORRECTION"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    UNKNOWN = "UNKNOWN"


class FeedbackEvent(BaseModel):
    """Auditable feedback input; it contains no raw query or memory content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feedback_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    project_id: str = ""
    task_id: str = ""
    session_id: str = ""
    retrieval_id: str = Field(min_length=1)
    memory_ids: list[str] = Field(default_factory=list)
    feedback_type: FeedbackType
    outcome: str = Field(default="UNKNOWN", min_length=1, max_length=64)
    source: str = Field(default="agent", min_length=1, max_length=64)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    retrieval_id: str = ""
    project_id: str = ""
    task_id: str = ""
    session_id: str = ""
    feedback_type: FeedbackType | None = None
    outcome: str = "UNKNOWN"
    source: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
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


@dataclass(frozen=True, slots=True)
class ScoreUpdate:
    """Auditable bounded score transition derived from one attributed feedback."""

    feedback_id: str
    tenant_id: str
    user_id: str
    memory_id: str
    old_utility: float
    new_utility: float
    old_stability: float
    new_stability: float
    reason: str


FEEDBACK_SCORE_WEIGHTS: dict[FeedbackType, tuple[float, float]] = {
    FeedbackType.EXPLICIT_POSITIVE: (0.10, 0.08),
    FeedbackType.USER_CONFIRMATION: (0.08, 0.06),
    FeedbackType.TASK_SUCCESS: (0.05, 0.04),
    FeedbackType.PARTIAL_SUCCESS: (0.02, 0.01),
    FeedbackType.TASK_FAILURE: (-0.03, -0.04),
    FeedbackType.EXPLICIT_NEGATIVE: (-0.15, -0.15),
    FeedbackType.USER_CORRECTION: (-0.15, -0.15),
    FeedbackType.UNKNOWN: (0.0, 0.0),
}

# Task failure is not evidence against a memory unless the caller explicitly
# attributes the failure to that memory.  Keep the classification small and
# deterministic: external/unknown causes are neutral, while only an explicit
# memory-cause marker can reach the existing TASK_FAILURE negative weight.
_EXTERNAL_FAILURE_OUTCOMES = {
    "TIMEOUT",
    "NETWORK_ERROR",
    "RATE_LIMIT",
    "EXTERNAL_SERVICE_FAILURE",
    "PERMISSION_DENIED",
    "INFRA_FAILURE",
    "EXTERNAL_FAILURE",
}
_MEMORY_CAUSED_FAILURE_OUTCOMES = {
    "MEMORY_CAUSED",
    "MEMORY_ERROR",
    "WRONG_MEMORY",
    "INCORRECT_MEMORY",
}


class UtilityStabilityUpdater:
    """Apply conservative, idempotent score changes to one memory store."""

    def __init__(self, *, trace_store: TraceStore | None = None) -> None:
        self.trace_store = trace_store or TraceStore()
        self._applied_feedback_ids: set[str] = set()
        self.updates: list[ScoreUpdate] = []

    def _delta(self, item: UtilityFeedback) -> tuple[float, float]:
        utility, stability = FEEDBACK_SCORE_WEIGHTS.get(
            item.feedback_type or FeedbackType.UNKNOWN, (0.0, 0.0)
        )
        confidence = item.confidence
        return utility * confidence, stability * confidence

    def update_candidate(self, item: UtilityFeedback, repository: Any) -> ScoreUpdate:
        """Update a candidate by tenant/user/id; missing candidates are rejected."""
        if item.feedback_id in self._applied_feedback_ids:
            return next(update for update in self.updates if update.feedback_id == item.feedback_id)
        current = repository.get(
            tenant_id=item.tenant_id, user_id=item.user_id, candidate_id=item.memory_id
        )
        if current is None:
            raise KeyError("candidate not found")
        delta_utility, delta_stability = self._delta(item)
        update = self._make_update(
            item,
            current.utility,
            current.stability,
            delta_utility,
            delta_stability,
        )
        repository.update_scores(
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            candidate_id=item.memory_id,
            utility=update.new_utility,
            stability=update.new_stability,
        )
        return self._remember(update)

    def update_authority(self, item: UtilityFeedback, repository: Any) -> ScoreUpdate:
        """Update Authority metadata without changing lifecycle status or content."""
        if item.feedback_id in self._applied_feedback_ids:
            return next(update for update in self.updates if update.feedback_id == item.feedback_id)
        current = repository.get(
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            memory_id=item.memory_id,
            include_inactive=True,
        )
        if current is None:
            raise KeyError("authority memory not found")
        delta_utility, delta_stability = self._delta(item)
        update = self._make_update(
            item,
            current.utility,
            current.stability,
            delta_utility,
            delta_stability,
        )
        repository.save(
            current.model_copy(
                update={
                    "utility": update.new_utility,
                    "stability": update.new_stability,
                    "content_version": current.content_version + 1,
                }
            )
        )
        return self._remember(update)

    def _make_update(
        self,
        item: UtilityFeedback,
        old_utility: float,
        old_stability: float,
        delta_utility: float,
        delta_stability: float,
    ) -> ScoreUpdate:
        return ScoreUpdate(
            feedback_id=item.feedback_id,
            tenant_id=item.tenant_id,
            user_id=item.user_id,
            memory_id=item.memory_id,
            old_utility=old_utility,
            new_utility=min(1.0, max(0.0, old_utility + delta_utility)),
            old_stability=old_stability,
            new_stability=min(1.0, max(0.0, old_stability + delta_stability)),
            reason=(item.feedback_type or FeedbackType.UNKNOWN).value,
        )

    def _remember(self, update: ScoreUpdate) -> ScoreUpdate:
        self._applied_feedback_ids.add(update.feedback_id)
        self.updates.append(update)
        self.trace_store.record(
            TraceSpan(
                span_id=f"span-score-{update.feedback_id}",
                trace_id=update.feedback_id,
                kind=TraceSpanKind.RETRIEVAL,
                category=TraceCategory.RETRIEVAL,
                layer="UTILITY_STABILITY_UPDATE",
                tenant_id=update.tenant_id,
                user_id=update.user_id,
                ids={"feedback_id": update.feedback_id, "memory_id": update.memory_id},
                classification={"reason": update.reason, "shadow_only": False},
                scores={
                    "old_utility": update.old_utility,
                    "new_utility": update.new_utility,
                    "old_stability": update.old_stability,
                    "new_stability": update.new_stability,
                },
            )
        )
        return update


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

    def record_event(
        self,
        event: FeedbackEvent,
        *,
        used_memory_ids: set[str],
    ) -> dict[str, object]:
        """Attribute one event conservatively and keep it shadow-only.

        Explicit feedback is strong.  Outcome feedback is only attributable to
        USED memories; multiple memories receive a weak signal.  A replayed
        feedback_id is a no-op and returns the original feedback IDs.
        """
        if event.tenant_id == "" or event.user_id == "":
            raise ValueError("feedback scope is required")
        requested = list(dict.fromkeys(event.memory_ids))
        if event.feedback_type in {
            FeedbackType.EXPLICIT_POSITIVE,
            FeedbackType.USER_CONFIRMATION,
        }:
            signal, accepted, attributable = 1.0, True, requested
        elif event.feedback_type in {
            FeedbackType.EXPLICIT_NEGATIVE,
            FeedbackType.USER_CORRECTION,
        }:
            signal, accepted, attributable = -1.0, False, requested
        elif event.feedback_type is FeedbackType.TASK_SUCCESS:
            attributable = [m for m in requested if m in used_memory_ids]
            signal, accepted = 0.5, True
        elif event.feedback_type is FeedbackType.PARTIAL_SUCCESS:
            attributable = [m for m in requested if m in used_memory_ids]
            signal, accepted = 0.2, True
        elif event.feedback_type is FeedbackType.TASK_FAILURE:
            attributable = [m for m in requested if m in used_memory_ids]
            outcome = event.outcome.strip().upper()
            if outcome in _MEMORY_CAUSED_FAILURE_OUTCOMES:
                signal, accepted = -0.2, False
            else:
                # A used memory only proves usage, not causality.  In
                # particular, infrastructure and unknown failures must not
                # create negative memory feedback.
                signal, accepted, attributable = 0.0, False, []
        else:
            signal, accepted, attributable = 0.0, False, []
        if event.feedback_type in {
            FeedbackType.TASK_SUCCESS,
            FeedbackType.TASK_FAILURE,
            FeedbackType.PARTIAL_SUCCESS,
        } and len(attributable) > 1:
            signal *= 0.5
        created: list[str] = []
        for memory_id in attributable:
            item = self.record_feedback(
                feedback_id=f"{event.feedback_id}:{memory_id}",
                usage_id=f"{event.retrieval_id}:{memory_id}",
                trace_id=event.retrieval_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                memory_id=memory_id,
                usage_kind=UsageKind.CORRECTION if event.feedback_type in {
                    FeedbackType.EXPLICIT_NEGATIVE,
                    FeedbackType.USER_CORRECTION,
                } else UsageKind.OUTCOME,
                accepted=accepted,
                utility_signal=signal,
                retrieval_id=event.retrieval_id,
                project_id=event.project_id,
                task_id=event.task_id,
                session_id=event.session_id,
                feedback_type=event.feedback_type,
                outcome=event.outcome,
                source=event.source,
                confidence=event.confidence * (0.5 if len(attributable) > 1 else 1.0),
            )
            created.append(item.feedback_id)
        return {
            "feedback_id": event.feedback_id,
            "attributed_memory_ids": attributable,
            "feedback_ids": created,
            "unattributed_memory_ids": [m for m in requested if m not in attributable],
            "attribution": (
                "strong" if len(attributable) == 1
                else "weak" if len(attributable) > 1 else "none"
            ),
        }

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
        feedback_id: str | None = None,
        retrieval_id: str = "",
        project_id: str = "",
        task_id: str = "",
        session_id: str = "",
        feedback_type: FeedbackType | str | None = None,
        outcome: str = "UNKNOWN",
        source: str = "",
        confidence: float = 1.0,
    ) -> UtilityFeedback:
        kind = UsageKind(usage_kind)
        if kind not in {UsageKind.OUTCOME, UsageKind.CORRECTION}:
            raise ValueError("feedback usage_kind must be OUTCOME or CORRECTION")
        stable_id = feedback_id or f"feedback-{uuid.uuid4().hex}"
        for existing in self._feedback:
            if existing.feedback_id == stable_id:
                return existing
        item = UtilityFeedback(
            feedback_id=stable_id,
            usage_id=usage_id,
            trace_id=trace_id,
            tenant_id=tenant_id,
            user_id=user_id,
            memory_id=memory_id,
            usage_kind=kind,
            accepted=accepted,
            utility_signal=utility_signal,
            correction_code=correction_code,
            retrieval_id=retrieval_id,
            project_id=project_id,
            task_id=task_id,
            session_id=session_id,
            feedback_type=FeedbackType(feedback_type) if feedback_type is not None else None,
            outcome=outcome,
            source=source,
            confidence=confidence,
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
                    "retrieval_id": item.retrieval_id,
                    "task_id": item.task_id,
                    "session_id": item.session_id,
                },
                classification={
                    "usage_kind": item.usage_kind.value,
                    "accepted": item.accepted,
                    "correction_code": item.correction_code,
                    "shadow_only": True,
                    "feedback_type": item.feedback_type.value if item.feedback_type else "",
                    "outcome": item.outcome,
                    "source": item.source,
                },
                scores={"utility_signal": item.utility_signal},
            )
        )


__all__ = [
    "AgentUsageTrace",
    "FeedbackEvent",
    "FeedbackType",
    "UsageKind",
    "UtilityFeedback",
    "UtilityFeedbackShadow",
    "UtilityFeedbackShadowReport",
    "UtilityStabilityUpdater",
    "ScoreUpdate",
    "UtilityUpdateProposal",
]
