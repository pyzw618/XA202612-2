"""Batch 4 — Feedback-driven Memory Evolution & Safeguards.

Validate that attributed feedback can drive evolution state transitions
(ACTIVE ↔ DORMANT / REVIEW), persist lineage, protect forgotten memories,
and maintain cross-scope isolation.
"""

from __future__ import annotations

from memoryhub.adapter.vnext_schemas import (
    ForgetRequest,
    MemoryRetrievalRequest,
    RetrievedMemory,
)
from memoryhub.application.evolution_service import EvolutionService
from memoryhub.application.feedback_service import (
    FeedbackEvent,
    FeedbackType,
    UtilityFeedbackShadow,
)
from memoryhub.application.forget_service import ForgetService
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    LineageRelation,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryLineageRepository
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
    CandidateRepository,
    RetrievalLogRepository,
)


def _memory(
    memory_id: str,
    *,
    score: float = 0.9,
    layer: LifecycleLayer = LifecycleLayer.LONG_TERM,
    memory_type: MemoryType = MemoryType.PREFERENCE,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=memory_type,
        layer=layer,
        scope_level=scope_level,
        scope=scope,
        content_version=1,
        evolution_status="ACTIVE",
        content={"text": f"content of {memory_id}"},
        score=score,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


def _request(
    *,
    tenant_id: str = "tenant-1",
    user_id: str = "user-1",
    query: str = "how to format report",
    task_id: str = "task-1",
    scope_level: MemoryScope | None = None,
    scope: str = "",
) -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id="req-1",
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        task_id=task_id,
        intent_hint=RetrievalIntent.PREFERENCE,
        token_budget=1000,
        scope_level=scope_level,
        scope=scope,
    )


def _fixed_executor(memories: list[RetrievedMemory]):
    def executor(request, plan, channel):
        return memories

    return executor


def _service(db: Database) -> RetrievalService:
    authority_repository = AuthorityRepository(db)
    authority_facade = LongTermAuthorityFacade(authority_repository)
    lineage_repository = MemoryLineageRepository(db)
    return RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=UtilityFeedbackShadow(),
        authority_repository=authority_repository,
        db=db,
        evolution_service=EvolutionService(
            authority_facade=authority_facade,
            lineage_repository=lineage_repository,
            db=db,
        ),
    )


def _authority(
    db: Database,
    *,
    tenant_id: str = "tenant-1",
    user_id: str = "user-1",
    memory_id: str = "m1",
    evolution_status: EvolutionStatus = EvolutionStatus.ACTIVE,
    utility: float = 0.5,
    stability: float = 0.5,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
) -> LongTermEnvelope:
    envelope = LongTermEnvelope(
        tenant_id=tenant_id,
        user_id=user_id,
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        normalized_key="preference:format",
        content={"text": "DOCX"},
        scope_level=scope_level,
        scope=scope,
        evolution_status=evolution_status,
        confidence=0.9,
        utility=utility,
        stability=stability,
        evidence_refs=["event-1"],
    )
    AuthorityRepository(db).save(envelope)
    return envelope


def test_explicit_negative_feedback_moves_active_to_review_and_writes_lineage():
    """EXPLICIT_NEGATIVE on a USED ACTIVE memory moves it to REVIEW and records lineage."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, utility=0.5, stability=0.5)
    service = _service(db)

    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-negative",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_NEGATIVE,
        outcome="USER_REJECTED",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "accepted"
    evolution = response.get("evolution")
    assert evolution is not None
    assert evolution[0]["action"] == LineageRelation.REVIEWED_BY.value
    assert evolution[0]["new_status"] == EvolutionStatus.REVIEW.value

    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.REVIEW

    lineage = MemoryLineageRepository(db).list_for_memory("m1", "PREFERENCE")
    assert len(lineage) == 1
    assert lineage[0].transition_action == LineageRelation.REVIEWED_BY.value


def test_low_scores_move_active_to_dormant():
    """When updated utility/stability both fall below 0.2, ACTIVE → DORMANT."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, utility=0.25, stability=0.25)
    service = _service(db)

    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-dormant",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_NEGATIVE,
        outcome="NOT_HELPFUL",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "accepted"
    evolution = response.get("evolution")
    assert evolution is not None
    assert evolution[0]["new_status"] == EvolutionStatus.DORMANT.value

    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.DORMANT


def test_positive_feedback_reactivates_dormant_memory():
    """EXPLICIT_POSITIVE on a DORMANT memory moves it back to ACTIVE."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, evolution_status=EvolutionStatus.DORMANT, utility=0.3, stability=0.3)
    service = _service(db)

    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-reactivate",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_POSITIVE,
        outcome="USER_CONFIRMED",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "accepted"
    evolution = response.get("evolution")
    assert evolution is not None
    assert evolution[0]["new_status"] == EvolutionStatus.ACTIVE.value

    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.ACTIVE


def test_negative_feedback_moves_candidate_to_review():
    """USER_CORRECTION on a Candidate moves it from ACCUMULATING to REVIEW."""
    db = Database(":memory:")
    db.init_schema()
    CandidateRepository(db).create(
        candidate_id="candidate-1",
        tenant_id="tenant-1",
        user_id="user-1",
        memory_type="PREFERENCE",
        normalized_key="format",
        claim={"format": "DOCX"},
        scope_level="PROJECT",
        scope="PROJECT:reporting",
        utility=0.5,
        stability=0.5,
    )

    # Point the retrieval log at the candidate id so it is selected.
    service = RetrievalService(
        channel_executors={
            "metadata": _fixed_executor(
                [
                    _memory("candidate-1"),
                ]
            )
        },
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=UtilityFeedbackShadow(),
        authority_repository=AuthorityRepository(db),
        db=db,
    )

    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["candidate-1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-candidate-correction",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["candidate-1"],
        feedback_type=FeedbackType.USER_CORRECTION,
        outcome="WRONG_FORMAT",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "accepted"
    candidate = CandidateRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", candidate_id="candidate-1"
    )
    assert candidate is not None
    assert candidate.status == "REVIEW"


def test_feedback_on_deleted_memory_is_rejected():
    """A DELETED memory rejects feedback and cannot be resurrected."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, utility=0.5, stability=0.5)
    ForgetService(db).execute(
        ForgetRequest(
            request_id="req-forget-1",
            idempotency_key="idem-forget-1",
            tenant_id="tenant-1",
            user_id="user-1",
            instruction="delete format preference",
            target_memory_ids=["m1"],
            dry_run=False,
            confirm=True,
        ),
        high_risk_authorized=True,
    )

    service = _service(db)
    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-deleted",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_POSITIVE,
        outcome="USER_CONFIRMED",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "accepted"
    assert response.get("rejected_reason") == "memory_deleted"
    assert "m1" in response.get("rejected_memory_ids", [])

    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.DELETED
    assert current.utility == 0.5  # score update must have been skipped


def test_cross_tenant_feedback_does_not_evolve_other_tenant_memory():
    """A feedback event scoped to tenant-2 cannot change tenant-1 memory state."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, tenant_id="tenant-1", user_id="user-1", utility=0.5, stability=0.5)
    # Use a different memory_id for tenant-2 so legacy rows do not collide.
    _authority(
        db,
        tenant_id="tenant-2",
        user_id="user-1",
        memory_id="m2",
        utility=0.5,
        stability=0.5,
    )

    service = _service(db)
    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-cross-tenant",
        tenant_id="tenant-2",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_NEGATIVE,
        outcome="USER_REJECTED",
    )
    response = service.record_feedback_event(feedback)

    assert response["status"] == "rejected"
    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.ACTIVE


def test_feedback_evolution_is_idempotent():
    """Replaying the same feedback_id does not trigger a second evolution transition."""
    db = Database(":memory:")
    db.init_schema()
    _authority(db, utility=0.25, stability=0.25)
    service = _service(db)

    result = service.retrieve(_request())
    service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    feedback = FeedbackEvent(
        feedback_id="fb-idempotent",
        tenant_id="tenant-1",
        user_id="user-1",
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_NEGATIVE,
        outcome="NOT_HELPFUL",
    )
    first = service.record_feedback_event(feedback)
    second = service.record_feedback_event(feedback)

    assert first.get("evolution") is not None
    # Second call sees the same feedback_id and becomes a NOOP at the service level.
    assert second.get("evolution") is None

    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="m1", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.DORMANT
    assert current.evolution_status.value == first["evolution"][0]["new_status"]


def test_existing_evolve_path_persists_lineage():
    """The existing formation/consolidation path also writes lineage after this batch."""
    db = Database(":memory:")
    db.init_schema()
    authority = AuthorityRepository(db)
    facade = LongTermAuthorityFacade(authority)
    lineage = MemoryLineageRepository(db)
    service = EvolutionService(facade, lineage_repository=lineage, db=db)

    first = LongTermEnvelope(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="m1",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="preference:format",
        content={"text": "DOCX"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        evolution_status=EvolutionStatus.ACTIVE,
        confidence=0.9,
        utility=0.5,
        stability=0.5,
        evidence_refs=["event-1"],
    )
    service.evolve(first)

    second = first.model_copy(
        update={"content": {"text": "PDF"}, "content_version": 2}
    )
    service.evolve(second)

    records = lineage.list_for_memory("m1", "PREFERENCE")
    assert len(records) == 2
    assert records[-1].transition_action == LineageRelation.SUPERSEDES.value
