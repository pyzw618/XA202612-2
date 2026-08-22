from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from memoryhub.adapter.vnext_schemas import APIErrorCode
from memoryhub.application.event_gateway import EventGateway, GatewayStatus
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.storage.database import Database
from memoryhub.storage.models import (
    EventRow,
    IdempotencyRecordRow,
    MemoryCandidateRow,
    MemoryEvidenceRow,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db() -> Database:
    db_path = ROOT / "evaluation" / "results" / "vnext_gateway_test.db"
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    database = Database(str(db_path))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def _event(
    *,
    event_id: str,
    tenant_id: str = "tenant-a",
    user_id: str = "user-a",
    idempotency_key: str | None = None,
    action: str = "ALLOW",
    payload: dict | None = None,
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id=tenant_id,
        user_id=user_id,
        event_id=event_id,
        event_type="user_instruction",
        source_type="user",
        task_id="task-1",
        session_id="session-1",
        occurred_at=datetime.now(timezone.utc),
        payload=payload or {"instruction": "use DOCX"},
        policy_action=action,
        source_hash=(event_id + "0" * 64)[:64],
        idempotency_key=idempotency_key or f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def test_gateway_policy_then_atomic_event_and_idempotency_commit(db: Database) -> None:
    calls: list[str] = []

    def policy(event: MemoryEventContract) -> MemoryEventContract:
        calls.append("policy")
        return event

    gateway = EventGateway(db, policy=policy)
    result = gateway.submit(_event(event_id="evt-1"))

    assert result.status is GatewayStatus.COMMITTED
    assert calls == ["policy"]
    with db.session() as session:
        assert session.query(EventRow).filter_by(event_id="evt-1").count() == 1
        record = session.query(IdempotencyRecordRow).one()
        assert record.request_hash
        assert record.event_id == "evt-1"
        assert record.response_ref is None


def test_gateway_duplicate_is_idempotent_and_conflicting_retry_is_rejected(
    db: Database,
) -> None:
    gateway = EventGateway(db, policy=lambda event: event)
    first = _event(event_id="evt-1", idempotency_key="same-key")
    assert gateway.submit(first).status is GatewayStatus.COMMITTED
    assert gateway.submit(first).status is GatewayStatus.IDEMPOTENT

    conflicting = _event(
        event_id="evt-2",
        idempotency_key="same-key",
        payload={"instruction": "use PDF"},
    )
    result = gateway.submit(conflicting)
    assert result.status is GatewayStatus.CONFLICT
    assert result.reason_code == "idempotency_conflict"
    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1


def test_review_and_drop_never_persist_raw_payload_or_idempotency_metadata(
    db: Database,
) -> None:
    raw = {"secret": "should-not-enter-storage"}
    review = EventGateway(db, policy=lambda event: event).submit(
        _event(event_id="evt-review", action="REVIEW", payload=raw)
    )
    dropped = EventGateway(db, policy=lambda event: event).submit(
        _event(event_id="evt-drop", action="DROP", payload=raw)
    )
    assert review.status is GatewayStatus.REVIEW
    assert dropped.status is GatewayStatus.REJECTED
    assert review.action == "REVIEW"
    assert dropped.action == "DROP"
    with db.session() as session:
        assert session.query(EventRow).count() == 0
        assert session.query(IdempotencyRecordRow).count() == 0


def test_mask_persists_only_policy_returned_sanitized_payload(db: Database) -> None:
    raw = _event(event_id="evt-mask", action="MASK", payload={"secret": "raw"})

    def policy(event: MemoryEventContract) -> MemoryEventContract:
        return event.model_copy(update={"payload": {"content_ref": "sha256:" + "a" * 64}})

    result = EventGateway(db, policy=policy).submit(raw)
    assert result.status is GatewayStatus.COMMITTED
    with db.session() as session:
        row = session.query(EventRow).one()
        assert row.payload == {"content_ref": "sha256:" + "a" * 64}


def test_mask_without_a_payload_change_fails_closed_without_persistence(db: Database) -> None:
    event = _event(event_id="evt-mask-raw", action="MASK", payload={"secret": "raw"})
    result = EventGateway(db, policy=lambda event: event).submit(event)

    assert result.status is GatewayStatus.REJECTED
    assert result.reason_code == "policy_mask_not_sanitized"
    with db.session() as session:
        assert session.query(EventRow).count() == 0
        assert session.query(IdempotencyRecordRow).count() == 0


def test_identity_and_scope_checks_happen_before_policy_and_are_tenant_scoped(
    db: Database,
) -> None:
    calls: list[str] = []
    gateway = EventGateway(
        db,
        policy=lambda event: calls.append("policy") or event,
        identity_check=lambda event: event.tenant_id == "tenant-a",
        scope_check=lambda event: event.task_id == "task-allowed",
    )
    unauthorized = gateway.submit(_event(event_id="evt-unauth", tenant_id="tenant-b"))
    assert unauthorized.status is GatewayStatus.REJECTED
    assert unauthorized.reason_code == "identity_rejected"
    assert calls == []

    scope_calls: list[str] = []
    scope_gateway = EventGateway(
        db,
        policy=lambda event: scope_calls.append("policy") or event,
        identity_check=lambda event: True,
        scope_check=lambda event: False,
    )
    scope_rejected = scope_gateway.submit(_event(event_id="evt-scope"))
    assert scope_rejected.status is GatewayStatus.REJECTED
    assert scope_rejected.reason_code == "scope_rejected"
    assert scope_calls == []

    tenant_a = _event(event_id="evt-a", idempotency_key="same", tenant_id="tenant-a")
    tenant_b = _event(
        event_id="evt-b", idempotency_key="same", tenant_id="tenant-b", user_id="user-b"
    )
    allowed_gateway = EventGateway(
        db, policy=lambda event: event, scope_check=lambda event: True
    )
    assert allowed_gateway.submit(tenant_a).status is GatewayStatus.COMMITTED
    assert allowed_gateway.submit(tenant_b).status is GatewayStatus.COMMITTED
    with db.session() as session:
        assert session.query(IdempotencyRecordRow).count() == 2


def test_concurrent_duplicate_submit_commits_once_and_replays_idempotently(
    db: Database,
) -> None:
    gateway = EventGateway(db, policy=lambda event: event)
    event = _event(event_id="evt-concurrent", idempotency_key="idem-concurrent")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: gateway.submit(event), range(8)))

    assert [result.status for result in results].count(GatewayStatus.COMMITTED) == 1
    assert [result.status for result in results].count(GatewayStatus.IDEMPOTENT) == 7
    with db.session() as session:
        assert session.query(EventRow).count() == 1
        assert session.query(IdempotencyRecordRow).count() == 1


def test_duplicate_gateway_submit_does_not_mutate_evidence_or_frequency(
    db: Database,
) -> None:
    event = _event(event_id="evt-downstream", idempotency_key="idem-downstream")
    with db.session() as session:
        session.add(
            MemoryCandidateRow(
                candidate_id="candidate-downstream",
                tenant_id="tenant-a",
                user_id="user-a",
                memory_type="PREFERENCE",
                normalized_key="format.report",
                claim={"value": "DOCX"},
                scope_level="PROJECT",
                scope="PROJECT:reporting",
                frequency=3,
            )
        )
        session.add(
            MemoryEvidenceRow(
                evidence_id="evidence-downstream",
                tenant_id="tenant-a",
                user_id="user-a",
                memory_id="memory-downstream",
                memory_type="PREFERENCE",
                event_id=event.event_id,
                source_hash=event.source_hash,
                content_ref="sha256:" + "b" * 64,
                source_type="user",
            )
        )

    gateway = EventGateway(db, policy=lambda event: event)
    assert gateway.submit(event).status is GatewayStatus.COMMITTED
    assert gateway.submit(event).status is GatewayStatus.IDEMPOTENT

    with db.session() as session:
        candidate = session.query(MemoryCandidateRow).one()
        assert candidate.frequency == 3
        assert session.query(MemoryEvidenceRow).count() == 1


def test_event_id_conflict_uses_global_event_primary_key_scope(db: Database) -> None:
    gateway = EventGateway(db, policy=lambda event: event)
    assert gateway.submit(_event(event_id="evt-global", tenant_id="tenant-a")).status is (
        GatewayStatus.COMMITTED
    )
    result = gateway.submit(_event(event_id="evt-global", tenant_id="tenant-b"))

    assert result.status is GatewayStatus.CONFLICT
    assert result.reason_code == "event_id_conflict"


def test_gateway_error_code_contract_remains_stable() -> None:
    assert APIErrorCode.IDEMPOTENCY_CONFLICT.value == "IDEMPOTENCY_CONFLICT"


def test_gateway_requires_an_explicit_policy_processor(db: Database) -> None:
    with pytest.raises(ValueError, match="policy processor"):
        EventGateway(db, policy=None)  # type: ignore[arg-type]
