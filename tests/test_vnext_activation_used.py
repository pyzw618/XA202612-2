"""Batch 1 — Activation Completion: USED.

Validate that Agent-asserted usage can promote an activation from
RECALLED → SELECTED/IN_CONTEXT → USED, with idempotency, scope checks,
and rejection of memories that never made it into context.
"""

from __future__ import annotations

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.feedback_service import (
    FeedbackEvent,
    FeedbackType,
    UsageKind,
    UtilityFeedbackShadow,
)
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    ActivationStatus,
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.storage.database import Database
from memoryhub.storage.models import MemoryActivationRow
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
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


def _request() -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id="req-1",
        tenant_id="tenant-1",
        user_id="user-1",
        query="how to format report",
        task_id="task-1",
        intent_hint=RetrievalIntent.PREFERENCE,
        token_budget=1000,
    )


def _fixed_executor(memories: list[RetrievedMemory]):
    def executor(request, plan, channel):
        return memories
    return executor


def test_upsert_activation_keeps_final_status():
    """record() updates the same row instead of creating duplicates."""
    db = Database(":memory:")
    db.init_schema()
    repo = ActivationRepository(db)

    repo.record(
        activation_id="act-1",
        tenant_id="tenant-1",
        user_id="user-1",
        query_id="req-1",
        memory_id="m1",
        task_id="task-1",
        intent="PREFERENCE",
        status="RECALLED",
        rank=1,
        initial_score=0.9,
        reranked_score=0.9,
        content_version=1,
        included_in_context=False,
    )
    repo.record(
        activation_id="act-2",
        tenant_id="tenant-1",
        user_id="user-1",
        query_id="req-1",
        memory_id="m1",
        task_id="task-1",
        intent="PREFERENCE",
        status="IN_CONTEXT",
        rank=1,
        initial_score=0.9,
        reranked_score=0.9,
        content_version=1,
        included_in_context=True,
    )

    with db.session() as session:
        rows = session.query(MemoryActivationRow).all()
        assert len(rows) == 1
        assert rows[0].status == "IN_CONTEXT"
        assert rows[0].included_in_context is True


def test_record_usage_feedback_promotes_to_used():
    """Explicit usage feedback moves IN_CONTEXT activation to USED."""
    db = Database(":memory:")
    db.init_schema()
    shadow = UtilityFeedbackShadow()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=shadow,
    )

    result = service.retrieve(_request())
    assert result.response.retrieval_log_id
    assert result.response.context.relevant_memory_ids == ["m1"]

    feedback = service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
        usage_source="agent.step",
        confidence=1.0,
    )
    assert feedback["marked"] == ["m1"]
    assert feedback["untrusted"] == []
    assert feedback["rejected"] == []

    act = ActivationRepository(db).get(
        tenant_id="tenant-1",
        user_id="user-1",
        query_id="req-1",
        memory_id="m1",
    )
    assert act is not None

    with db.session() as session:
        row = session.query(MemoryActivationRow).filter_by(memory_id="m1").one()
        assert row.status == ActivationStatus.USED.value
        assert row.used_at is not None

    used_usages = [u for u in shadow.usages if u.outcome_code == "USED"]
    assert len(used_usages) == 1
    assert used_usages[0].usage_kind is UsageKind.ACTION_INFLUENCED
    assert used_usages[0].memory_id == "m1"


def test_record_usage_feedback_is_idempotent():
    """Replaying the same usage feedback does not create a second USED row."""
    db = Database(":memory:")
    db.init_schema()
    shadow = UtilityFeedbackShadow()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=shadow,
    )

    result = service.retrieve(_request())
    retrieval_id = result.response.retrieval_log_id

    service.record_usage_feedback(
        retrieval_id=retrieval_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )
    service.record_usage_feedback(
        retrieval_id=retrieval_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )

    with db.session() as session:
        rows = session.query(MemoryActivationRow).filter_by(memory_id="m1").all()
        assert len(rows) == 1
        assert rows[0].status == ActivationStatus.USED.value
    used_usages = [u for u in shadow.usages if u.outcome_code == "USED"]
    assert len(used_usages) == 1


def test_record_usage_feedback_rejects_not_in_context():
    """A memory that was never selected into context cannot be marked USED."""
    db = Database(":memory:")
    db.init_schema()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
    )

    result = service.retrieve(_request())
    feedback = service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m2"],
        tenant_id="tenant-1",
        user_id="user-1",
    )
    assert feedback["marked"] == []
    assert feedback["untrusted"] == ["m2"]
    assert feedback["rejected"] == []


def test_record_usage_feedback_rejects_cross_tenant():
    """Usage feedback from tenant-a cannot touch tenant-b retrieval."""
    db = Database(":memory:")
    db.init_schema()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
    )

    result = service.retrieve(_request())
    feedback = service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-2",
        user_id="user-1",
    )
    assert feedback["marked"] == []
    assert feedback["rejected"] == ["m1"]


def test_retrieval_service_response_carries_retrieval_log_id():
    """The response must expose the retrieval log id so callers can report usage."""
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        retrieval_log_repository=RetrievalLogRepository(Database(":memory:")),
    )
    response = service.search(_request())
    assert response.retrieval_log_id



def test_app_wires_usage_feedback_shadow_to_retrieval_service(tmp_path):
    """The production app factory injects UtilityFeedbackShadow into RetrievalService."""
    from fastapi.testclient import TestClient

    from memoryhub.app import create_app
    from memoryhub.config import load_config

    config = load_config()
    config.storage.db_path = str(tmp_path / "memoryhub.db")
    config.storage.vector_index_path = str(tmp_path / "vector")
    config.storage.evidence_path = str(tmp_path / "evidence")
    app = create_app(config)
    with TestClient(app):
        retrieval_service = app.state.retrieval_service
        assert retrieval_service is not None
        assert retrieval_service.usage_feedback_service is not None


def test_record_feedback_event_requires_used_memory_for_task_outcome():
    db = Database(":memory:")
    db.init_schema()
    shadow = UtilityFeedbackShadow()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=shadow,
    )
    result = service.retrieve(_request())

    event = FeedbackEvent(
        feedback_id="fb-outcome",
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
        retrieval_id=result.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.TASK_FAILURE,
        outcome="TIMEOUT",
    )
    rejected = service.record_feedback_event(event)
    assert rejected["status"] == "accepted"
    assert rejected["attribution"] == "none"
    assert shadow.feedback == []

    service.record_usage_feedback(
        retrieval_id=result.retrieval_log_id,
        memory_ids=["m1"],
        tenant_id="tenant-1",
        user_id="user-1",
    )
    attributed = service.record_feedback_event(
        event.model_copy(update={"feedback_id": "fb-outcome-2"})
    )
    assert attributed["attribution"] == "strong"
    assert attributed["attributed_memory_ids"] == ["m1"]


def test_feedback_event_rejects_cross_scope_retrieval():
    db = Database(":memory:")
    db.init_schema()
    service = RetrievalService(
        channel_executors={"metadata": _fixed_executor([_memory("m1")])},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=UtilityFeedbackShadow(),
    )
    result = service.retrieve(_request())
    event = FeedbackEvent(
        feedback_id="fb-cross-tenant",
        tenant_id="tenant-2",
        user_id="user-1",
        retrieval_id=result.retrieval_log_id,
        memory_ids=["m1"],
        feedback_type=FeedbackType.EXPLICIT_POSITIVE,
    )
    assert service.record_feedback_event(event)["status"] == "rejected"
