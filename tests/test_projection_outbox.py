from __future__ import annotations

from memoryhub.adapter.schemas import MemoryDecision, PreferenceMemory
from memoryhub.core.domain_writer import DomainMemoryWriter
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import MemoryProjectionOutboxRow
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker


class _Projector:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, bool]] = []

    def sync_memory(self, memory, *, remove: bool = False) -> None:
        if self.fail:
            raise RuntimeError("vector backend unavailable")
        self.calls.append((memory.memory_id, remove))


def _setup(tmp_path):
    db = Database(str(tmp_path / "outbox.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = DomainMemoryWriter(db=db, pref_repo=pref_repo, know_repo=know_repo)
    return db, pref_repo, know_repo, writer


def test_projection_worker_completes_outbox_without_rewriting_business_memory(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Use concise bullet points")
    receipt = writer.write(memory, action=MemoryDecision.NEW)
    projector = _Projector()
    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=projector,
    )

    result = worker.run_once()

    assert result.succeeded == [receipt.outbox_id]
    assert projector.calls == [(memory.memory_id, False)]
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)
        assert row.status == "completed"
        assert row.attempts == 1
        assert pref_repo.get_by_id(memory.memory_id) is not None
    db.close()


def test_projection_worker_records_stable_error_backoff_and_replay(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Retry projection")
    receipt = writer.write(memory, action=MemoryDecision.NEW)
    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=_Projector(fail=True),
        base_retry_seconds=2,
        max_retry_seconds=60,
    )

    first = worker.run_once()

    assert first.failed == [receipt.outbox_id]
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)
        assert row.status == "failed"
        assert row.error_code == "projection.vector_failed"
        assert row.attempts == 1
        assert row.next_retry_at is not None

    recovered = _Projector()
    worker.memory_write_service = recovered
    result = worker.replay([receipt.outbox_id])

    assert result.succeeded == [receipt.outbox_id]
    assert recovered.calls == [(memory.memory_id, False)]
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)
        assert row.status == "completed"
        # replay resets attempts before the retry, so the successful attempt is counted as 1.
        assert row.attempts == 1
    db.close()


def test_projection_outbox_reclaims_stale_processing_lease(tmp_path):
    db, pref_repo, know_repo, writer = _setup(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Stale lease")
    receipt = writer.write(memory, action=MemoryDecision.NEW)
    repo = MemoryProjectionOutboxRepository(db)
    first_lease = repo.claim_ready()
    assert first_lease[0].outbox_id == receipt.outbox_id

    # Mark the lease old, then verify a subsequent worker can reclaim it.
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)
        from datetime import datetime, timedelta

        row.lease_expires_at = datetime.now() - timedelta(seconds=600)
        row.updated_at = datetime.now() - timedelta(seconds=600)

    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=_Projector(),
    )
    result = worker.run_once()

    assert result.succeeded == [receipt.outbox_id]
    db.close()


def test_outbox_only_memory_write_defers_runtime_projection_until_worker_runs(tmp_path):
    db = Database(str(tmp_path / "outbox-only.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    lookup: dict[str, PreferenceMemory] = {}
    service = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_lookup=lookup,
        project_immediately=False,
    )
    memory = PreferenceMemory(user_id="u1", text="Production writes use the outbox")

    receipt = service.upsert_memory(memory)

    assert receipt is not None
    assert lookup == {}
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)
        assert row.status == "pending"

    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=service,
    )
    result = worker.run_once()

    assert result.succeeded == [receipt.outbox_id]
    assert lookup[memory.memory_id].memory_id == memory.memory_id
    db.close()
