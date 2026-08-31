from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from memoryhub.adapter.schemas import MemoryWriteReceipt
from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway, GatewayStatus
from memoryhub.application.working_service import WorkingService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import (
    EpisodeEventContract,
    EpisodeSnapshot,
    EpisodeStatus,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
    WorkingPatch,
    WorkingPatchOperation,
    WorkingSnapshot,
)
from memoryhub.domain.long_term import (
    AuthorityStatusConflictError,
    AuthorityVersionConflictError,
    LongTermAuthorityFacade,
)
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import (
    EventRow,
    ExtractionTaskRow,
    IdempotencyRecordRow,
    KnowledgeRow,
    MemoryEvidenceRow,
    MemoryLineageRow,
    MemoryProjectionOutboxRow,
    PreferenceRow,
)
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository

ROOT = Path(__file__).parents[1]
DB_BASE = ROOT / "evaluation" / "results" / "vnext_authority_write_test"
_db_counter = 0


def _db() -> Database:
    import time

    global _db_counter
    _db_counter += 1
    db_path = DB_BASE.parent / f"{DB_BASE.name}_{int(time.time() * 1000)}_{_db_counter}.db"
    db = Database(str(db_path))
    db.init_schema()
    return db


def _envelope(
    *,
    memory_id: str = "pref-v1",
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    version: int = 1,
    status: EvolutionStatus = EvolutionStatus.ACTIVE,
) -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id=tenant_id,
        user_id=user_id,
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        normalized_key="report.format",
        content={"text": "Use DOCX", "payload": {"format": "docx"}},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        evolution_status=status,
        confidence=0.95,
        utility=0.8,
        content_version=version,
        evidence_refs=["event-authority"],
    )


def _event(event_id: str = "event-authority") -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        event_id=event_id,
        event_type="user_instruction",
        source_type="user_behavior",
        task_id="task-authority",
        session_id="session-authority",
        occurred_at=datetime.now(timezone.utc),
        payload={"instruction": "Use DOCX"},
        policy_action="ALLOW",
        source_hash=(event_id + "a" * 64)[:64],
        idempotency_key="idem-" + event_id,
        trace_id="trace-" + event_id,
    )


def test_authority_facade_unifies_legacy_preference_and_hides_inactive_versions() -> None:
    db = _db()
    repository = AuthorityRepository(db)
    facade = LongTermAuthorityFacade(repository)
    active = _envelope()
    repository.save(active)

    assert facade.read(tenant_id="tenant-a", user_id="user-a", memory_id="pref-v1") == active
    assert facade.read(tenant_id="tenant-b", user_id="user-a", memory_id="pref-v1") is None

    superseded = _envelope(
        memory_id="pref-v2", version=2, status=EvolutionStatus.SUPERSEDED
    )
    repository.save(superseded)
    assert facade.read(tenant_id="tenant-a", user_id="user-a", memory_id="pref-v2") is None
    assert (
        facade.read(
            tenant_id="tenant-a",
            user_id="user-a",
            memory_id="pref-v2",
            include_inactive=True,
        ).evolution_status
        is EvolutionStatus.SUPERSEDED
    )
    with db.session() as session:
        row = session.get(PreferenceRow, "pref-v1")
        assert row.tenant_id == "tenant-a"
        assert row.extra_payload["vnext_authority"]["scope"] == "PROJECT:reporting"
    db.close()


def test_authority_facade_enforces_one_active_chain_and_monotonic_version() -> None:
    db = _db()
    repository = AuthorityRepository(db)
    facade = LongTermAuthorityFacade(repository)
    repository.save(_envelope())

    try:
        facade.prepare(_envelope(memory_id="pref-v2", version=2))
    except AuthorityStatusConflictError:
        pass
    else:
        raise AssertionError("a second ACTIVE version must be rejected")

    with db.session() as session:
        row = session.get(PreferenceRow, "pref-v1")
        metadata = dict(row.extra_payload)
        authority_metadata = dict(metadata["vnext_authority"])
        authority_metadata["evolution_status"] = EvolutionStatus.ARCHIVED.value
        metadata["vnext_authority"] = authority_metadata
        session.query(PreferenceRow).filter_by(memory_id="pref-v1").update(
            {PreferenceRow.status: "archived", PreferenceRow.extra_payload: metadata}
        )
    repository.save(_envelope(memory_id="pref-v2", version=2))
    try:
        facade.validate(_envelope(memory_id="pref-v2", version=1))
    except AuthorityVersionConflictError:
        pass
    else:
        raise AssertionError("a stale content version must be rejected")
    db.close()


def test_authority_facade_maps_fact_procedure_and_episode_types() -> None:
    db = _db()
    repository = AuthorityRepository(db)
    values = [
        LongTermEnvelope(
            tenant_id="tenant-a",
            user_id="user-a",
            memory_id="fact-v1",
            memory_type=MemoryType.SEMANTIC,
            normalized_key="python.version",
            content={"subject": "Python", "predicate": "version", "object_value": "3.11"},
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            confidence=0.9,
            utility=0.5,
            evidence_refs=["event-fact"],
        ),
        LongTermEnvelope(
            tenant_id="tenant-a",
            user_id="user-a",
            memory_id="procedure-v1",
            memory_type=MemoryType.PROCEDURAL,
            normalized_key="report.repair",
            content={"name": "repair", "steps": ["inspect", "verify"]},
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:reporting",
            confidence=0.9,
            utility=0.7,
            evidence_refs=["event-procedure"],
        ),
        LongTermEnvelope(
            tenant_id="tenant-a",
            user_id="user-a",
            memory_id="episode-v1",
            memory_type=MemoryType.EPISODIC,
            normalized_key="report.incident",
            content={"content": "recovered report"},
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:reporting",
            confidence=0.8,
            utility=0.4,
            evidence_refs=["event-episode"],
        ),
    ]
    for value in values:
        repository.save(value)
    stored = repository.list(tenant_id="tenant-a", user_id="user-a")
    assert {value.memory_type for value in stored} == {
        MemoryType.SEMANTIC,
        MemoryType.PROCEDURAL,
        MemoryType.EPISODIC,
    }
    db.close()


def test_canonical_write_commits_task_state_reflection_and_long_term_authority() -> None:
    db = _db()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    facade = LongTermAuthorityFacade(authority)
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        project_immediately=False,
    )
    working = WorkingService(WorkingStateRepository(db))
    episodes = EpisodeService(EpisodeRepository(db))
    episodes.create(
        episode_id="episode-authority",
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-authority",
        goal="write report",
    )
    service = CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=working,
        episode_service=episodes,
        authority_facade=facade,
        memory_write_service=writer,
        formation_mode="authority",
    )
    snapshot = WorkingSnapshot(
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-authority",
        session_id="session-authority",
        current_goal="write report",
        current_step="draft",
        pending_steps=["review"],
    )
    patch = WorkingPatch(
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-authority",
        base_version=1,
        operations=[
            WorkingPatchOperation(op="replace", path="/current_step", value="review")
        ],
        event_refs=["event-authority"],
        reason="checkpoint",
    )
    episode_event = EpisodeEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-authority",
        task_id="task-authority",
        seq_no=1,
        event_type="PHASE_CHECKPOINT",
        payload={"phase": "review"},
        source_event_id="event-authority",
    )
    episode_snapshot = EpisodeSnapshot(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-authority",
        task_id="task-authority",
        session_id="session-authority",
        status=EpisodeStatus.ACTIVE,
        current_phase="review",
        goal="write report",
        pending_steps=["review"],
        last_event_seq=1,
    )
    event = _event()
    result = service.write(
        event,
        working_snapshot=snapshot,
        working_state_id="working-authority",
        working_patch=patch,
        episode_event=episode_event,
        episode_snapshot=episode_snapshot,
        long_term=_envelope(),
    )
    assert result.status is GatewayStatus.COMMITTED
    assert result.working is not None and result.working.version == 2
    assert result.episode_event is not None and result.episode_event.seq_no == 1
    assert result.reflection_task is not None
    assert isinstance(result.long_term_receipt, MemoryWriteReceipt)

    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1
        assert session.query(ExtractionTaskRow).count() == 1
        assert session.query(PreferenceRow).count() == 1
        lineage = session.query(MemoryLineageRow).one()
        evidence = session.query(MemoryEvidenceRow).one()
        outbox_rows = session.query(MemoryProjectionOutboxRow).all()
        assert len(outbox_rows) == 2
        types = {row.projection_type for row in outbox_rows}
        assert types == {"long_term", "vector"}
        assert (lineage.tenant_id, lineage.content_version) == ("tenant-a", 1)
        assert (evidence.tenant_id, evidence.content_version) == ("tenant-a", 1)

    duplicate = service.write(event)
    assert duplicate.status is GatewayStatus.IDEMPOTENT
    with db.session() as session:
        assert session.query(ExtractionTaskRow).count() == 1
        assert session.query(MemoryEvidenceRow).count() == 1
    db.close()


def _candidate_only_service(db: Database) -> CanonicalWriteService:
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    facade = LongTermAuthorityFacade(authority)
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        project_immediately=False,
    )
    return CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        authority_facade=facade,
        memory_write_service=writer,
        formation_mode="candidate-only",
    )


def test_candidate_only_rejects_long_term_payload() -> None:
    """candidate-only + _long_term → Authority is not written and Formation fails fast."""
    db = _db()
    service = _candidate_only_service(db)

    with pytest.raises(ValueError, match="long_term writes"):
        service.write(_event(), long_term=_envelope())

    with db.session() as session:
        assert session.query(PreferenceRow).count() == 0
        assert session.query(KnowledgeRow).count() == 0
    db.close()


def test_candidate_only_normal_formation_creates_candidate_not_authority() -> None:
    """Normal candidate formation creates a Candidate but never touches Authority."""
    db = _db()
    from memoryhub.application.formation_worker import FormationWorker
    from memoryhub.application.reflection_service import (
        DeterministicReflectionModel,
        ReflectionService,
    )
    from memoryhub.core.ingestion.retry import ExtractionRetryService
    from memoryhub.storage.database import EventRepository
    from memoryhub.storage.vnext_repositories import CandidateRepository

    service = _candidate_only_service(db)
    tasks = service.extraction_tasks
    worker = FormationWorker(
        db,
        task_repository=tasks,
        event_repository=EventRepository(db),
        canonical_write_service=service,
        mode="candidate-only",
        reflection_service=ReflectionService(
            model=DeterministicReflectionModel(), max_retries=0
        ),
    )
    retry = ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )

    event = _event("event-candidate-formation")
    result = service.write(event)
    assert result.reflection_task is not None

    run = retry.run_due(user_id=event.user_id)
    assert run.succeeded == 1

    with db.session() as session:
        assert session.query(PreferenceRow).count() == 0
        assert session.query(KnowledgeRow).count() == 0
        candidates = CandidateRepository(db).list_for_review(
            tenant_id=event.tenant_id, user_id=event.user_id
        )
        assert len(candidates) == 1
    db.close()


def test_explicit_authority_writer_routes_through_safety_gate() -> None:
    """The separated write_authority interface still commits Authority in any mode."""
    db = _db()
    service = _candidate_only_service(db)

    envelope, receipt = service.write_authority(_event(), _envelope())
    assert envelope.memory_id == "pref-v1"
    assert isinstance(receipt, MemoryWriteReceipt)

    with db.session() as session:
        assert session.query(PreferenceRow).count() == 1
    db.close()
