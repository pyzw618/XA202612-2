from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
    MemoryEvidenceRow,
    MemoryLineageRow,
    MemoryProjectionOutboxRow,
    PreferenceRow,
)
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository

ROOT = Path(__file__).parents[1]
DB_PATH = ROOT / "evaluation" / "results" / "vnext_authority_write_test.db"


def _db() -> Database:
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    db = Database(str(DB_PATH))
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
        outbox = session.query(MemoryProjectionOutboxRow).one()
        assert (lineage.tenant_id, lineage.content_version) == ("tenant-a", 1)
        assert (evidence.tenant_id, evidence.content_version) == ("tenant-a", 1)
        assert (outbox.tenant_id, outbox.content_version, outbox.projection_type) == (
            "tenant-a",
            1,
            "long_term",
        )

    duplicate = service.write(event)
    assert duplicate.status is GatewayStatus.IDEMPOTENT
    with db.session() as session:
        assert session.query(ExtractionTaskRow).count() == 1
        assert session.query(MemoryEvidenceRow).count() == 1
    db.close()
