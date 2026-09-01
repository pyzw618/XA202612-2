"""Stage 3 Batch 5 — continuous feedback scenarios.

These tests exercise the real vNext service chain from retrieval through
activation, feedback attribution, score update, and evolution.  They do not
replace the focused unit tests in the earlier Stage 3 batches.
"""

from __future__ import annotations

from memoryhub.adapter.vnext_schemas import ForgetRequest, MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.evolution_service import EvolutionService
from memoryhub.application.feedback_service import FeedbackEvent, FeedbackType, UtilityFeedbackShadow
from memoryhub.application.forget_service import ForgetService
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryLineageRepository
from memoryhub.storage.vnext_repositories import ActivationRepository, RetrievalLogRepository


def _memory(
    memory_id: str,
    *,
    project_id: str = "",
    score: float = 0.9,
    utility: float = 0.5,
    stability: float = 0.5,
    status: EvolutionStatus = EvolutionStatus.ACTIVE,
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        layer="LONG_TERM",
        scope_level=MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL,
        scope=f"PROJECT:{project_id}" if project_id else "GLOBAL",
        content_version=1,
        evolution_status=status,
        content={"text": f"content for {memory_id}"},
        score=score,
        score_breakdown={"utility": utility, "stability": stability},
        source_ids=[f"source:{memory_id}"],
    )


def _request(
    request_id: str,
    *,
    task_id: str = "task-1",
    project_id: str = "",
) -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id=request_id,
        tenant_id="tenant-1",
        user_id="user-1",
        query="which format should this project use",
        task_id=task_id,
        intent_hint=RetrievalIntent.PREFERENCE,
        token_budget=4096,
        scope_level=MemoryScope.PROJECT if project_id else None,
        scope=f"PROJECT:{project_id}" if project_id else "",
    )


def _service(db: Database, memories: list[RetrievedMemory]) -> tuple[RetrievalService, UtilityFeedbackShadow]:
    authority = AuthorityRepository(db)
    shadow = UtilityFeedbackShadow()
    lineage = MemoryLineageRepository(db)
    service = RetrievalService(
        channel_executors={"metadata": lambda request, plan, channel: memories},
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        usage_feedback_service=shadow,
        authority_repository=authority,
        db=db,
        evolution_service=EvolutionService(
            authority_facade=LongTermAuthorityFacade(authority),
            lineage_repository=lineage,
            db=db,
        ),
    )
    return service, shadow


def _save_authority(db: Database, memory_id: str, *, utility: float = 0.5, stability: float = 0.5,
                    status: EvolutionStatus = EvolutionStatus.ACTIVE, project_id: str = "") -> None:
    AuthorityRepository(db).save(
        LongTermEnvelope(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id=memory_id,
            memory_type=MemoryType.PREFERENCE,
            normalized_key=f"preference:{memory_id}",
            content={"text": f"content for {memory_id}"},
            scope_level=MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL,
            scope=f"PROJECT:{project_id}" if project_id else "GLOBAL",
            evolution_status=status,
            confidence=0.9,
            utility=utility,
            stability=stability,
            evidence_refs=["event-1"],
        )
    )


def _used(service: RetrievalService, retrieval_id: str, memory_ids: list[str], *, task_id: str = "task-1",
          project_id: str = "") -> None:
    result = service.record_usage_feedback(
        retrieval_id=retrieval_id,
        memory_ids=memory_ids,
        tenant_id="tenant-1",
        user_id="user-1",
        task_id=task_id,
        usage_source="scenario",
    )
    assert result["marked"] == memory_ids
    assert result["untrusted"] == []


def _feedback(retrieval_id: str, feedback_id: str, memory_ids: list[str], feedback_type: FeedbackType,
              *, task_id: str = "task-1", project_id: str = "") -> FeedbackEvent:
    return FeedbackEvent(
        feedback_id=feedback_id,
        tenant_id="tenant-1",
        user_id="user-1",
        project_id=project_id,
        task_id=task_id,
        retrieval_id=retrieval_id,
        memory_ids=memory_ids,
        feedback_type=feedback_type,
        outcome=feedback_type.value,
        source="scenario",
    )


def test_scenarios_a_and_c_positive_and_single_used_success() -> None:
    db = Database(":memory:")
    db.init_schema()
    _save_authority(db, "maven", utility=0.5, stability=0.5)
    service, _ = _service(db, [_memory("maven")])

    result = service.retrieve(_request("scenario-a"))
    assert result.response.context.relevant_memory_ids == ["maven"]
    _used(service, result.response.retrieval_log_id, ["maven"])
    response = service.record_feedback_event(
        _feedback(result.response.retrieval_log_id, "fb-a", ["maven"], FeedbackType.EXPLICIT_POSITIVE)
    )
    assert response["attribution"] == "strong"
    updated = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="maven")
    assert updated is not None and updated.utility > 0.5 and updated.stability > 0.5


def test_scenario_b_correction_is_reviewable_without_hard_delete() -> None:
    db = Database(":memory:")
    db.init_schema()
    _save_authority(db, "database", utility=0.8, stability=0.8)
    service, _ = _service(db, [_memory("database")])
    result = service.retrieve(_request("scenario-b"))
    _used(service, result.response.retrieval_log_id, ["database"])
    response = service.record_feedback_event(
        _feedback(result.response.retrieval_log_id, "fb-b", ["database"], FeedbackType.USER_CORRECTION)
    )
    assert response["status"] == "accepted"
    current = AuthorityRepository(db).get(
        tenant_id="tenant-1", user_id="user-1", memory_id="database", include_inactive=True
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.REVIEW
    assert current.content["text"] == "content for database"


def test_scenarios_d_and_e_only_used_memories_receive_outcome_feedback() -> None:
    db = Database(":memory:")
    db.init_schema()
    for index in range(10):
        _save_authority(db, f"m{index}")
    memories = [_memory(f"m{index}") for index in range(10)]
    service, _ = _service(db, memories)
    result = service.retrieve(_request("scenario-d"))
    assert len(result.response.context.relevant_memory_ids) == 10
    _used(service, result.response.retrieval_log_id, ["m1", "m7"])
    response = service.record_feedback_event(
        _feedback(result.response.retrieval_log_id, "fb-d", [f"m{index}" for index in range(10)], FeedbackType.TASK_SUCCESS)
    )
    assert response["attributed_memory_ids"] == ["m1", "m7"]
    assert response["unattributed_memory_ids"] == [f"m{index}" for index in range(10) if index not in {1, 7}]
    scores = [AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id=f"m{index}") for index in range(10)]
    assert scores[1].utility > 0.5 and scores[7].utility > 0.5
    assert all(scores[index].utility == 0.5 for index in range(10) if index not in {1, 7})

    unrelated = service.retrieve(_request("scenario-e", task_id="network-task"))
    response = service.record_feedback_event(
        _feedback(unrelated.response.retrieval_log_id, "fb-e", ["m1"], FeedbackType.TASK_FAILURE, task_id="network-task")
    )
    assert response["attributed_memory_ids"] == []
    unchanged = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="m1")
    assert unchanged is not None and unchanged.utility > 0.5


def test_scenarios_f_and_g_negative_cause_and_duplicate_replay() -> None:
    db = Database(":memory:")
    db.init_schema()
    _save_authority(db, "procedure", utility=0.8, stability=0.8)
    service, _ = _service(db, [_memory("procedure")])
    first = service.retrieve(_request("scenario-f"))
    _used(service, first.response.retrieval_log_id, ["procedure"])
    negative = service.record_feedback_event(
        _feedback(first.response.retrieval_log_id, "fb-f", ["procedure"], FeedbackType.TASK_FAILURE)
    )
    assert negative["attribution"] == "strong"
    after_failure = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="procedure")
    assert after_failure is not None and after_failure.utility < 0.8

    second = service.retrieve(_request("scenario-g1", task_id="task-g1"))
    _used(service, second.response.retrieval_log_id, ["procedure"], task_id="task-g1")
    event = _feedback(second.response.retrieval_log_id, "fb-g", ["procedure"], FeedbackType.EXPLICIT_POSITIVE, task_id="task-g1")
    service.record_feedback_event(event)
    once = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="procedure")
    assert once is not None
    service.record_feedback_event(event)
    twice = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="procedure")
    assert twice is not None and twice.utility == once.utility and twice.stability == once.stability


def test_scenarios_h_and_i_dormant_reactivation_and_forget_protection() -> None:
    db = Database(":memory:")
    db.init_schema()
    _save_authority(db, "dormant", utility=0.3, stability=0.3, status=EvolutionStatus.DORMANT)
    service, _ = _service(db, [_memory("dormant", status=EvolutionStatus.DORMANT)])
    result = service.retrieve(_request("scenario-h"))
    _used(service, result.response.retrieval_log_id, ["dormant"])
    response = service.record_feedback_event(
        _feedback(result.response.retrieval_log_id, "fb-h", ["dormant"], FeedbackType.EXPLICIT_POSITIVE)
    )
    assert response["evolution"][0]["new_status"] == EvolutionStatus.ACTIVE.value

    _save_authority(db, "forgotten", utility=0.5, stability=0.5)
    forgotten_service, _ = _service(db, [_memory("forgotten")])
    deleted_retrieval = forgotten_service.retrieve(_request("scenario-i"))
    _used(forgotten_service, deleted_retrieval.response.retrieval_log_id, ["forgotten"])
    ForgetService(db).execute(
        ForgetRequest(
            request_id="forget-scenario-i",
            idempotency_key="forget-scenario-i",
            tenant_id="tenant-1",
            user_id="user-1",
            instruction="forget forgotten",
            target_memory_ids=["forgotten"],
            dry_run=False,
            confirm=True,
        ),
        high_risk_authorized=True,
    )
    replay = forgotten_service.record_feedback_event(
        _feedback(
            deleted_retrieval.response.retrieval_log_id,
            "fb-i",
            ["forgotten"],
            FeedbackType.EXPLICIT_POSITIVE,
        )
    )
    assert replay["rejected_reason"] == "memory_deleted"
    current = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="forgotten", include_inactive=True)
    assert current is not None and current.evolution_status is EvolutionStatus.DELETED


def test_scenarios_j_and_l_scope_isolation_and_used_without_context() -> None:
    db = Database(":memory:")
    db.init_schema()
    _save_authority(db, "project-a", project_id="a")
    _save_authority(db, "project-b", project_id="b")
    service, _ = _service(db, [_memory("project-a", project_id="a"), _memory("project-b", project_id="b")])
    result = service.retrieve(_request("scenario-j", project_id="a"))
    assert result.response.context.relevant_memory_ids == ["project-a"]
    _used(service, result.response.retrieval_log_id, ["project-a"], project_id="a")
    response = service.record_feedback_event(
        _feedback(result.response.retrieval_log_id, "fb-j", ["project-a"], FeedbackType.EXPLICIT_POSITIVE, project_id="a")
    )
    assert response["status"] == "accepted"
    a = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="project-a")
    b = AuthorityRepository(db).get(tenant_id="tenant-1", user_id="user-1", memory_id="project-b")
    assert a is not None and b is not None and a.utility > b.utility

    invalid = service.record_usage_feedback(
        retrieval_id=result.response.retrieval_log_id,
        memory_ids=["project-b"],
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
    )
    assert invalid["untrusted"] == ["project-b"]
