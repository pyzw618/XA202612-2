from __future__ import annotations

from memoryhub.adapter.vnext_schemas import DiagnosticRequest, ForgetRequest
from memoryhub.application.diagnostic_service import DiagnosticService
from memoryhub.application.forget_service import ForgetService, ForgetState
from memoryhub.domain.contracts import LongTermEnvelope, MemoryScope, MemoryType
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database
from memoryhub.storage.models import ForgetRow, MemoryProjectionOutboxRow


def _setup(tmp_path):
    db = Database(str(tmp_path / "b14.db"))
    db.init_schema()
    authority = AuthorityRepository(db)
    authority.save(
        LongTermEnvelope(
            tenant_id="tenant-a",
            user_id="user-a",
            memory_id="mem-a",
            memory_type=MemoryType.PREFERENCE,
            normalized_key="format",
            content={"text": "DOCX", "secret": "do-not-return"},
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            confidence=0.9,
            utility=0.5,
            evidence_refs=["e1"],
        )
    )
    return db, authority


def test_forget_blocks_authority_before_projection_cleanup_and_is_idempotent(tmp_path):
    db, authority = _setup(tmp_path)
    service = ForgetService(db, authority)
    request = ForgetRequest(
        request_id="req-1",
        idempotency_key="idem-1",
        tenant_id="tenant-a",
        user_id="user-a",
        target_memory_ids=["mem-a"],
        dry_run=False,
        confirm=True,
    )
    first = service.execute(request)
    assert first.state is ForgetState.READ_BLOCKED
    assert authority.get(tenant_id="tenant-a", user_id="user-a", memory_id="mem-a") is None
    tombstone = authority.get(
        tenant_id="tenant-a", user_id="user-a", memory_id="mem-a", include_inactive=True
    )
    assert tombstone is not None and tombstone.evolution_status.value == "DELETED"
    with db.session() as session:
        outbox = session.query(MemoryProjectionOutboxRow).filter_by(memory_id="mem-a").one()
        assert outbox.operation == "delete" and outbox.priority == 100
    again = service.execute(request)
    assert again.response.forget_request_id == first.response.forget_request_id
    with db.session() as session:
        assert session.query(ForgetRow).count() == 1


def test_forget_high_risk_selector_requires_authorization(tmp_path):
    db, authority = _setup(tmp_path)
    service = ForgetService(db, authority)
    request = ForgetRequest(
        request_id="req-2",
        idempotency_key="idem-2",
        tenant_id="tenant-a",
        user_id="user-a",
        instruction="forget all format",
        dry_run=False,
        confirm=True,
    )
    try:
        service.execute(request)
    except PermissionError as exc:
        assert "authorization" in str(exc)
    else:
        raise AssertionError("high-risk forget must fail closed")


def test_diagnostics_are_tenant_scoped_and_redacted(tmp_path):
    db, authority = _setup(tmp_path)
    items = DiagnosticService(db).inspect(
        target_type="memory", target_id="mem-a", tenant_id="tenant-a", user_id="user-a"
    )
    assert items and items[0]["memory_id"] == "mem-a"
    assert "secret" not in str(items)
    assert (
        DiagnosticRequest(
            request_id="diag-1",
            tenant_id="tenant-a",
            user_id="user-a",
            target_type="memory",
            target_id="mem-a",
        ).include_sensitive
        is False
    )
