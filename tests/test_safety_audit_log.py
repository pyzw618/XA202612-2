from __future__ import annotations

import json
import multiprocessing
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SensitiveLevel,
    SensitiveRule,
)
from memoryhub.core.safety.audit_log import (
    SafetyAuditLog,
    SafetyAuditLogError,
)
from memoryhub.core.safety.detector import SensitiveDetector


_KEY = b"test-only-audit-key-material-32bytes!!"


def _event(
    *,
    event_id: str = "evt_audit_001",
    text: str = "ordinary text",
    payload: dict[str, Any] | None = None,
    source_hash: str = "a" * 64,
) -> MemoryEvent:
    return MemoryEvent.model_validate(
        {
            "event_id": event_id,
            "source_type": "tool_result",
            "event_type": "tool_result",
            "user_id": "complete-user-id-must-not-be-logged",
            "session_id": "session_001",
            "turn_id": "turn_001",
            "scene": "office",
            "task_type": "weekly_report",
            "occurred_at": "2026-07-24T10:30:00Z",
            "text": text,
            "payload": {"status": "success"} if payload is None else payload,
            "tool_calls": [
                {
                    "call_id": "call_001",
                    "tool_name": "fixture",
                    "arguments": {},
                    "result": None,
                    "status": "success",
                    "sequence": 1,
                    "error": "",
                }
            ],
            "schema_version": "1.1",
            "source_hash": source_hash,
            "redactions": [],
            "quality": {
                "score": 1.0,
                "status": "accepted",
                "completeness": 1.0,
                "validity": 1.0,
                "consistency": 1.0,
                "freshness": 1.0,
                "issues": [],
            },
        }
    )


def _mask_rule() -> SensitiveRule:
    return SensitiveRule(
        name="custom.secret",
        pattern=re.escape("secret-4242"),
        level=SensitiveLevel.HIGH,
        action=SafetyAction.MASK,
        replacement="[REDACTED_CUSTOM_SECRET]",
        reason_code="test.custom_secret",
        reason="Test secret.",
        standard_source="Bearer metadata-must-not-be-persisted",
    )


def _segment_paths(directory: Path) -> list[Path]:
    return sorted(directory.glob("safety-audit-*.jsonl"))


def _append_in_process(directory: str, index: int) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event(event_id=f"evt_process_{index:03d}", text=f"ordinary {index}")
    store = SafetyAuditLog(directory, fingerprint_key=_KEY)
    store.append(event, detector.process(event), detector)


def test_append_uses_validated_minimal_projection_and_hmac_fingerprint(
    tmp_path: Path,
) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event(
        text="secret-4242",
        payload={"copy": "secret-4242"},
    )
    result = detector.process(event)
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)

    record = store.append(event, result, detector)

    assert record.decision is SafetyAction.MASK
    assert record.highest_risk is SensitiveLevel.HIGH
    assert record.category_counts[0].category == "custom"
    assert record.finding_count == 2
    assert record.redaction_count == 2
    assert record.output_hash == result.verification_report.event_digest
    assert record.processing_time_ms == result.audit.processing_time_ms
    assert record.input_fingerprint != result.report.event_digest
    assert record.previous_record_hash == "0" * 64
    raw = _segment_paths(store.directory)[0].read_text(encoding="utf-8")
    assert "secret-4242" not in raw
    assert "complete-user-id-must-not-be-logged" not in raw
    assert "metadata-must-not-be-persisted" not in raw
    assert '"payload":{' not in raw
    assert store.verify().record_count == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"directory": object(), "fingerprint_key": _KEY},
        {
            "directory": "unused",
            "fingerprint_key": _KEY,
            "fingerprint_key_id": 123,
        },
    ],
)
def test_invalid_audit_runtime_config_uses_stable_error(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(SafetyAuditLogError) as caught:
        SafetyAuditLog(**kwargs)  # type: ignore[arg-type]
    assert caught.value.code in {"audit.invalid_config", "audit.invalid_key"}
    assert str(caught.value) == caught.value.code


def test_input_fingerprint_ignores_forged_equal_source_hash(tmp_path: Path) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)
    first = _event(event_id="evt_one", text="first", source_hash="f" * 64)
    second = _event(event_id="evt_two", text="second", source_hash="f" * 64)

    first_record = store.append(first, detector.process(first), detector)
    second_record = store.append(second, detector.process(second), detector)

    assert first_record.input_fingerprint != second_record.input_fingerprint
    assert second_record.previous_record_hash == first_record.record_hash
    verified = store.verify()
    assert verified.last_sequence == 2
    assert verified.head_hash == second_record.record_hash


def test_event_reference_and_dynamic_path_segments_are_pseudonymized(
    tmp_path: Path,
) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    canary = "alice@example.com"
    event = _event(
        event_id=canary,
        text="secret-4242",
        payload={canary: "secret-4242"},
    )
    result = detector.process(event)
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)

    record = store.append(event, result, detector)

    assert record.event_id.startswith("event_")
    assert any(path.startswith("/payload/seg_") for path in record.field_paths)
    raw = _segment_paths(store.directory)[0].read_text(encoding="utf-8")
    assert canary not in raw
    assert "secret-4242" not in raw


def test_safe_shaped_user_id_in_dynamic_path_is_pseudonymized(
    tmp_path: Path,
) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    canary = "complete-user-id-must-not-be-logged"
    event = _event(
        text="secret-4242",
        payload={canary: "secret-4242"},
    )
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)

    record = store.append(event, detector.process(event), detector)

    assert any(path.startswith("/payload/seg_") for path in record.field_paths)
    raw = _segment_paths(store.directory)[0].read_text(encoding="utf-8")
    assert canary not in raw


def test_event_reference_always_pseudonymizes_and_preserves_correlation(
    tmp_path: Path,
) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)
    first = _event(event_id="complete-user-id-must-not-be-logged")
    second = _event(event_id="different-safe-shaped-identity")

    first_record = store.append(first, detector.process(first), detector)
    repeated_record = store.append(first, detector.process(first), detector)
    second_record = store.append(second, detector.process(second), detector)

    assert first_record.event_id.startswith("event_")
    assert first_record.event_id == repeated_record.event_id
    assert first_record.event_id != second_record.event_id
    raw = "".join(
        path.read_text(encoding="utf-8") for path in _segment_paths(store.directory)
    )
    assert first.event_id not in raw
    assert second.event_id not in raw


def test_append_revalidates_result_and_exposes_only_stable_error(
    tmp_path: Path,
) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event(text="secret-4242")
    trusted = detector.process(event)
    forged = trusted.model_copy(
        update={
            "audit": trusted.audit.model_copy(
                update={"audit_id": "Bearer injected-audit-secret"}
            )
        }
    )
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)

    with pytest.raises(SafetyAuditLogError) as caught:
        store.append(event, forged, detector)

    assert str(caught.value) == "audit.result_invalid"
    assert "injected-audit-secret" not in str(caught.value)
    assert not _segment_paths(store.directory)


def test_verify_rejects_tampering_and_noncanonical_json(tmp_path: Path) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event()
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)
    store.append(event, detector.process(event), detector)
    path = _segment_paths(store.directory)[0]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision"] = "reject"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SafetyAuditLogError) as caught:
        store.verify()

    assert caught.value.code in {
        "audit.record_hash_mismatch",
        "audit.record_invalid",
    }


def test_threaded_append_is_one_contiguous_chain(tmp_path: Path) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)
    failures: list[Exception] = []

    def worker(index: int) -> None:
        try:
            event = _event(event_id=f"evt_{index:03d}", text=f"ordinary {index}")
            store.append(event, detector.process(event), detector)
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    verified = store.verify()
    assert verified.record_count == 8
    assert verified.first_sequence == 1
    assert verified.last_sequence == 8


def test_multiprocess_append_is_one_contiguous_chain(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_append_in_process, args=(str(directory), index))
        for index in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    verified = SafetyAuditLog(directory, fingerprint_key=_KEY).verify()
    assert verified.record_count == 4
    assert verified.last_sequence == 4


def test_rotation_restart_and_retention_anchor_preserve_chain(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(
        directory,
        fingerprint_key=_KEY,
        rotate_max_bytes=1,
        retention_days=1,
    )
    for index in range(3):
        event = _event(event_id=f"evt_rotate_{index}")
        store.append(event, detector.process(event), detector)
    segments = _segment_paths(directory)
    assert len(segments) == 3

    old = datetime.now(timezone.utc) - timedelta(days=10)
    for path in segments[:-1]:
        os.utime(path, (old.timestamp(), old.timestamp()))
    assert store.enforce_retention() == 2
    assert store.anchor_path.exists()

    reopened = SafetyAuditLog(
        directory,
        fingerprint_key=_KEY,
        rotate_max_bytes=1,
        retention_days=1,
    )
    verified = reopened.verify()
    assert verified.anchored is True
    assert verified.record_count == 1
    assert verified.first_sequence == 3


def test_next_append_rotates_and_prunes_expired_current_segment(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(
        directory,
        fingerprint_key=_KEY,
        rotate_max_bytes=10 * 1024 * 1024,
        retention_days=1,
    )
    first = _event(event_id="evt_expired_segment_first")
    store.append(first, detector.process(first), detector)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    os.utime(
        _segment_paths(directory)[0],
        (old.timestamp(), old.timestamp()),
    )

    second = _event(event_id="evt_expired_segment_second")
    store.append(second, detector.process(second), detector)

    verified = store.verify()
    assert verified.anchored is True
    assert verified.record_count == 1
    assert verified.first_sequence == 2


def test_authenticated_head_detects_complete_tail_truncation(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(directory, fingerprint_key=_KEY)
    for index in range(2):
        event = _event(event_id=f"evt_tail_{index}")
        store.append(event, detector.process(event), detector)
    segment = _segment_paths(directory)[0]
    lines = segment.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    segment.write_bytes(lines[0])

    with pytest.raises(SafetyAuditLogError, match=r"^audit\.tail_truncated$"):
        SafetyAuditLog(directory, fingerprint_key=_KEY)


def test_authenticated_head_recovers_valid_fsynced_extension(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(directory, fingerprint_key=_KEY)
    first = _event(event_id="evt_head_first")
    store.append(first, detector.process(first), detector)

    def fail_head_update(_record):
        raise SafetyAuditLogError("audit.head_write_failed")

    store._write_head = fail_head_update
    second = _event(event_id="evt_head_second")
    with pytest.raises(SafetyAuditLogError, match=r"^audit\.head_write_failed$"):
        store.append(second, detector.process(second), detector)

    reopened = SafetyAuditLog(directory, fingerprint_key=_KEY)
    verified = reopened.verify()
    assert verified.record_count == 2
    assert verified.last_sequence == 2


def test_missing_authenticated_head_is_not_silently_recreated(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(directory, fingerprint_key=_KEY)
    event = _event()
    store.append(event, detector.process(event), detector)
    store.head_path.unlink()

    with pytest.raises(SafetyAuditLogError, match=r"^audit\.head_missing$"):
        SafetyAuditLog(directory, fingerprint_key=_KEY)


def test_retention_recovers_if_crash_occurs_after_anchor_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    directory = tmp_path / "audit"
    detector = SensitiveDetector(rules=[_mask_rule()])
    store = SafetyAuditLog(
        directory,
        fingerprint_key=_KEY,
        rotate_max_bytes=1,
        retention_days=1,
    )
    for index in range(3):
        event = _event(event_id=f"evt_retention_crash_{index}")
        store.append(event, detector.process(event), detector)
    segments = _segment_paths(directory)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    for path in segments[:-1]:
        os.utime(path, (old.timestamp(), old.timestamp()))

    def fail_unlink(_path):
        raise OSError("simulated interruption")

    monkeypatch.setattr(
        "memoryhub.core.safety.audit_log.os.unlink",
        fail_unlink,
    )
    with pytest.raises(SafetyAuditLogError, match=r"^audit\.retention_failed$"):
        store.enforce_retention()
    monkeypatch.undo()

    reopened = SafetyAuditLog(directory, fingerprint_key=_KEY)
    verified = reopened.verify()
    assert verified.anchored is True
    assert verified.record_count == 1
    assert verified.first_sequence == 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_audit_directory_and_files_are_owner_only(tmp_path: Path) -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event()
    store = SafetyAuditLog(tmp_path / "audit", fingerprint_key=_KEY)
    store.append(event, detector.process(event), detector)

    assert stat_mode(store.directory) == 0o700
    for path in [
        *_segment_paths(store.directory),
        store.directory / ".safety-audit.lock",
        store.head_path,
    ]:
        assert stat_mode(path) == 0o600


def stat_mode(path: Path) -> int:
    return os.stat(path, follow_symlinks=False).st_mode & 0o777


def test_rejects_segment_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "audit"
    store = SafetyAuditLog(directory, fingerprint_key=_KEY)
    target = tmp_path / "outside.jsonl"
    target.write_text("", encoding="utf-8")
    link = directory / "safety-audit-00000001.jsonl"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(SafetyAuditLogError, match=r"^audit\.symlink_rejected$"):
        store.verify()


def test_rejects_symlinked_directory_ancestor(tmp_path: Path) -> None:
    target = tmp_path / "real-parent"
    target.mkdir()
    link = tmp_path / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")

    with pytest.raises(SafetyAuditLogError, match=r"^audit\.symlink_rejected$"):
        SafetyAuditLog(link / "audit", fingerprint_key=_KEY)
