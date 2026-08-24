from __future__ import annotations

from memoryhub.adapter.schemas import MemoryDecision, PreferenceMemory
from memoryhub.core.domain_writer import DomainMemoryWriter
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import PreferenceRow
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker


def _db(tmp_path):
    db = Database(str(tmp_path / "projection_version.db"))
    db.init_schema()
    return db


def test_worker_bumps_projection_version_after_success(tmp_path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    memory = PreferenceMemory(user_id="u1", text="Versioned projection")
    receipt = writer.write(memory, action=MemoryDecision.NEW)

    projector = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        project_immediately=False,
    )
    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=projector,
    )
    result = worker.run_once()

    assert result.succeeded == [receipt.outbox_id]
    with db.session() as session:
        row = session.get(PreferenceRow, memory.memory_id)
        assert row.projection_version == row.version


def test_outbox_record_is_unique_per_event(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        first = repo.enqueue(
            memory_id="m1",
            memory_type="preference",
            operation="upsert",
            payload={"x": 1},
            session=session,
            tenant_id="t1",
            event_id="evt-1",
            content_version=1,
        )
        first_id = first.outbox_id
        second = repo.enqueue(
            memory_id="m1",
            memory_type="preference",
            operation="upsert",
            payload={"x": 1},
            session=session,
            tenant_id="t1",
            event_id="evt-1",
            content_version=1,
        )
        second_id = second.outbox_id
    assert first_id == second_id
