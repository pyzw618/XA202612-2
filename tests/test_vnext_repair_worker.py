from __future__ import annotations

from memoryhub.adapter.schemas import MemoryDecision, PreferenceMemory
from memoryhub.core.domain_writer import DomainMemoryWriter
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import MemoryProjectionOutboxRow, PreferenceRow
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker
from memoryhub.storage.repair import RepairService, RepairWorker


def _db(tmp_path):
    db = Database(str(tmp_path / "repair_worker.db"))
    db.init_schema()
    return db


def _project(worker: ProjectionOutboxWorker) -> None:
    while True:
        result = worker.run_once(limit=10)
        if not result.succeeded and not result.failed:
            break


def test_repair_detects_missing_projection(tmp_path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    memory = PreferenceMemory(user_id="u1", text="Missing projection")
    writer.write(memory, action=MemoryDecision.NEW)

    authority = AuthorityRepository(db)
    outbox = MemoryProjectionOutboxRepository(db)
    repair = RepairService(db, authority, outbox_repo=outbox)
    diagnostic = repair.repair_one(memory.memory_id, "preference")

    assert diagnostic.category == "missing"
    assert diagnostic.action == "upsert"


def test_repair_detects_stale_projection(tmp_path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    memory = PreferenceMemory(user_id="u1", text="Stale projection")
    writer.write(memory, action=MemoryDecision.NEW)

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
    _project(worker)

    with db.session() as session:
        row = session.get(PreferenceRow, memory.memory_id)
        row.version = row.version + 1

    authority = AuthorityRepository(db)
    outbox = MemoryProjectionOutboxRepository(db)
    repair = RepairService(db, authority, outbox_repo=outbox)
    diagnostic = repair.repair_one(memory.memory_id, "preference")

    assert diagnostic.category == "stale"
    assert diagnostic.action == "upsert"


def test_repair_worker_scans_and_enqueues_repairs(tmp_path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    memory = PreferenceMemory(user_id="u1", text="Scan repair")
    writer.write(memory, action=MemoryDecision.NEW)

    authority = AuthorityRepository(db)
    outbox = MemoryProjectionOutboxRepository(db)
    repair = RepairService(db, authority, outbox_repo=outbox)
    worker = RepairWorker(repair)
    diagnostics = worker.run_once()

    assert len(diagnostics) == 1
    assert diagnostics[0].category == "missing"


def test_repair_dry_run_does_not_enqueue(tmp_path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    memory = PreferenceMemory(user_id="u1", text="Dry run")
    writer.write(memory, action=MemoryDecision.NEW)

    with db.session() as session:
        before = session.query(MemoryProjectionOutboxRow).count()

    authority = AuthorityRepository(db)
    outbox = MemoryProjectionOutboxRepository(db)
    repair = RepairService(db, authority, outbox_repo=outbox)
    diagnostic = repair.repair_one(memory.memory_id, "preference", dry_run=True)

    assert diagnostic.action == "upsert"
    with db.session() as session:
        after = session.query(MemoryProjectionOutboxRow).count()
        assert after == before
