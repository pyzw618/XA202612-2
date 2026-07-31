from __future__ import annotations

import sqlite3

import pytest

import memoryhub.core.safety.user_rules as user_rules_module
from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SafetyAction,
    SourceType,
    ToolCallResult,
    ToolCallStatus,
)
from memoryhub.config import SafetyConfig
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.gate import (
    ApprovedWrite,
    GuardedCallbacks,
    SafetyGateError,
    SafetyWriteGate,
)
from memoryhub.core.safety.user_rules import (
    InMemoryUserRuleRepository,
    UserRuleError,
    UserRuleService,
    build_user_rule_service,
)


def _quality() -> EventQuality:
    return EventQuality(
        score=1.0,
        status=QualityStatus.ACCEPTED,
        completeness=1.0,
        validity=1.0,
        consistency=1.0,
        freshness=1.0,
    )


def _event(
    user_id: str,
    text: str,
    *,
    event_id: str = "evt_user_rule",
    scene: str = "",
    payload: dict[str, object] | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        source_type=SourceType.USER_BEHAVIOR,
        event_type="user_feedback",
        user_id=user_id,
        scene=scene,
        occurred_at="2026-07-25T00:00:00Z",
        text=text,
        payload=payload or {"content": text},
        source_hash="a" * 64,
        quality=_quality(),
    )


def _service(**kwargs: object) -> UserRuleService:
    return UserRuleService(
        InMemoryUserRuleRepository(),
        master_key=b"r" * 32,
        **kwargs,
    )


def test_literal_rule_masks_recursively_but_not_identity_metadata() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="C++ version",
        kind="literal",
        effect="mask_match",
        matcher="Ｃ\u200b++20",
        case_sensitive=False,
    )
    detector = service.detector_for("user-a", SafetyConfig())
    event = _event(
        "user-a",
        "Prefer c++20 for builds",
        event_id="C++20-metadata-is-not-custom-content",
        scene="C++20-metadata-is-not-custom-content",
        payload={"nested": {"version": "C++20"}},
    )

    result = detector.process(event)

    assert result.decision.action is SafetyAction.MASK
    assert result.sanitized_event is not None
    assert result.sanitized_event.text == "Prefer [REDACTED_USER_DEFINED] for builds"
    assert result.sanitized_event.payload["nested"]["version"] == (
        "[REDACTED_USER_DEFINED]"
    )
    assert result.sanitized_event.event_id == event.event_id
    assert result.sanitized_event.scene == event.scene
    assert result.verification_report is not None
    assert result.verification_report.findings == ()
    assert event.text == "Prefer c++20 for builds"


def test_content_scope_includes_tool_arguments_results_and_errors_only() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Compiler version",
        kind="literal",
        effect="mask_match",
        matcher="C++20",
    )
    detector = service.detector_for("user-a", SafetyConfig())
    event = MemoryEvent(
        event_id="evt_tool_user_rule",
        source_type=SourceType.TOOL_RESULT,
        event_type="tool_result",
        user_id="user-a",
        occurred_at="2026-07-25T00:00:00Z",
        payload={"status": "ok"},
        tool_calls=[
            ToolCallResult(
                call_id="C++20",
                tool_name="C++20",
                arguments={"version": "C++20"},
                result={"version": "C++20"},
                error="C++20",
                status=ToolCallStatus.SUCCESS,
                sequence=1,
            )
        ],
        source_hash="a" * 64,
        quality=_quality(),
    )

    result = detector.process(event)

    assert result.decision.action is SafetyAction.MASK
    assert result.sanitized_event is not None
    call = result.sanitized_event.tool_calls[0]
    assert call.call_id == "C++20"
    assert call.tool_name == "C++20"
    assert call.arguments["version"] == "[REDACTED_USER_DEFINED]"
    assert call.result["version"] == "[REDACTED_USER_DEFINED]"
    assert call.error == "[REDACTED_USER_DEFINED]"


def test_drop_event_is_user_scoped_and_tightens_builtin_mask() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Drop private address",
        kind="literal",
        effect="drop_event",
        matcher="alice@example.com",
    )
    config = SafetyConfig()

    blocked = service.detector_for("user-a", config).process(
        _event("user-a", "alice@example.com")
    )
    other_user = service.detector_for("user-b", config).process(
        _event("user-b", "ordinary compiler note", event_id="evt_user_b")
    )

    assert blocked.decision.action is SafetyAction.REJECT
    assert blocked.sanitized_event is None
    assert {finding.rule_name for finding in blocked.report.findings} == {
        next(iter(service.compile_overlay("user-a").rules)).name
    }
    assert other_user.decision.action is SafetyAction.ALLOW


def test_user_mask_cannot_weaken_builtin_reject() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Attempted credential mask",
        kind="literal",
        effect="mask_match",
        matcher="Bearer live-secret-777",
    )

    result = service.detector_for("user-a", SafetyConfig()).process(
        _event("user-a", "Bearer live-secret-777")
    )

    assert result.decision.action is SafetyAction.REJECT
    assert {finding.rule_name for finding in result.report.findings} == {
        "credential.bearer_token"
    }


def test_advanced_regex_matches_a_cxx_version_family() -> None:
    service = _service(allow_advanced_regex=True)
    service.create_rule(
        "user-a",
        label="C++ version family",
        kind="advanced_regex",
        effect="mask_match",
        matcher=r"C\+\+[0-9]{2}",
        case_sensitive=False,
    )

    result = service.detector_for("user-a", SafetyConfig()).process(
        _event("user-a", "C++17 and c++23")
    )

    assert result.decision.action is SafetyAction.MASK
    assert result.sanitized_event is not None
    assert result.sanitized_event.text == (
        "[REDACTED_USER_DEFINED] and [REDACTED_USER_DEFINED]"
    )


def test_advanced_regex_is_disabled_by_default() -> None:
    service = _service()

    with pytest.raises(UserRuleError, match=r"^user_rule\.advanced_regex_disabled$"):
        service.create_rule(
            "user-a",
            label="Advanced pattern",
            kind="advanced_regex",
            effect="mask_match",
            matcher=r"C\+\+[0-9]{2}",
        )


@pytest.mark.parametrize(
    ("matcher", "expected_code"),
    [
        (r"(a+)+", "user_rule.unsafe_regex"),
        (r"^a()a*()a*()a*()a*Z$", "user_rule.unsafe_regex"),
        (r".*", "user_rule.invalid_matcher"),
        ("REDACTED_USER_DEFINED", "user_rule.invalid_matcher"),
    ],
)
def test_invalid_or_non_idempotent_matchers_are_rejected(
    matcher: str,
    expected_code: str,
) -> None:
    service = _service(allow_advanced_regex=True)

    with pytest.raises(UserRuleError, match=f"^{expected_code}$"):
        service.create_rule(
            "user-a",
            label="Unsafe",
            kind=(
                "literal" if matcher == "REDACTED_USER_DEFINED" else "advanced_regex"
            ),
            effect="mask_match",
            matcher=matcher,
        )


def test_literal_is_rejected_before_escaping_can_exceed_detector_limit() -> None:
    service = _service()

    with pytest.raises(UserRuleError, match=r"^user_rule\.invalid_matcher$"):
        service.create_rule(
            "user-a",
            label="Oversized compiled pattern",
            kind="literal",
            effect="mask_match",
            matcher="[" * 2_048,
            case_sensitive=False,
        )


def test_drop_rule_cannot_be_bypassed_with_a_redaction_marker() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Drop marker text",
        kind="literal",
        effect="drop_event",
        matcher="REDACTED_USER_DEFINED",
    )

    result = service.detector_for("user-a", SafetyConfig()).process(
        _event("user-a", "[REDACTED_USER_DEFINED]")
    )

    assert result.decision.action is SafetyAction.REJECT


def test_mask_rule_cannot_be_bypassed_with_a_forged_redaction_marker() -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Private name",
        kind="literal",
        effect="mask_match",
        matcher="ALICE",
    )

    result = service.detector_for("user-a", SafetyConfig()).process(
        _event("user-a", "[REDACTED_ALICE]")
    )

    assert result.decision.action is SafetyAction.MASK
    assert result.sanitized_event is not None
    assert "ALICE" not in result.sanitized_event.text


def test_quota_and_optimistic_revision_are_enforced() -> None:
    service = _service(max_rules_per_user=1)
    created = service.create_rule(
        "user-a",
        label="First",
        kind="literal",
        effect="mask_match",
        matcher="first-private-value",
    )
    with pytest.raises(UserRuleError, match=r"^user_rule\.limit_exceeded$"):
        service.create_rule(
            "user-a",
            label="Second",
            kind="literal",
            effect="drop_event",
            matcher="second-private-value",
        )
    updated = service.update_rule(
        "user-a",
        created.rule_id,
        expected_revision=1,
        label="Updated",
    )
    assert updated.revision == 2
    with pytest.raises(UserRuleError, match=r"^user_rule\.conflict$"):
        service.update_rule(
            "user-a",
            created.rule_id,
            expected_revision=1,
            enabled=False,
        )
    service.delete_rule("user-a", created.rule_id, expected_revision=2)
    with pytest.raises(UserRuleError, match=r"^user_rule\.limit_exceeded$"):
        service.create_rule(
            "user-a",
            label="Deleted rows still consume bounded quota",
            kind="literal",
            effect="mask_match",
            matcher="third-private-value",
        )


def test_revision_history_is_bounded_and_reserves_a_tombstone(
    monkeypatch,
) -> None:
    monkeypatch.setattr(user_rules_module, "_MAX_REVISIONS_PER_RULE", 3)
    service = _service()
    created = service.create_rule(
        "user-a",
        label="Bounded revisions",
        kind="literal",
        effect="mask_match",
        matcher="private-value",
    )
    updated = service.update_rule(
        "user-a",
        created.rule_id,
        expected_revision=1,
        label="Last update",
    )

    with pytest.raises(UserRuleError, match=r"^user_rule\.limit_exceeded$"):
        service.update_rule(
            "user-a",
            created.rule_id,
            expected_revision=2,
            label="Unbounded update",
        )
    deleted = service.delete_rule(
        "user-a",
        created.rule_id,
        expected_revision=updated.revision,
    )
    assert deleted.revision == 3


def test_rule_update_invalidates_cache_without_mutating_inflight_detector() -> None:
    service = _service()
    created = service.create_rule(
        "user-a",
        label="Version",
        kind="literal",
        effect="mask_match",
        matcher="C++17",
    )
    config = SafetyConfig()
    old_detector = service.detector_for("user-a", config)
    service.update_rule(
        "user-a",
        created.rule_id,
        expected_revision=1,
        matcher="C++23",
    )
    new_detector = service.detector_for("user-a", config)

    assert new_detector is not old_detector
    assert old_detector.process(_event("user-a", "C++17")).decision.action is (
        SafetyAction.MASK
    )
    assert old_detector.process(_event("user-a", "C++23")).decision.action is (
        SafetyAction.ALLOW
    )
    assert new_detector.process(_event("user-a", "C++17")).decision.action is (
        SafetyAction.ALLOW
    )
    assert new_detector.process(_event("user-a", "C++23")).decision.action is (
        SafetyAction.MASK
    )


def test_sqlite_store_encrypts_matcher_and_keeps_versioned_tombstone(
    tmp_path,
) -> None:
    database_path = tmp_path / "memoryhub.db"
    canary = "low-entropy-private-rule"
    service = build_user_rule_service(database_path, b"s" * 32)
    created = service.create_rule(
        "user-a",
        label="Private category",
        kind="literal",
        effect="mask_match",
        matcher=canary,
    )
    updated = service.update_rule(
        "user-a",
        created.rule_id,
        expected_revision=1,
        effect="drop_event",
    )
    deleted = service.delete_rule(
        "user-a",
        created.rule_id,
        expected_revision=2,
    )

    assert updated.revision == 2
    assert deleted.revision == 3
    assert [
        item.revision for item in service.list_rule_versions("user-a", created.rule_id)
    ] == [1, 2, 3]
    assert service.list_rules("user-a") == ()
    assert service.list_rules("user-a", include_deleted=True)[0].deleted is True
    service.close()
    assert canary.encode() not in database_path.read_bytes()
    assert b"user-a" not in database_path.read_bytes()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("label", "forged-label"),
        ("enabled", 0),
        ("deleted", 1),
    ],
)
def test_sqlite_metadata_or_ciphertext_tampering_fails_closed(
    tmp_path,
    column: str,
    value: object,
) -> None:
    database_path = tmp_path / "memoryhub.db"
    service = build_user_rule_service(database_path, b"t" * 32)
    created = service.create_rule(
        "user-a",
        label="Tamper target",
        kind="literal",
        effect="mask_match",
        matcher="private-tamper-value",
    )
    with sqlite3.connect(database_path) as connection:
        statement = {
            "label": "UPDATE user_sensitive_rules SET label = ? WHERE rule_id = ?",
            "enabled": "UPDATE user_sensitive_rules SET enabled = ? WHERE rule_id = ?",
            "deleted": "UPDATE user_sensitive_rules SET deleted = ? WHERE rule_id = ?",
        }[column]
        connection.execute(
            statement,
            (value, created.rule_id),
        )

    with pytest.raises(UserRuleError, match=r"^user_rule\.integrity_error$"):
        service.compile_overlay("user-a")
    service.close()


def test_audit_preserves_builtin_and_user_defined_categories(tmp_path) -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="C++ version",
        kind="literal",
        effect="mask_match",
        matcher="C++20",
    )
    detector = service.detector_for("user-a", SafetyConfig())
    event = _event("user-a", "C++20 and alice@example.com")
    result = detector.process(event)
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"a" * 32,
    )

    record = audit.append(event, result, detector)
    categories = {item.category: item.count for item in record.category_counts}

    assert categories == {"personal": 2, "user_defined": 2}


def test_gate_provider_masks_or_drops_before_ordinary_callbacks(tmp_path) -> None:
    service = _service()
    service.create_rule(
        "user-a",
        label="Mask version",
        kind="literal",
        effect="mask_match",
        matcher="C++20",
    )
    service.create_rule(
        "user-a",
        label="Drop private topic",
        kind="literal",
        effect="drop_event",
        matcher="never-store-topic",
    )
    audit = SafetyAuditLog(
        tmp_path / "audit",
        fingerprint_key=b"a" * 32,
    )
    gate = SafetyWriteGate(
        None,
        audit,
        detector_provider=service.detector_provider(SafetyConfig()),
    )
    received: list[ApprovedWrite] = []

    masked = gate.dispatch(
        _event("user-a", "C++20"),
        GuardedCallbacks(sqlite=received.append),
    )
    dropped = gate.dispatch(
        _event(
            "user-a",
            "never-store-topic",
            event_id="evt_drop_user_rule",
        ),
        GuardedCallbacks(sqlite=received.append),
    )

    assert masked.action is SafetyAction.MASK
    assert masked.approved is received[0]
    assert received[0].safe_event.text == "[REDACTED_USER_DEFINED]"
    assert dropped.action is SafetyAction.REJECT
    assert dropped.approved is None
    assert len(received) == 1


def test_user_rule_gate_rejects_three_way_key_reuse_before_creating_files(
    tmp_path,
) -> None:
    service = UserRuleService(
        InMemoryUserRuleRepository(),
        master_key=b"k" * 32,
    )
    config = SafetyConfig(
        audit={"directory": str(tmp_path / "audit")},
        quarantine={"directory": str(tmp_path / "quarantine")},
    )

    with pytest.raises(SafetyGateError, match=r"^gate\.key_reuse$"):
        SafetyWriteGate.from_user_rule_config(
            service,
            config,
            audit_hmac_key=b"k" * 32,
            quarantine_key=b"q" * 32,
        )

    assert not (tmp_path / "audit").exists()
    assert not (tmp_path / "quarantine").exists()
