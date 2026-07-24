from __future__ import annotations

import math
from dataclasses import fields

import pytest

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
)
from memoryhub.config import (
    ReviewQuarantineConfig,
    SafetyAuditConfig,
    SafetyConfig,
)
from memoryhub.core.safety import SensitiveDetector
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.gate import SafetyGateError, SafetyWriteGate
from memoryhub.core.safety.quarantine import ReviewQuarantineStore


def _event() -> MemoryEvent:
    return MemoryEvent(
        event_id="evt_runtime_config",
        source_type=SourceType.USER_BEHAVIOR,
        event_type="user_action",
        user_id="u_runtime",
        occurred_at="2026-07-24T08:00:00Z",
        text="safe weekly report",
        payload={"status": "success"},
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


def test_safety_config_normalizes_audit_and_quarantine_mappings() -> None:
    config = SafetyConfig(
        audit={
            "directory": "runtime/audit",
            "retention_days": 90,
        },
        quarantine={
            "directory": "runtime/review",
            "retention_days": 14,
        },
    )

    assert isinstance(config.audit, SafetyAuditConfig)
    assert config.audit.directory == "runtime/audit"
    assert isinstance(config.quarantine, ReviewQuarantineConfig)
    assert config.quarantine.directory == "runtime/review"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("rotate_max_bytes", 0),
        ("retention_days", 0),
        ("max_record_bytes", -1),
        ("lock_timeout_seconds", 0),
    ],
)
def test_audit_config_rejects_non_positive_limits(
    field_name: str,
    value: int,
) -> None:
    with pytest.raises(ValueError):
        SafetyAuditConfig(**{field_name: value})


@pytest.mark.parametrize(
    ("config_type", "kwargs"),
    [
        (SafetyAuditConfig, {"directory": 123}),
        (SafetyAuditConfig, {"hmac_key_env": "NOT AN ENV"}),
        (SafetyAuditConfig, {"key_id": 123}),
        (SafetyAuditConfig, {"lock_timeout_seconds": math.nan}),
        (SafetyAuditConfig, {"lock_timeout_seconds": math.inf}),
        (ReviewQuarantineConfig, {"directory": 123}),
        (ReviewQuarantineConfig, {"encryption_key_env": "NOT AN ENV"}),
        (ReviewQuarantineConfig, {"key_id": 123}),
    ],
)
def test_persistence_config_rejects_invalid_runtime_types(
    config_type: type[SafetyAuditConfig] | type[ReviewQuarantineConfig],
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        config_type(**kwargs)


def test_runtime_config_stores_secret_references_not_secret_values() -> None:
    audit_fields = {item.name for item in fields(SafetyAuditConfig)}
    quarantine_fields = {item.name for item in fields(ReviewQuarantineConfig)}

    assert "hmac_key" not in audit_fields
    assert "encryption_key" not in quarantine_fields
    assert "hmac_key_env" in audit_fields
    assert "encryption_key_env" in quarantine_fields


@pytest.mark.parametrize(
    ("config_type", "field_name"),
    [
        (SafetyAuditConfig, "strict_permissions"),
        (SafetyAuditConfig, "fsync"),
        (SafetyAuditConfig, "fail_closed"),
        (ReviewQuarantineConfig, "strict_permissions"),
        (ReviewQuarantineConfig, "fsync"),
        (ReviewQuarantineConfig, "fail_closed"),
    ],
)
def test_persistence_security_controls_cannot_be_disabled(
    config_type: type[SafetyAuditConfig] | type[ReviewQuarantineConfig],
    field_name: str,
) -> None:
    with pytest.raises(ValueError):
        config_type(**{field_name: False})


def test_persistence_stores_are_constructed_from_typed_config(tmp_path) -> None:
    audit_config = SafetyAuditConfig(directory=str(tmp_path / "audit"))
    quarantine_config = ReviewQuarantineConfig(directory=str(tmp_path / "quarantine"))

    audit = SafetyAuditLog.from_config(
        audit_config,
        fingerprint_key=b"a" * 32,
    )
    quarantine = ReviewQuarantineStore.from_config(
        quarantine_config,
        encryption_key=b"q" * 32,
    )

    assert audit.directory == tmp_path / "audit"
    assert quarantine.directory == tmp_path / "quarantine"


def test_write_gate_is_constructed_from_one_safety_config(tmp_path) -> None:
    config = SafetyConfig(
        audit={"directory": str(tmp_path / "audit")},
        quarantine={"directory": str(tmp_path / "quarantine")},
    )
    detector = SensitiveDetector.from_config(config)

    gate = SafetyWriteGate.from_config(
        detector,
        config,
        audit_hmac_key=b"a" * 32,
        quarantine_key=b"q" * 32,
    )

    assert isinstance(gate, SafetyWriteGate)


def test_write_gate_rejects_audit_and_quarantine_key_reuse(tmp_path) -> None:
    config = SafetyConfig(
        audit={"directory": str(tmp_path / "audit")},
        quarantine={"directory": str(tmp_path / "quarantine")},
    )
    detector = SensitiveDetector.from_config(config)

    with pytest.raises(SafetyGateError, match="gate.key_reuse"):
        SafetyWriteGate.from_config(
            detector,
            config,
            audit_hmac_key=b"k" * 32,
            quarantine_key=b"k" * 32,
        )

    assert not (tmp_path / "audit").exists()
    assert not (tmp_path / "quarantine").exists()


def test_process_records_finite_non_negative_processing_time() -> None:
    result = SensitiveDetector().process(_event())

    assert math.isfinite(result.audit.processing_time_ms)
    assert result.audit.processing_time_ms >= 0.0
