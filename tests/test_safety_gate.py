from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SafetyAction,
    SensitiveLevel,
    SensitiveRule,
    SourceType,
)
from memoryhub.core.safety.detector import SensitiveDetector
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.gate import (
    ApprovedWrite,
    GuardedCallbacks,
    SafeLogRecord,
    SafetyGateError,
    SafetyWriteGate,
)
from memoryhub.core.safety.quarantine import (
    QuarantineError,
    ReviewQuarantineStore,
)


def _event(
    text: str, *, event_id: str = "evt_gate", user_id: str = "user-gate"
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        source_type=SourceType.USER_BEHAVIOR,
        event_type="user_feedback",
        user_id=user_id,
        session_id="session-gate",
        occurred_at="2026-07-24T00:00:00Z",
        text=text,
        payload={"feedback": text},
        source_hash="a" * 64,
        quality=EventQuality(
            score=1.0,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )


def _rule(action: SafetyAction) -> SensitiveRule:
    return SensitiveRule(
        name=f"test.{action.value}",
        pattern=r"gate-secret-[0-9]+",
        level=SensitiveLevel.HIGH,
        action=action,
        reason_code=f"test.{action.value}",
        reason="Synthetic gate test rule.",
        standard_source="test-suite",
        replacement="[REDACTED_GATE]",
    )


class _AuditStub:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[MemoryEvent, object, SensitiveDetector]] = []

    def append(self, event, result, detector):
        self.calls.append((event, result, detector))
        if self.fail:
            raise RuntimeError("untrusted detail gate-secret-999")
        detector.validate_result(event, result)
        return SimpleNamespace(
            audit_id=result.audit.audit_id,
            record_hash="b" * 64,
            sequence=len(self.calls),
        )


class _HostileAuditReceipt:
    @property
    def audit_id(self):
        raise RuntimeError("gate-secret-999 must not escape")


class _InvalidReceiptAuditStub(_AuditStub):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind

    def append(self, event, result, detector):
        self.calls.append((event, result, detector))
        detector.validate_result(event, result)
        if self.kind == "none":
            return None
        if self.kind == "missing":
            return SimpleNamespace()
        if self.kind == "wrong_id":
            return SimpleNamespace(
                audit_id="audit_wrong",
                record_hash="b" * 64,
                sequence=1,
            )
        if self.kind == "bad_hash":
            return SimpleNamespace(
                audit_id=result.audit.audit_id,
                record_hash="",
                sequence=1,
            )
        if self.kind == "bad_sequence":
            return SimpleNamespace(
                audit_id=result.audit.audit_id,
                record_hash="b" * 64,
                sequence=True,
            )
        return _HostileAuditReceipt()


def _gate(
    tmp_path,
    action: SafetyAction,
    *,
    audit: _AuditStub | None = None,
    key: bytes = b"k" * 32,
):
    detector = SensitiveDetector(
        rules=[] if action is SafetyAction.ALLOW else [_rule(action)]
    )
    audit_stub = audit
    audit_store = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"test-only-gate-audit-key-" + (b"a" * 32),
    )
    if audit_stub is None:
        calls: list[tuple[MemoryEvent, object, SensitiveDetector]] = []
        real_append = audit_store.append

        def tracked_append(event, result, selected_detector):
            calls.append((event, result, selected_detector))
            return real_append(event, result, selected_detector)

        audit_store.calls = calls
        audit_store.append = tracked_append
    else:
        audit_store.calls = audit_stub.calls
        audit_store.append = audit_stub.append
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=key,
        retention_days=7,
    )
    return (
        SafetyWriteGate(detector, audit_store, quarantine=quarantine),
        audit_store,
        quarantine,
    )


@pytest.mark.parametrize(
    ("action", "approved_count", "quarantine_count"),
    [
        (SafetyAction.ALLOW, 5, 0),
        (SafetyAction.MASK, 5, 0),
        (SafetyAction.REVIEW, 0, 1),
        (SafetyAction.REJECT, 0, 0),
    ],
)
def test_gate_routes_four_actions_after_exactly_one_audit(
    tmp_path,
    action: SafetyAction,
    approved_count: int,
    quarantine_count: int,
) -> None:
    gate, audit, quarantine = _gate(tmp_path, action)
    seen: list[object] = []
    callbacks = GuardedCallbacks(
        sqlite=seen.append,
        embedding=seen.append,
        vector=seen.append,
        evidence=seen.append,
        log=seen.append,
    )

    outcome = gate.dispatch(_event("gate-secret-123"), callbacks)

    assert outcome.action is action
    assert len(audit.calls) == 1
    assert len(seen) == approved_count
    assert len(tuple(quarantine.directory.glob("review_*.json"))) == quarantine_count
    if action in (SafetyAction.ALLOW, SafetyAction.MASK):
        assert outcome.approved is not None
        assert all(isinstance(item, ApprovedWrite) for item in seen[:-1])
        assert isinstance(seen[-1], SafeLogRecord)
    else:
        assert outcome.approved is None
        assert seen == []


def test_mask_callbacks_receive_only_deeply_readonly_sanitized_event(tmp_path) -> None:
    gate, _, _ = _gate(tmp_path, SafetyAction.MASK)
    received: list[ApprovedWrite] = []

    outcome = gate.dispatch(
        _event("gate-secret-123"),
        GuardedCallbacks(sqlite=received.append),
    )

    assert outcome.approved is received[0]
    approved = received[0]
    assert "gate-secret-123" not in approved.safe_event.model_dump_json()
    assert "[REDACTED_GATE]" in approved.safe_event.model_dump_json()
    with pytest.raises(TypeError):
        approved.safe_event.payload["feedback"] = "changed"
    with pytest.raises(TypeError):
        approved._mac = "0" * 64


@pytest.mark.parametrize(
    "action",
    [
        SafetyAction.ALLOW,
        SafetyAction.MASK,
        SafetyAction.REVIEW,
        SafetyAction.REJECT,
    ],
)
def test_audit_failure_is_before_every_downstream_sink(
    tmp_path, action: SafetyAction
) -> None:
    audit = _AuditStub(fail=True)
    gate, _, quarantine = _gate(tmp_path, action, audit=audit)
    seen: list[object] = []
    callbacks = GuardedCallbacks(
        sqlite=seen.append,
        embedding=seen.append,
        vector=seen.append,
        evidence=seen.append,
        log=seen.append,
    )

    with pytest.raises(SafetyGateError, match=r"^gate\.audit_failed$"):
        gate.dispatch(_event("gate-secret-999"), callbacks)

    assert len(audit.calls) == 1
    assert seen == []
    assert tuple(quarantine.directory.glob("review_*.json")) == ()


@pytest.mark.parametrize("action", [SafetyAction.ALLOW, SafetyAction.REVIEW])
@pytest.mark.parametrize(
    "receipt_kind",
    [
        "none",
        "missing",
        "wrong_id",
        "bad_hash",
        "bad_sequence",
        "hostile",
    ],
)
def test_invalid_audit_receipt_fails_before_all_routing(
    tmp_path,
    action: SafetyAction,
    receipt_kind: str,
) -> None:
    audit = _InvalidReceiptAuditStub(receipt_kind)
    gate, _, quarantine = _gate(tmp_path, action, audit=audit)
    seen: list[object] = []

    with pytest.raises(
        SafetyGateError,
        match=r"^gate\.audit_record_invalid$",
    ) as raised:
        gate.dispatch(
            _event("gate-secret-123"),
            GuardedCallbacks(sqlite=seen.append, log=seen.append),
        )

    assert raised.value.code == "gate.audit_record_invalid"
    assert "gate-secret-999" not in str(raised.value)
    assert len(audit.calls) == 1
    assert seen == []
    assert tuple(quarantine.directory.glob("review_*.json")) == ()


def test_quarantine_failure_is_closed_before_callbacks(tmp_path, monkeypatch) -> None:
    gate, audit, quarantine = _gate(tmp_path, SafetyAction.REVIEW)
    seen: list[object] = []

    def fail_put(*_args, **_kwargs):
        raise QuarantineError("quarantine.write_failed")

    monkeypatch.setattr(quarantine, "put", fail_put)
    with pytest.raises(SafetyGateError, match=r"^gate\.quarantine_failed$"):
        gate.dispatch(
            _event("gate-secret-123"),
            GuardedCallbacks(sqlite=seen.append, log=seen.append),
        )

    assert len(audit.calls) == 1
    assert seen == []


def test_approved_write_is_constructor_guarded_mac_bound_and_gate_bound(
    tmp_path,
) -> None:
    gate, _, _ = _gate(tmp_path, SafetyAction.ALLOW)
    other_gate, _, _ = _gate(tmp_path / "other", SafetyAction.ALLOW)
    outcome = gate.route(_event("clean"))
    assert outcome.approved is not None
    original_record_hash = outcome.approved.audit_record_hash
    assert len(original_record_hash) == 64
    assert outcome.approved.audit_sequence == 1

    with pytest.raises(SafetyGateError, match=r"^gate\.approved_write_forged$"):
        ApprovedWrite()
    with pytest.raises(SafetyGateError, match=r"^gate\.approved_write_wrong_issuer$"):
        other_gate.verify_approved(outcome.approved)

    object.__setattr__(outcome.approved, "_audit_record_hash", "c" * 64)
    with pytest.raises(SafetyGateError, match=r"^gate\.approved_write_invalid$"):
        gate.verify_approved(outcome.approved)
    object.__setattr__(outcome.approved, "_audit_record_hash", original_record_hash)
    object.__setattr__(outcome.approved, "_audit_sequence", 2)
    with pytest.raises(SafetyGateError, match=r"^gate\.approved_write_invalid$"):
        gate.verify_approved(outcome.approved)
    object.__setattr__(outcome.approved, "_audit_sequence", 1)
    object.__setattr__(outcome.approved, "_mac", "0" * 64)
    called: list[object] = []
    with pytest.raises(SafetyGateError, match=r"^gate\.approved_write_invalid$"):
        gate.guarded_call(outcome.approved, called.append)
    assert called == []


def test_gate_integrates_with_real_append_only_audit_log(tmp_path) -> None:
    detector = SensitiveDetector(rules=[])
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"audit-fingerprint-key-" + (b"x" * 32),
    )
    gate = SafetyWriteGate(detector, audit)
    received: list[ApprovedWrite] = []

    outcome = gate.dispatch(
        _event("clean event"),
        GuardedCallbacks(sqlite=received.append),
    )

    assert outcome.approved is received[0]
    assert outcome.approved.audit_id == outcome.audit_id
    assert outcome.approved.audit_record_hash == outcome.log_record.audit_record_hash
    assert outcome.approved.audit_sequence == 1
    assert audit.verify()


def test_gate_rejects_raw_text_before_audit(tmp_path) -> None:
    gate, audit, _ = _gate(tmp_path, SafetyAction.ALLOW)
    with pytest.raises(SafetyGateError, match=r"^gate\.memory_event_required$"):
        gate.dispatch("gate-secret-123")  # type: ignore[arg-type]
    assert audit.calls == []


def test_gate_rejects_unsealed_audit_and_quarantine_adapters(tmp_path) -> None:
    detector = SensitiveDetector(rules=[])
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"test-only-gate-audit-key-" + (b"a" * 32),
    )

    with pytest.raises(SafetyGateError, match=r"^gate\.invalid_audit_log$"):
        SafetyWriteGate(detector, _AuditStub())  # type: ignore[arg-type]
    with pytest.raises(SafetyGateError, match=r"^gate\.invalid_quarantine$"):
        SafetyWriteGate(
            detector,
            audit,
            quarantine=object(),  # type: ignore[arg-type]
        )


def test_review_quarantine_encrypts_plaintext_and_binds_aad(tmp_path) -> None:
    gate, _, quarantine = _gate(tmp_path, SafetyAction.REVIEW)
    secret = "gate-secret-123-plaintext-sentinel"
    user_id = "complete-user-id-plaintext-sentinel"
    original = _event(secret, event_id="evt_plaintext", user_id=user_id)

    outcome = gate.route(original)

    assert outcome.review is not None
    files = tuple(quarantine.directory.glob("review_*.json"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    assert secret.encode() not in raw
    assert user_id.encode() not in raw
    assert original.event_id.encode() not in raw
    assert quarantine.load(outcome.review.review_id) == original
    if os.name == "posix":
        assert quarantine.directory.stat().st_mode & 0o077 == 0
        assert files[0].stat().st_mode & 0o077 == 0

    record = json.loads(raw)
    record["audit_id"] = "audit_tampered"
    files[0].write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(files[0], 0o600)
    with pytest.raises(QuarantineError, match=r"^quarantine\.integrity_error$"):
        quarantine.load(outcome.review.review_id)


def test_quarantine_revalidates_result_and_rejects_forgery(tmp_path) -> None:
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
    )
    event = _event("gate-secret-123")
    result = detector.process(event)
    forged = result.model_copy(update={"attestation": "0" * 64})

    with pytest.raises(
        QuarantineError,
        match=r"^quarantine\.validation_failed$",
    ):
        quarantine.put(
            event,
            forged,
            detector,
            audit_id=result.audit.audit_id,
        )

    assert tuple(quarantine.directory.glob("review_*.json")) == ()


def test_quarantine_requires_aes256_and_enforces_record_limit(tmp_path) -> None:
    with pytest.raises(QuarantineError, match=r"^quarantine\.invalid_key$"):
        ReviewQuarantineStore(
            tmp_path / "short-key",
            encryption_key=b"a" * 16,
        )

    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    quarantine = ReviewQuarantineStore(
        tmp_path / "limited",
        encryption_key=b"a" * 32,
        max_record_bytes=512,
    )
    event = _event("gate-secret-123-" + ("x" * 1024))
    result = detector.process(event)
    with pytest.raises(
        QuarantineError,
        match=r"^quarantine\.record_too_large$",
    ):
        quarantine.put(
            event,
            result,
            detector,
            audit_id=result.audit.audit_id,
        )

    assert tuple(quarantine.directory.glob("review_*.json")) == ()


def test_quarantine_record_limit_is_enforced_on_read(tmp_path) -> None:
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    writer = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
    )
    event = _event("gate-secret-123-" + ("x" * 1024))
    result = detector.process(event)
    receipt = writer.put(
        event,
        result,
        detector,
        audit_id=result.audit.audit_id,
    )
    reader = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
        max_record_bytes=512,
    )

    with pytest.raises(
        QuarantineError,
        match=r"^quarantine\.record_too_large$",
    ):
        reader.load(receipt.review_id)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"key_id": None}, "quarantine.invalid_key_id"),
        ({"retention_days": 10**20}, "quarantine.invalid_config"),
        ({"max_record_bytes": 0}, "quarantine.invalid_size_limit"),
        ({"now_factory": "secret-clock"}, "quarantine.invalid_clock"),
    ],
)
def test_quarantine_invalid_config_uses_only_stable_codes(
    tmp_path,
    kwargs: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(QuarantineError) as raised:
        ReviewQuarantineStore(
            tmp_path / "quarantine",
            encryption_key=b"a" * 32,
            **kwargs,  # type: ignore[arg-type]
        )
    assert raised.value.code == code
    assert str(raised.value) == code
    assert "secret-clock" not in str(raised.value)


def test_quarantine_invalid_method_inputs_use_only_stable_codes(tmp_path) -> None:
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
    )
    with pytest.raises(QuarantineError) as invalid_id:
        quarantine.load(None)  # type: ignore[arg-type]
    assert str(invalid_id.value) == "quarantine.invalid_review_id"

    with pytest.raises(QuarantineError) as invalid_clock:
        quarantine.cleanup_expired(now="secret-clock")  # type: ignore[arg-type]
    assert str(invalid_clock.value) == "quarantine.invalid_clock"
    assert "secret-clock" not in str(invalid_clock.value)


def test_quarantine_rejects_symlinked_directory_ancestor(tmp_path) -> None:
    target = tmp_path / "real-parent"
    target.mkdir()
    link = tmp_path / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")

    with pytest.raises(
        QuarantineError,
        match=r"^quarantine\.unsafe_directory$",
    ):
        ReviewQuarantineStore(
            link / "quarantine",
            encryption_key=b"a" * 32,
        )


def test_quarantine_wrong_key_and_retention_cleanup(tmp_path) -> None:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"test-only-gate-audit-key-" + (b"a" * 32),
    )
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
        key_id="key-a",
        retention_days=1,
        now_factory=lambda: now,
    )
    gate = SafetyWriteGate(detector, audit, quarantine=quarantine)
    outcome = gate.route(_event("gate-secret-123"))
    assert outcome.review is not None

    wrong_material = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"b" * 32,
        key_id="key-a",
        retention_days=1,
        now_factory=lambda: now,
    )
    with pytest.raises(QuarantineError, match=r"^quarantine\.integrity_error$"):
        wrong_material.load(outcome.review.review_id)

    wrong = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"b" * 32,
        key_id="key-b",
        retention_days=1,
        now_factory=lambda: now,
    )
    with pytest.raises(QuarantineError, match=r"^quarantine\.key_mismatch$"):
        wrong.load(outcome.review.review_id)

    assert quarantine.cleanup_expired(now=now + timedelta(hours=23)) == 0
    assert quarantine.cleanup_expired(now=now + timedelta(days=2)) == 1
    with pytest.raises(QuarantineError, match=r"^quarantine\.not_found$"):
        quarantine.load(outcome.review.review_id)


def test_expired_quarantine_record_cannot_be_loaded_before_cleanup(tmp_path) -> None:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
        retention_days=1,
        now_factory=lambda: now,
    )
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"test-only-gate-audit-key-" + (b"a" * 32),
    )
    outcome = SafetyWriteGate(detector, audit, quarantine=quarantine).route(
        _event("gate-secret-123")
    )
    assert outcome.review is not None

    quarantine._now_factory = lambda: now + timedelta(days=2)
    with pytest.raises(QuarantineError, match=r"^quarantine\.expired$"):
        quarantine.load(outcome.review.review_id)


def test_quarantine_write_failure_never_publishes_partial_record(
    tmp_path,
    monkeypatch,
) -> None:
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
    )
    event = _event("gate-secret-123")
    result = detector.process(event)

    def fail_fsync(_fd):
        raise OSError("untrusted backend detail")

    monkeypatch.setattr(
        "memoryhub.core.safety.quarantine.os.fsync",
        fail_fsync,
    )
    with pytest.raises(QuarantineError, match=r"^quarantine\.write_failed$"):
        quarantine.put(
            event,
            result,
            detector,
            audit_id=result.audit.audit_id,
        )

    assert tuple(quarantine.directory.glob("review_*.json")) == ()
    assert tuple(quarantine.directory.glob(".*.tmp")) == ()


def test_quarantine_cleanup_continues_after_corrupt_record(tmp_path) -> None:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    detector = SensitiveDetector(rules=[_rule(SafetyAction.REVIEW)])
    quarantine = ReviewQuarantineStore(
        tmp_path / "quarantine",
        encryption_key=b"a" * 32,
        retention_days=1,
        now_factory=lambda: now,
    )
    receipts = []
    for index in range(2):
        event = _event(
            "gate-secret-123",
            event_id=f"evt_cleanup_{index}",
        )
        result = detector.process(event)
        receipts.append(
            quarantine.put(
                event,
                result,
                detector,
                audit_id=result.audit.audit_id,
            )
        )

    corrupt_path = quarantine.directory / f"{receipts[0].review_id}.json"
    corrupt_path.write_bytes(b"{")
    if os.name == "posix":
        os.chmod(corrupt_path, 0o600)

    with pytest.raises(
        QuarantineError,
        match=r"^quarantine\.cleanup_incomplete$",
    ):
        quarantine.cleanup_expired(now=now + timedelta(days=2))

    assert corrupt_path.exists()
    assert not (quarantine.directory / f"{receipts[1].review_id}.json").exists()
