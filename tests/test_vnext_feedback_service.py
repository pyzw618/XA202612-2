from __future__ import annotations

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.feedback_service import (
    FeedbackEvent,
    FeedbackType,
    UsageKind,
    UtilityFeedbackShadow,
    UtilityStabilityUpdater,
)
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    LifecycleLayer,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
)
from memoryhub.observability.trace_store import TraceStore
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import CandidateRepository


def test_usage_shadow_distinguishes_all_five_kinds_and_is_redacted() -> None:
    traces = TraceStore()
    shadow = UtilityFeedbackShadow(trace_store=traces)
    for kind in UsageKind:
        shadow.record_usage(
            trace_id="trace-usage",
            query_id="query-1",
            task_id="task-1",
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id="memory-1",
            usage_kind=kind,
            utility_signal=0.5 if kind is UsageKind.OUTCOME else 0.0,
        )

    report = shadow.report()
    assert set(report.by_kind) == {kind.value for kind in UsageKind}
    assert report.shadow_only is True
    assert report.authority_mutations == 0
    assert all(span.redacted for span in traces.records)
    assert all("query" not in span.classification for span in traces.records)


def test_feedback_requires_outcome_or_correction_and_only_proposes_utility() -> None:
    shadow = UtilityFeedbackShadow()
    usage = shadow.record_usage(
        trace_id="trace-1",
        query_id="query-1",
        task_id="task-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="memory-1",
        usage_kind=UsageKind.INCLUDED,
    )
    shadow.record_feedback(
        usage_id=usage.usage_id,
        trace_id="trace-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="memory-1",
        usage_kind=UsageKind.CORRECTION,
        accepted=False,
        utility_signal=-1.0,
        correction_code="WRONG_SCOPE",
    )
    report = shadow.report()
    assert report.feedback == 1
    assert report.proposals[0].proposed_utility == 0.25
    assert "NO_AUTHORITY_MUTATION" in report.proposals[0].reason_codes


def test_retrieval_usage_shadow_records_included_memory() -> None:
    shadow = UtilityFeedbackShadow()
    memory = RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="memory-1",
        memory_type=MemoryType.PREFERENCE,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        content_version=1,
        evolution_status="ACTIVE",
        content={"text": "redacted from usage traces"},
        score=0.9,
    )
    service = RetrievalService(
        usage_feedback_service=shadow,
        channel_executors={
            "metadata": lambda request, plan, channel: [memory],
        },
    )
    service.retrieve(
        MemoryRetrievalRequest(
            request_id="request-1",
            tenant_id="tenant-1",
            user_id="user-1",
            query="format",
            intent_hint="PREFERENCE",
            token_budget=256,
        )
    )
    assert shadow.usages[0].usage_kind is UsageKind.INCLUDED
    assert shadow.usages[0].memory_id == "memory-1"
    assert all("redacted from usage" not in str(span) for span in shadow.trace_store.records)


def test_feedback_event_attributes_explicit_and_is_idempotent() -> None:
    shadow = UtilityFeedbackShadow()
    event = FeedbackEvent(
        feedback_id="fb-1",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id="retrieval-1",
        memory_ids=["memory-1"],
        feedback_type=FeedbackType.EXPLICIT_NEGATIVE,
        outcome="USER_CORRECTED",
        source="agent",
        confidence=1.0,
    )

    first = shadow.record_event(event, used_memory_ids=set())
    second = shadow.record_event(event, used_memory_ids=set())

    assert first["attribution"] == "strong"
    assert first["attributed_memory_ids"] == ["memory-1"]
    assert second["feedback_ids"] == first["feedback_ids"]
    assert len(shadow.feedback) == 1


def test_task_failure_without_used_memory_is_not_attributed() -> None:
    shadow = UtilityFeedbackShadow()
    result = shadow.record_event(
        FeedbackEvent(
            feedback_id="fb-unrelated",
            tenant_id="tenant-1",
            user_id="user-1",
            retrieval_id="retrieval-1",
            memory_ids=["memory-1"],
            feedback_type=FeedbackType.TASK_FAILURE,
            outcome="TIMEOUT",
        ),
        used_memory_ids=set(),
    )

    assert result["attribution"] == "none"
    assert result["unattributed_memory_ids"] == ["memory-1"]
    assert shadow.feedback == []


def test_multiple_used_memories_receive_weak_outcome_attribution() -> None:
    shadow = UtilityFeedbackShadow()
    result = shadow.record_event(
        FeedbackEvent(
            feedback_id="fb-multi",
            tenant_id="tenant-1",
            user_id="user-1",
            retrieval_id="retrieval-1",
            memory_ids=["memory-1", "memory-2"],
            feedback_type=FeedbackType.TASK_SUCCESS,
            outcome="SUCCESS",
        ),
        used_memory_ids={"memory-1", "memory-2"},
    )

    assert result["attribution"] == "weak"
    assert len(shadow.feedback) == 2
    assert all(item.confidence == 0.5 for item in shadow.feedback)
    assert all(item.utility_signal == 0.25 for item in shadow.feedback)


def test_candidate_score_update_is_bounded_and_idempotent() -> None:
    db = Database(":memory:")
    db.init_schema()
    repository = CandidateRepository(db)
    repository.create(
        candidate_id="candidate-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_type="PREFERENCE",
        normalized_key="format",
        claim={"format": "DOCX"},
        scope_level="PROJECT",
        scope="PROJECT:reporting",
        utility=0.98,
        stability=0.98,
    )
    item = UtilityFeedbackShadow().record_feedback(
        feedback_id="fb-correction:candidate-1",
        usage_id="usage-1",
        trace_id="trace-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="candidate-1",
        usage_kind=UsageKind.CORRECTION,
        accepted=False,
        utility_signal=-1.0,
        feedback_type=FeedbackType.USER_CORRECTION,
    )
    updater = UtilityStabilityUpdater()
    first = updater.update_candidate(item, repository)
    second = updater.update_candidate(item, repository)
    current = repository.get(
        tenant_id="tenant-1", user_id="user-1", candidate_id="candidate-1"
    )
    assert first == second
    assert current is not None
    assert current.utility == 0.83
    assert current.stability == 0.83
    assert len(updater.updates) == 1


def test_authority_feedback_updates_scores_and_writes_audit_trace() -> None:
    db = Database(":memory:")
    db.init_schema()
    authority = AuthorityRepository(db)
    authority.save(
        LongTermEnvelope(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id="memory-1",
            memory_type=MemoryType.PREFERENCE,
            normalized_key="format",
            content={"text": "DOCX"},
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            confidence=0.9,
            utility=0.5,
            stability=0.5,
            evidence_refs=["event-1"],
        )
    )
    traces = TraceStore()
    shadow = UtilityFeedbackShadow(trace_store=traces)
    item = shadow.record_feedback(
        feedback_id="fb-positive:memory-1",
        usage_id="usage-1",
        trace_id="trace-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="memory-1",
        usage_kind=UsageKind.OUTCOME,
        accepted=True,
        utility_signal=1.0,
        feedback_type=FeedbackType.EXPLICIT_POSITIVE,
    )
    update = UtilityStabilityUpdater(trace_store=traces).update_authority(item, authority)
    current = authority.get(
        tenant_id="tenant-1", user_id="user-1", memory_id="memory-1"
    )
    assert current is not None
    assert (current.utility, current.stability) == (0.6, 0.58)
    assert update.old_utility == 0.5
    assert any(span.layer == "UTILITY_STABILITY_UPDATE" for span in traces.records)
