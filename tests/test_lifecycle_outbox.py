from __future__ import annotations

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryDecision,
    MemoryStatus,
    PreferenceMemory,
    SourceType,
)
from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.core.lifecycle.manager import LifecycleManager
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import MemoryEvidenceRow, MemoryLineageRow, MemoryProjectionOutboxRow
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker


class _Projector:
    def __init__(self):
        self.calls = []

    def sync_memory(self, memory, *, remove=False):
        self.calls.append((memory.memory_id, remove))


def _setup(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        project_immediately=False,
    )
    pref_repo.write_service = writer
    know_repo.write_service = writer
    return db, pref_repo, know_repo, writer


def test_lifecycle_archive_writes_lineage_and_outbox_remove_projection(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Archive me")
    writer.upsert_memory(memory, action=MemoryDecision.NEW)

    LifecycleManager(pref_repo=pref_repo, know_repo=know_repo).expire(memory)

    with db.session() as session:
        stored = pref_repo.get_by_id(memory.memory_id)
        actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == memory.memory_id)
            .order_by(MemoryLineageRow.evidence_revision)
        ]
        jobs = (
            session.query(MemoryProjectionOutboxRow)
            .filter(MemoryProjectionOutboxRow.memory_id == memory.memory_id)
            .order_by(MemoryProjectionOutboxRow.created_at)
            .all()
        )
        assert stored.status.value == "archived"
        assert actions == ["new", "supersede"]
        assert len(jobs) == 2

    projector = _Projector()
    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=projector,
    )
    worker.run_once()
    assert projector.calls[-1] == (memory.memory_id, False)
    db.close()


def test_forgetter_deletes_through_writer_and_retains_authoritative_evidence(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Forget me")
    writer.upsert_memory(memory, action=MemoryDecision.NEW)

    with db.session() as session:
        before = session.query(MemoryEvidenceRow).filter(
            MemoryEvidenceRow.memory_id == memory.memory_id
        ).count()

    forgetter = MemoryForgetter(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=writer,
    )
    assert forgetter.delete_memories([memory.memory_id], user_id="u1") == 1

    with db.session() as session:
        stored = pref_repo.get_by_id(memory.memory_id)
        actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == memory.memory_id)
            .order_by(MemoryLineageRow.evidence_revision)
        ]
        after = session.query(MemoryEvidenceRow).filter(
            MemoryEvidenceRow.memory_id == memory.memory_id
        ).count()
        delete_job = (
            session.query(MemoryProjectionOutboxRow)
            .filter(
                MemoryProjectionOutboxRow.memory_id == memory.memory_id,
                MemoryProjectionOutboxRow.operation == "delete",
            )
            .one()
        )
        assert stored.status.value == "deleted"
        assert actions == ["new", "supersede"]
        assert after == before
        assert delete_job.status == "pending"
    db.close()


def test_fact_lifecycle_transition_appends_lineage_and_delete_outbox(tmp_path):
    db, _, _, writer = _setup(tmp_path)
    fact = KnowledgeMemory(
        memory_id="fact_lifecycle",
        user_id="u1",
        knowledge_type=KnowledgeType.FACT,
        subject="Project A",
        predicate="owner",
        object_value="Alice",
        object_type="Person",
        content="Project A owner is Alice",
        confidence=0.9,
        evidences=[
            Evidence(
                event_id="evt_fact",
                content="fact source",
                source_type=SourceType.TOOL_RESULT,
            )
        ],
    )
    writer.upsert_memory(fact, action=MemoryDecision.NEW)

    fact.status = MemoryStatus.DELETED
    writer.upsert_memory(fact, action=MemoryDecision.SUPERSEDE)

    with db.session() as session:
        lineage = (
            session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == fact.memory_id)
            .order_by(MemoryLineageRow.evidence_revision)
            .all()
        )
        outbox = (
            session.query(MemoryProjectionOutboxRow)
            .filter(
                MemoryProjectionOutboxRow.memory_id == fact.memory_id,
                MemoryProjectionOutboxRow.operation == "delete",
            )
            .one()
        )
        assert [row.transition_action for row in lineage] == ["new", "supersede"]
        assert outbox.operation == "delete"
    db.close()
