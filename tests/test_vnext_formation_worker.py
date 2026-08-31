from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionModel,
    ReflectionService,
)
from memoryhub.application.working_service import WorkingService
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.models import MemoryEvidenceRow, MemoryLineageRow
from memoryhub.storage.vnext_repositories import (
    CandidateRepository,
    EpisodeRepository,
    WorkingStateRepository,
)


def _event(event_id: str, task_id: str, text: str, **payload) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-formation",
        user_id="user-formation",
        event_id=event_id,
        event_type="user_instruction",
        source_type="user_behavior",
        task_id=task_id,
        session_id=f"session-{task_id}",
        occurred_at=datetime.now(timezone.utc),
        payload={"text": text, **payload},
        policy_action="ALLOW",
        source_hash=(event_id + "a" * 64)[:64],
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def _stack(
    *,
    mode: str = "candidate-only",
    reflection_service: ReflectionService | None = None,
):
    if reflection_service is None:
        reflection_service = ReflectionService(
            model=DeterministicReflectionModel(), max_retries=0
        )
    db_path = Path(__file__).parents[1] / "evaluation" / "results" / (
        f"vnext_formation_worker_{mode}_{time.time_ns()}.db"
    )
    db = Database(str(db_path))
    db.init_schema()
    pref = PreferenceRepository(db)
    know = KnowledgeRepository(db)
    authority = LongTermAuthorityFacade(
        AuthorityRepository(db, preference_repository=pref, knowledge_repository=know)
    )
    writer = MemoryWriteService(pref_repo=pref, know_repo=know, project_immediately=False)
    tasks = ExtractionTaskRepository(db)
    canonical = CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        extraction_tasks=tasks,
        authority_facade=authority,
        memory_write_service=writer,
        formation_mode=mode,
    )
    worker = FormationWorker(
        db,
        task_repository=tasks,
        event_repository=EventRepository(db),
        canonical_write_service=canonical,
        mode=mode,
        reflection_service=reflection_service,
    )
    retry = ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )
    return db, canonical, worker, retry, tasks


def test_single_preference_is_candidate_only_and_task_reports_result():
    db, canonical, _worker, retry, tasks = _stack()
    event = _event("event-one", "task-one", "This time use DOCX")
    result = canonical.write(event)

    run = retry.run_due(user_id=event.user_id)
    task = tasks.get(result.reflection_task.task_id, user_id=event.user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=event.tenant_id, user_id=event.user_id
    )
    assert run.succeeded == 1
    assert task is not None and task.candidate_ids
    assert task.candidate_statuses[task.candidate_ids[0]] == "ACCUMULATING"
    assert len(candidates) == 1
    assert PreferenceRepository(db).list_all(user_id=event.user_id) == []
    assert db.session_factory is not None
    with db.session() as session:
        assert (
            session.query(MemoryEvidenceRow)
            .filter_by(memory_id=task.candidate_ids[0])
            .count()
            == 1
        )
    db.close()


def test_independent_evidence_promotes_through_canonical_authority():
    db, canonical, _worker, retry, tasks = _stack(mode="authority")
    first = canonical.write(_event("event-a", "task-a", "This time use DOCX"))
    second = canonical.write(_event("event-b", "task-b", "This time use DOCX"))
    assert retry.run_due(user_id="user-formation").succeeded == 2

    first_task = tasks.get(first.reflection_task.task_id, user_id="user-formation")
    second_task = tasks.get(second.reflection_task.task_id, user_id="user-formation")
    assert first_task is not None and second_task is not None
    assert second_task.memory_ids
    assert len(PreferenceRepository(db).list_all(user_id="user-formation")) == 1
    memory_id = second_task.memory_ids[0]
    with db.session() as session:
        assert session.query(MemoryEvidenceRow).filter_by(memory_id=memory_id).count() >= 2
        assert session.query(MemoryLineageRow).filter_by(memory_id=memory_id).count() >= 1
    db.close()


def test_two_successes_and_failure_form_a_procedure():
    db, canonical, _worker, retry, tasks = _stack(mode="authority")
    common = {
        "trigger": "export fails",
        "preconditions": ["report exists"],
        "steps": ["inspect log", "restart exporter"],
        "verification": ["output exists"],
        "failure_recovery": [{"condition": "restart fails", "action": "rollback"}],
    }
    events = [
        _event("proc-1", "proc-task-1", "repair export", outcome="success", **common),
        _event("proc-2", "proc-task-2", "repair export", outcome="success", **common),
        _event("proc-3", "proc-task-3", "repair export", outcome="failed", **common),
    ]
    results = [canonical.write(event) for event in events]
    assert retry.run_due(user_id="user-formation").succeeded == 3
    completed = [
        tasks.get(item.reflection_task.task_id, user_id="user-formation")
        for item in results
    ]
    assert any(task is not None and task.memory_ids for task in completed)
    assert any(
        item.memory_type == "knowledge"
        for item in KnowledgeRepository(db).list_all(user_id="user-formation")
    )
    db.close()


def test_redelivery_does_not_duplicate_authority_lineage_or_evidence():
    db, canonical, worker, retry, tasks = _stack(mode="authority")
    canonical.write(_event("dup-1", "dup-task-1", "This time use DOCX"))
    second = canonical.write(_event("dup-2", "dup-task-2", "This time use DOCX"))
    assert retry.run_due(user_id="user-formation").succeeded == 2
    task = tasks.get(second.reflection_task.task_id, user_id="user-formation")
    assert task is not None and task.memory_ids
    memory_id = task.memory_ids[0]
    with db.session() as session:
        before_lineage = session.query(MemoryLineageRow).filter_by(memory_id=memory_id).count()
        before_evidence = session.query(MemoryEvidenceRow).filter_by(memory_id=memory_id).count()
    contract = EventRepository(db).get_vnext_contract("dup-2")
    assert contract is not None
    worker.execute(task, [contract])
    with db.session() as session:
        assert (
            session.query(MemoryLineageRow).filter_by(memory_id=memory_id).count()
            == before_lineage
        )
        assert (
            session.query(MemoryEvidenceRow).filter_by(memory_id=memory_id).count()
            == before_evidence
        )
    db.close()


def test_invalid_reflection_output_does_not_stage_a_candidate():
    class InvalidModel(ReflectionModel):
        model_id = "invalid-reflection/v1"

        def generate(self, prompt, *, input_hash, input_data=None):
            return {"candidate_id": "missing-required-fields"}

    reflection = ReflectionService(model=InvalidModel(), max_retries=0)
    db, canonical, _worker, retry, tasks = _stack(reflection_service=reflection)
    event = _event("invalid-reflection", "invalid-task", "Use DOCX")
    result = canonical.write(event)

    run = retry.run_due(user_id=event.user_id)
    task = tasks.get(result.reflection_task.task_id, user_id=event.user_id)
    candidates = CandidateRepository(db).list_for_review(
        tenant_id=event.tenant_id, user_id=event.user_id
    )

    assert run.retried == 1
    assert task is not None and task.candidate_ids == []
    assert candidates == []
    db.close()
