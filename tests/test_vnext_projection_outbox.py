from __future__ import annotations

from datetime import datetime, timedelta

from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import MemoryProjectionOutboxRow


def _db(tmp_path):
    db = Database(str(tmp_path / "outbox.db"))
    db.init_schema()
    return db


def _enqueue(repo, session, *, operation: str = "upsert", priority: int | None = None):
    return repo.enqueue(
        memory_id="m1",
        memory_type="preference",
        operation=operation,
        payload={"memory_id": "m1", "memory_type": "preference", "operation": operation},
        session=session,
        tenant_id="t1",
        user_id="u1",
        content_version=2,
        priority=priority,
    )


def test_delete_operations_get_high_priority(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        row = _enqueue(repo, session, operation="delete")
        assert row.priority == 10


def test_claim_returns_lease_token_and_expires_at(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session)
    items = repo.claim_ready(lease_seconds=120)
    assert len(items) == 1
    item = items[0]
    assert item.lease_token
    assert len(item.lease_token) == 32
    assert item.lease_version == 1
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
        assert row.lease_expires_at is not None
        assert row.lease_expires_at > datetime.now()


def test_mark_succeeded_requires_lease_token(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session)
    item = repo.claim_ready()[0]
    assert repo.mark_succeeded(item.outbox_id, lease_token="wrong-token") is False
    assert repo.mark_succeeded(item.outbox_id, lease_token=item.lease_token) is True


def test_mark_failed_applies_backoff_and_dead_letter(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session, priority=5)
    item = None
    for _ in range(5):
        item = repo.claim_ready()[0]
        repo.mark_failed(item.outbox_id, error_code="projection.fail", lease_token=item.lease_token)
        with db.session() as session:
            row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
            row.next_retry_at = datetime.now() - timedelta(seconds=1)
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
        assert row.status == "dead_letter"
        assert row.dead_lettered_at is not None


def test_claim_prioritizes_delete_and_older_created(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session, operation="upsert", priority=0)
        _enqueue(repo, session, operation="delete", priority=10)
    items = repo.claim_ready(limit=10)
    assert items[0].operation == "delete"
    assert items[1].operation == "upsert"


def test_reclaim_expired_lease(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session)
    item = repo.claim_ready(lease_seconds=1)[0]
    import time

    time.sleep(1.1)
    reclaimed = repo.claim_ready(lease_seconds=60)
    assert len(reclaimed) == 1
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
        assert row.status == "processing"
        assert row.lease_token != item.lease_token
        assert row.error_code == "projection.lease_expired"


def test_replay_resets_failed_and_dead_letter(tmp_path) -> None:
    db = _db(tmp_path)
    repo = MemoryProjectionOutboxRepository(db)
    with db.session() as session:
        _enqueue(repo, session)
    item = repo.claim_ready()[0]
    repo.mark_failed(item.outbox_id, error_code="projection.fail", lease_token=item.lease_token)
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
        assert row.attempts == 1
    count = repo.replay([item.outbox_id])
    assert count == 1
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, item.outbox_id)
        assert row.status == "pending"
        assert row.attempts == 0
        assert row.dead_lettered_at is None
