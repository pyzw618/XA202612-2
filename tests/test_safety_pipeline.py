from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SafetyExceptionScope,
    SafetyLevelOverride,
    SafetyPolicy,
    SafetyPolicyException,
    SafetyReport,
    SafetyResult,
    SafetyRuleOverride,
    SensitiveLevel,
    SensitiveRule,
)
from memoryhub.core.safety import (
    SafetyDecisionError,
    SafetySanitizationError,
    SensitiveDetector,
)


def _event(
    *,
    text: str = "ordinary text",
    payload: dict[str, Any] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    scene: str = "office",
    task_type: str = "weekly_report",
    event_id: str = "evt_pipeline_001",
    redactions: list[str] | None = None,
) -> MemoryEvent:
    if payload is None:
        payload = {"status": "success"}
    if tool_calls is None:
        tool_calls = [
            {
                "call_id": "call_001",
                "tool_name": "fixture",
                "arguments": {},
                "result": None,
                "status": "success",
                "sequence": 1,
                "error": "",
            }
        ]
    return MemoryEvent.model_validate(
        {
            "event_id": event_id,
            "source_type": "tool_result",
            "event_type": "tool_result",
            "user_id": "u001",
            "session_id": "session_001",
            "turn_id": "turn_001",
            "scene": scene,
            "task_type": task_type,
            "occurred_at": "2026-07-24T10:30:00Z",
            "text": text,
            "payload": payload,
            "tool_calls": tool_calls,
            "schema_version": "1.1",
            "source_hash": "a" * 64,
            "redactions": [] if redactions is None else redactions,
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


def _rule(
    name: str,
    token: str,
    action: SafetyAction,
    *,
    level: SensitiveLevel = SensitiveLevel.MEDIUM,
    path_pattern: str = "",
    replacement: str | None = None,
) -> SensitiveRule:
    marker = (
        replacement
        if replacement is not None
        else f"[REDACTED_{name.upper().replace('.', '_')}]"
    )
    return SensitiveRule(
        name=name,
        pattern=re.escape(token),
        path_pattern=path_pattern,
        level=level,
        action=action,
        replacement=marker,
        reason_code=f"test.{name}",
        reason=f"Test policy for {name}.",
        standard_source="Test threat model",
    )


def _mask_rule() -> SensitiveRule:
    return _rule(
        "test.secret",
        "secret-4242",
        SafetyAction.MASK,
        level=SensitiveLevel.HIGH,
        replacement="[REDACTED_TEST_SECRET]",
    )


def _secret_everywhere_event() -> MemoryEvent:
    secret = "secret-4242"
    return _event(
        text=f"{secret} appears twice: {secret}",
        payload={
            "direct": secret,
            "nested": [{"copy": secret}],
        },
        tool_calls=[
            {
                "call_id": "call_001",
                "tool_name": "fixture",
                "arguments": {"secret": secret},
                "result": {"items": [secret]},
                "status": "success",
                "sequence": 1,
                "error": f"failed with {secret}",
            },
            {
                "call_id": "call_002",
                "tool_name": "fixture",
                "arguments": {"nested": {"copy": secret}},
                "result": secret,
                "status": "success",
                "sequence": 2,
                "error": "",
            },
        ],
        redactions=["existing"],
    )


def _scoped_exception(
    rule_name: str,
    *,
    scenes: tuple[str, ...] = ("diagnostics",),
    expires_at: datetime | None = None,
    rule_set_digest: str = "",
) -> SafetyPolicyException:
    return SafetyPolicyException(
        exception_id="allow_network_diagnostics",
        version="1.0",
        scope=SafetyExceptionScope(
            rule_names=(rule_name,),
            scenes=scenes,
            task_types=("network_check",),
            field_paths=("/payload/ip",),
        ),
        reason="Approved network diagnostics use.",
        owner="security-team",
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=expires_at or datetime(2099, 1, 1, tzinfo=timezone.utc),
        rule_set_digest=rule_set_digest,
    )


def test_clean_process_allows_an_independent_event_snapshot() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event()
    original = deepcopy(event.model_dump(mode="python"))

    result = detector.process(event)

    assert result.decision.action is SafetyAction.ALLOW
    assert result.report.findings == ()
    assert result.sanitized_event is not None
    assert result.sanitized_event is not event
    assert result.sanitized_event.model_dump(mode="python") == original
    assert result.verification_report is None
    assert result.audit.decision_action is SafetyAction.ALLOW
    assert event.model_dump(mode="python") == original


@pytest.mark.parametrize("action", [SafetyAction.REVIEW, SafetyAction.REJECT])
def test_blocking_process_actions_never_expose_an_event(
    action: SafetyAction,
) -> None:
    rule = _rule(f"test.{action.value}", "blocked-token", action)
    detector = SensitiveDetector(rules=[rule])

    result = detector.process(_event(text="blocked-token"))

    assert result.decision.action is action
    assert result.sanitized_event is None
    assert result.verification_report is None
    assert result.audit.decision_action is action


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        ((SafetyAction.ALLOW, SafetyAction.MASK), SafetyAction.MASK),
        ((SafetyAction.MASK, SafetyAction.REVIEW), SafetyAction.REVIEW),
        ((SafetyAction.REVIEW, SafetyAction.REJECT), SafetyAction.REJECT),
        (
            (
                SafetyAction.ALLOW,
                SafetyAction.MASK,
                SafetyAction.REVIEW,
                SafetyAction.REJECT,
            ),
            SafetyAction.REJECT,
        ),
    ],
)
def test_decide_uses_strict_action_precedence_independent_of_finding_order(
    actions: tuple[SafetyAction, ...],
    expected: SafetyAction,
) -> None:
    rules: list[SensitiveRule] = []
    exception_rule_names: list[str] = []
    for index, action in enumerate(actions):
        rule_name = f"test.priority_{index}"
        if action is SafetyAction.ALLOW:
            rules.append(
                _rule(
                    rule_name,
                    f"token-{index}",
                    SafetyAction.MASK,
                    level=SensitiveLevel.LOW,
                )
            )
            exception_rule_names.append(rule_name)
        else:
            rules.append(_rule(rule_name, f"token-{index}", action))
    exceptions = tuple(
        SafetyPolicyException(
            exception_id=f"allow_priority_{index}",
            version="1.0",
            scope=SafetyExceptionScope(
                rule_names=(rule_name,),
                scenes=("office",),
                field_paths=("/text",),
            ),
            reason="Test governed ALLOW branch.",
            owner="test-security",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )
        for index, rule_name in enumerate(exception_rule_names)
    )
    policy = SafetyPolicy(exceptions=exceptions)
    detector = SensitiveDetector(rules=rules)
    forward_report = detector.scan(
        _event(text=" ".join(f"token-{i}" for i in range(len(rules))))
    )
    backward_report = detector.scan(
        _event(text=" ".join(f"token-{i}" for i in reversed(range(len(rules)))))
    )

    forward = detector.decide(forward_report, policy)
    backward = detector.decide(backward_report, policy)

    assert forward.action is expected
    assert backward.action is expected
    assert {item.action for item in forward.finding_decisions} == set(actions)


def test_rule_override_precedes_level_override() -> None:
    rule = _rule(
        "test.override",
        "override-token",
        SafetyAction.MASK,
        level=SensitiveLevel.MEDIUM,
    )
    policy = SafetyPolicy(
        rule_overrides=(
            SafetyRuleOverride(
                rule_name=rule.name,
                action=SafetyAction.REJECT,
            ),
        ),
        level_overrides=(
            SafetyLevelOverride(
                level=SensitiveLevel.MEDIUM,
                action=SafetyAction.REVIEW,
            ),
        ),
    )
    detector = SensitiveDetector(rules=[rule], policy=policy)

    decision = detector.decide(detector.scan(_event(text="override-token")))

    assert decision.action is SafetyAction.REJECT
    assert decision.finding_decisions[0].action is SafetyAction.REJECT
    assert "policy.rule_override" in decision.reason_codes
    assert "policy.level_override" not in decision.reason_codes


def test_policy_overrides_cannot_weaken_a_reject_rule() -> None:
    rule = _rule(
        "test.non_downgradable",
        "must-reject",
        SafetyAction.REJECT,
        level=SensitiveLevel.HIGH,
    )
    policy = SafetyPolicy(
        rule_overrides=(
            SafetyRuleOverride(
                rule_name=rule.name,
                action=SafetyAction.MASK,
            ),
        ),
        level_overrides=(
            SafetyLevelOverride(
                level=SensitiveLevel.HIGH,
                action=SafetyAction.REVIEW,
            ),
        ),
    )
    detector = SensitiveDetector(rules=[rule], policy=policy)

    result = detector.process(_event(text="must-reject"))

    assert result.decision.action is SafetyAction.REJECT
    assert result.decision.finding_decisions[0].action is SafetyAction.REJECT
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.blocked_by_decision$",
    ):
        detector.mask_text("must-reject")


@pytest.mark.parametrize(
    ("detector_kwargs", "policy", "expected", "reason_code"),
    [
        (
            {"auto_mask": False},
            SafetyPolicy(),
            SafetyAction.REVIEW,
            "policy.auto_sanitize_disabled",
        ),
        (
            {},
            SafetyPolicy(auto_sanitize=False),
            SafetyAction.REVIEW,
            "policy.auto_sanitize_disabled",
        ),
        (
            {"reject_on_detect": True},
            SafetyPolicy(),
            SafetyAction.REJECT,
            "policy.reject_on_detect",
        ),
    ],
)
def test_legacy_compatibility_switches_only_tighten_mask(
    detector_kwargs: dict[str, bool],
    policy: SafetyPolicy,
    expected: SafetyAction,
    reason_code: str,
) -> None:
    detector = SensitiveDetector(
        rules=[_mask_rule()],
        policy=policy,
        **detector_kwargs,
    )

    result = detector.process(_event(text="secret-4242"))

    assert result.decision.action is expected
    assert reason_code in result.decision.reason_codes
    assert result.sanitized_event is None


def test_policy_exception_requires_governance_scope_and_timezone() -> None:
    scope = SafetyExceptionScope(
        rule_names=("test.contextual_ip",),
        scenes=("diagnostics",),
    )
    valid = {
        "exception_id": "allow_network_diagnostics",
        "version": "1.0",
        "scope": scope,
        "reason": "Approved diagnostics.",
        "owner": "security-team",
        "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc),
    }

    for required_field in (
        "exception_id",
        "version",
        "scope",
        "reason",
        "owner",
        "expires_at",
    ):
        invalid = dict(valid)
        invalid.pop(required_field)
        with pytest.raises(ValidationError):
            SafetyPolicyException.model_validate(invalid)

    with pytest.raises(ValidationError, match="timezone-aware"):
        SafetyPolicyException.model_validate(
            {
                **valid,
                "expires_at": datetime(2099, 1, 1),
            }
        )
    with pytest.raises(ValidationError, match="contextual selector"):
        SafetyExceptionScope(rule_names=("test.contextual_ip",))
    for governance_field in ("version", "reason", "owner"):
        with pytest.raises(ValidationError, match="must not be blank"):
            SafetyPolicyException.model_validate(
                {
                    **valid,
                    governance_field: "   ",
                }
            )
    with pytest.raises(ValidationError, match="must not be empty"):
        SafetyExceptionScope(
            rule_names=("test.contextual_ip",),
            scenes=("   ",),
        )
    with pytest.raises(ValidationError, match="governed scoped"):
        SafetyPolicy(
            rule_overrides=(
                SafetyRuleOverride(
                    rule_name="test.contextual_ip",
                    action=SafetyAction.ALLOW,
                ),
            )
        )


def test_scoped_exception_matches_scene_and_ignores_expired_or_wrong_scene() -> None:
    rule = _rule(
        "test.contextual_ip",
        "10.20.30.40",
        SafetyAction.MASK,
        level=SensitiveLevel.LOW,
    )
    detector = SensitiveDetector(rules=[rule])
    event = _event(
        payload={"ip": "10.20.30.40"},
        scene="diagnostics",
        task_type="network_check",
    )
    report = detector.scan(event)

    matching_policy = SafetyPolicy(
        exceptions=(
            _scoped_exception(
                rule.name,
                rule_set_digest=detector.rule_set_digest,
            ),
        )
    )
    matched = detector.decide(report, matching_policy)
    wrong_scene = detector.decide(
        report,
        SafetyPolicy(
            exceptions=(
                _scoped_exception(
                    rule.name,
                    scenes=("office",),
                    rule_set_digest=detector.rule_set_digest,
                ),
            )
        ),
    )
    expired = detector.decide(
        report,
        SafetyPolicy(
            exceptions=(
                _scoped_exception(
                    rule.name,
                    expires_at=report.scanned_at + timedelta(microseconds=1),
                    rule_set_digest=detector.rule_set_digest,
                ),
            )
        ),
    )

    assert matched.action is SafetyAction.ALLOW
    assert matched.exception_ids == ("allow_network_diagnostics",)
    assert "policy.exception.allow_network_diagnostics" in matched.reason_codes
    assert wrong_scene.action is SafetyAction.MASK
    assert wrong_scene.exception_ids == ()
    assert expired.action is SafetyAction.MASK
    assert expired.exception_ids == ()
    assert expired.decided_at >= report.scanned_at + timedelta(microseconds=1)

    audit = detector.build_audit(report, matched)
    assert audit.exception_ids == matched.exception_ids
    assert "10.20.30.40" not in audit.model_dump_json()


def test_high_risk_rule_cannot_receive_an_allow_exception() -> None:
    high_risk = _rule(
        "test.high_risk",
        "high-risk-token",
        SafetyAction.MASK,
        level=SensitiveLevel.HIGH,
    )
    policy = SafetyPolicy(
        exceptions=(
            _scoped_exception(
                high_risk.name,
                scenes=("office",),
            ),
        )
    )

    with pytest.raises(ValueError, match="low-risk contextual"):
        SensitiveDetector(rules=[high_risk], policy=policy)


def test_mask_process_redacts_every_scanned_copy_without_mutating_input() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _secret_everywhere_event()
    original = deepcopy(event.model_dump(mode="python"))

    result = detector.process(event)

    assert result.decision.action is SafetyAction.MASK
    assert len(result.report.findings) == 9
    assert result.sanitized_event is not None
    sanitized_json = result.sanitized_event.model_dump_json()
    assert "secret-4242" not in sanitized_json
    assert sanitized_json.count("[REDACTED_TEST_SECRET]") == 9
    assert result.sanitized_event.redactions == ("existing", "test.secret")
    assert event.model_dump(mode="python") == original
    assert result.sanitized_event is not event
    assert result.sanitized_event.payload is not event.payload
    assert result.sanitized_event.tool_calls[0] is not event.tool_calls[0]

    audit_json = result.audit.model_dump_json()
    assert "secret-4242" not in audit_json
    assert result.audit.redaction_types == ("test.secret",)


def test_safe_result_event_is_deeply_immutable() -> None:
    result = SensitiveDetector(rules=[_mask_rule()]).process(_secret_everywhere_event())
    safe = result.sanitized_event

    assert safe is not None
    with pytest.raises(ValidationError):
        safe.text = "Bearer injected-after-verification"
    with pytest.raises(TypeError):
        safe.payload["new"] = "Bearer injected-after-verification"
    with pytest.raises((AttributeError, TypeError)):
        safe.payload["nested"].append("Bearer injected-after-verification")
    with pytest.raises(TypeError):
        safe.payload["nested"][0]["copy"] = "Bearer injected-after-verification"
    with pytest.raises((AttributeError, TypeError)):
        safe.tool_calls.append(safe.tool_calls[0])
    with pytest.raises(ValidationError):
        safe.tool_calls[0].tool_name = "Bearer injected-after-verification"
    with pytest.raises((AttributeError, TypeError)):
        safe.tool_calls[0].arguments.update(
            {"token": "Bearer injected-after-verification"}
        )
    with pytest.raises((AttributeError, TypeError)):
        safe.tool_calls[0].result["items"].append("Bearer injected-after-verification")
    with pytest.raises((AttributeError, TypeError)):
        safe.redactions.append("Bearer injected-after-verification")
    with pytest.raises((AttributeError, TypeError)):
        safe.quality.issues.append("Bearer injected-after-verification")
    with pytest.raises(TypeError):
        dict.__setitem__(safe.payload, "new", "Bearer injected-after-verification")
    with pytest.raises(TypeError):
        list.append(safe.redactions, "Bearer injected-after-verification")


def test_persistent_string_metadata_is_scanned_and_rejects_credentials() -> None:
    detector = SensitiveDetector()
    event = _event()
    event.session_id = "Bearer session-secret-001"
    event.quality.issues.append("Bearer quality-secret-002")
    event.tool_calls[0].tool_name = "Bearer tool-secret-003"
    event.redactions.append("Bearer redaction-secret-004")

    result = detector.process(event)
    finding_paths = {finding.field_path for finding in result.report.findings}

    assert result.decision.action is SafetyAction.REJECT
    assert result.sanitized_event is None
    assert {
        "/session_id",
        "/quality/issues/0",
        "/tool_calls/0/tool_name",
        "/redactions/0",
    } <= finding_paths
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.blocked_by_decision$",
    ):
        detector.mask(event, result=result)


@pytest.mark.parametrize(
    ("event", "secret", "expected_path", "projected"),
    [
        (
            _event(event_id="Bearer report-secret-001"),
            "report-secret-001",
            "/event_id",
            "[REDACTED_EVENT_ID]",
        ),
        (
            _event(scene="Bearer scene-secret-002"),
            "scene-secret-002",
            "/scene",
            "[REDACTED_SCENE]",
        ),
    ],
)
def test_report_and_audit_never_copy_sensitive_metadata(
    event: MemoryEvent,
    secret: str,
    expected_path: str,
    projected: str,
) -> None:
    result = SensitiveDetector().process(event)
    serialized = result.model_dump_json()

    assert result.decision.action is SafetyAction.REJECT
    assert result.sanitized_event is None
    assert expected_path in {finding.field_path for finding in result.report.findings}
    assert secret not in serialized
    if expected_path == "/event_id":
        assert result.report.event_id == projected
        assert result.audit.event_id == projected
    else:
        assert result.report.context.scene == projected


def test_numeric_tool_sequence_cannot_hide_a_sensitive_number() -> None:
    event = _event()
    event.tool_calls[0].sequence = 13_800_138_000

    result = SensitiveDetector().process(event)

    assert result.decision.action is SafetyAction.REVIEW
    assert result.sanitized_event is None
    assert "/tool_calls/0/sequence" in {
        finding.field_path for finding in result.report.findings
    }
    assert "13800138000" not in result.model_dump_json()


def test_legacy_wrapper_rejects_a_model_copy_weakened_result() -> None:
    detector = SensitiveDetector()
    event = _event(text="Bearer wrapper-secret-001")
    result = detector.process(event)
    forged_finding_decisions = tuple(
        finding.model_copy(update={"action": SafetyAction.ALLOW})
        for finding in result.decision.finding_decisions
    )
    forged_decision = result.decision.model_copy(
        update={
            "action": SafetyAction.ALLOW,
            "finding_decisions": forged_finding_decisions,
            "exception_ids": ("forged_exception",),
        }
    )
    forged_audit = result.audit.model_copy(
        update={
            "decision_action": SafetyAction.ALLOW,
            "exception_ids": ("forged_exception",),
        }
    )
    forged_result = result.model_copy(
        update={
            "decision": forged_decision,
            "audit": forged_audit,
            "sanitized_event": event,
        }
    )

    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.invalid$",
    ):
        detector.mask(event, result=forged_result)


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        (
            "reject",
            "REJECT finding cannot be downgraded by an ALLOW exception",
        ),
        (
            "high",
            "governed ALLOW exception requires a low-risk finding",
        ),
        (
            "medium",
            "governed ALLOW exception requires a low-risk finding",
        ),
        (
            "report_metadata",
            "report metadata finding cannot be downgraded by an ALLOW exception",
        ),
    ],
)
def test_safety_result_rejects_direct_forged_exception_downgrade(
    case: str,
    expected_error: str,
) -> None:
    if case == "reject":
        detector = SensitiveDetector()
        event = _event(text="Bearer direct-forgery-secret-001")
    elif case in {"high", "medium"}:
        token = f"{case}-direct-forgery"
        detector = SensitiveDetector(
            rules=[
                _rule(
                    f"test.{case}_direct_forgery",
                    token,
                    SafetyAction.MASK,
                    level=(
                        SensitiveLevel.HIGH if case == "high" else SensitiveLevel.MEDIUM
                    ),
                )
            ]
        )
        event = _event(text=token)
    else:
        metadata_rule = _rule(
            "test.low_report_metadata",
            "context-token",
            SafetyAction.MASK,
            level=SensitiveLevel.LOW,
        )
        detector = SensitiveDetector(rules=[metadata_rule])
        event = _event(scene="context-token")

    real = detector.process(event)
    forged_finding_decisions = tuple(
        finding.model_copy(update={"action": SafetyAction.ALLOW})
        for finding in real.decision.finding_decisions
    )
    forged_decision = real.decision.model_copy(
        update={
            "action": SafetyAction.ALLOW,
            "finding_decisions": forged_finding_decisions,
            "exception_ids": ("forged_exception",),
        }
    )
    forged_audit = real.audit.model_copy(
        update={
            "decision_action": SafetyAction.ALLOW,
            "exception_ids": ("forged_exception",),
        }
    )

    with pytest.raises(ValidationError, match=re.escape(expected_error)):
        SafetyResult(
            report=real.report,
            decision=forged_decision,
            audit=forged_audit,
            sanitized_event=event,
        )


def test_maskable_metadata_copies_are_all_redacted_and_reverified() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event()
    event.session_id = "secret-4242"
    event.quality.issues.append("secret-4242")
    event.tool_calls[0].call_id = "secret-4242"
    event.redactions.append("secret-4242")
    original = deepcopy(event.model_dump(mode="python"))

    result = detector.process(event)

    assert result.decision.action is SafetyAction.MASK
    assert result.verification_report is not None
    assert result.verification_report.findings == ()
    assert result.sanitized_event is not None
    safe = result.sanitized_event
    assert safe.session_id == "[REDACTED_TEST_SECRET]"
    assert safe.quality.issues == ("[REDACTED_TEST_SECRET]",)
    assert safe.tool_calls[0].call_id == "[REDACTED_TEST_SECRET]"
    assert safe.redactions == ("[REDACTED_TEST_SECRET]", "test.secret")
    assert event.model_dump(mode="python") == original


def test_enabled_rules_cannot_directly_allow_a_finding() -> None:
    rule_data = _mask_rule().model_dump(mode="python")
    rule_data["action"] = SafetyAction.ALLOW

    with pytest.raises(ValidationError, match="governed policy exception"):
        SensitiveRule.model_validate(rule_data)


def test_model_copy_cannot_inject_an_allow_policy_override() -> None:
    rule = _mask_rule()
    valid = SafetyPolicy(
        rule_overrides=(
            SafetyRuleOverride(
                rule_name=rule.name,
                action=SafetyAction.MASK,
            ),
        )
    )
    injected_override = valid.rule_overrides[0].model_copy(
        update={"action": SafetyAction.ALLOW}
    )
    tampered = valid.model_copy(update={"rule_overrides": (injected_override,)})

    with pytest.raises(ValidationError, match="governed scoped"):
        SensitiveDetector(rules=[rule], policy=tampered)

    detector = SensitiveDetector(rules=[rule])
    report = detector.scan(_event(text="secret-4242"))
    with pytest.raises(
        SafetyDecisionError,
        match=r"^decide\.invalid_policy$",
    ):
        detector.decide(report, tampered)

    detector.policy = tampered
    with pytest.raises(
        SafetyDecisionError,
        match=r"^process\.invalid_policy$",
    ):
        detector.process(_event(text="secret-4242"))


def test_report_attestation_blocks_recomputed_exception_context() -> None:
    rule = _rule(
        "test.contextual_ip",
        "10.20.30.40",
        SafetyAction.MASK,
        level=SensitiveLevel.LOW,
    )
    detector = SensitiveDetector(rules=[rule])
    report = detector.scan(
        _event(
            payload={"ip": "10.20.30.40"},
            scene="office",
            task_type="network_check",
        )
    )
    tampered_data = report.model_dump(mode="python")
    tampered_data["context"] = {
        **report.context.model_dump(mode="python"),
        "scene": "diagnostics",
    }
    tampered_data["context_digest"] = ""
    tampered = SafetyReport.model_validate(tampered_data)
    policy = SafetyPolicy(
        exceptions=(
            _scoped_exception(
                rule.name,
                rule_set_digest=detector.rule_set_digest,
            ),
        )
    )

    with pytest.raises(
        SafetyDecisionError,
        match=r"^decide\.report_attestation_mismatch$",
    ):
        detector.decide(tampered, policy)


def test_validate_result_rejects_a_forged_low_risk_allow_exception() -> None:
    rule = _rule(
        "test.low_risk_identifier",
        "context-id-4242",
        SafetyAction.MASK,
        level=SensitiveLevel.LOW,
    )
    detector = SensitiveDetector(rules=[rule])
    event = _event(text="context-id-4242")
    trusted = detector.process(event)
    forged_finding = trusted.decision.finding_decisions[0].model_copy(
        update={"action": SafetyAction.ALLOW}
    )
    forged_decision = trusted.decision.model_copy(
        update={
            "action": SafetyAction.ALLOW,
            "finding_decisions": (forged_finding,),
            "exception_ids": ("forged_exception",),
        }
    )
    forged_audit = trusted.audit.model_copy(
        update={
            "decision_action": SafetyAction.ALLOW,
            "exception_ids": ("forged_exception",),
        }
    )
    forged = trusted.model_copy(
        update={
            "decision": forged_decision,
            "audit": forged_audit,
            "sanitized_event": event,
            "verification_report": None,
        }
    )

    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.decision_snapshot_mismatch$",
    ):
        detector.validate_result(event, forged)


def test_validate_result_rejects_a_forged_verification_report() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event(text="secret-4242")
    trusted = detector.process(event)
    assert trusted.verification_report is not None
    forged_verification = trusted.verification_report.model_copy(
        update={
            "attestation": "0" * 64,
            "event_digest": trusted.report.event_digest,
            "context": trusted.report.context,
            "context_digest": trusted.report.context_digest,
        }
    )
    forged = trusted.model_copy(
        update={
            "sanitized_event": event,
            "verification_report": forged_verification,
        }
    )

    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.invalid_verification_attestation$",
    ):
        detector.validate_result(event, forged)


def test_validate_result_rejects_an_attested_clean_report_replay() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event(text="secret-4242")
    trusted = detector.process(event)
    replayed_event = _event(text="attacker-controlled clean memory")
    replayed_verification = detector.scan(replayed_event)
    assert replayed_verification.findings == ()
    forged = trusted.model_copy(
        update={
            "sanitized_event": replayed_event,
            "verification_report": replayed_verification,
        }
    )

    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.sanitized_event_derivation_mismatch$",
    ):
        detector.validate_result(event, forged)


def test_validate_result_rejects_injected_decision_and_audit_text() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    event = _event()
    trusted = detector.process(event)
    leaked_reason = "Bearer injected-decision-secret"
    leaked_audit = "Bearer injected-audit-secret"
    forged_reason_codes = (*trusted.decision.reason_codes, leaked_reason)
    forged_decision = trusted.decision.model_copy(
        update={
            "reason": leaked_reason,
            "reason_codes": forged_reason_codes,
        }
    )
    forged_audit = trusted.audit.model_copy(
        update={
            "audit_id": leaked_audit,
            "reason_codes": forged_reason_codes,
            "redaction_types": (leaked_audit,),
        }
    )
    forged = trusted.model_copy(
        update={
            "decision": forged_decision,
            "audit": forged_audit,
        }
    )

    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.attestation_mismatch$",
    ) as caught:
        detector.validate_result(event, forged)

    assert leaked_reason not in str(caught.value)
    assert leaked_audit not in str(caught.value)


def test_validate_result_accepts_same_instance_json_roundtrip_only() -> None:
    rule = _mask_rule()
    detector = SensitiveDetector(rules=[rule])
    event = _event(text="secret-4242")
    trusted = detector.process(event)
    round_tripped = SafetyResult.model_validate_json(trusted.model_dump_json())

    validated = detector.validate_result(event, round_tripped)

    assert validated.decision.action is SafetyAction.MASK
    assert validated.sanitized_event is not None
    assert validated.sanitized_event.text == "[REDACTED_TEST_SECRET]"

    equivalent_but_new_instance = SensitiveDetector(rules=[rule])
    with pytest.raises(
        SafetySanitizationError,
        match=r"^result\.invalid$",
    ):
        equivalent_but_new_instance.validate_result(event, round_tripped)


def test_sanitize_rejects_digest_mismatch_without_modifying_either_event() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    scanned = _event(text="secret-4242")
    report = detector.scan(scanned)
    changed = scanned.model_copy(deep=True)
    changed.payload["after_scan"] = "secret-4242"
    scanned_before = deepcopy(scanned.model_dump(mode="python"))
    changed_before = deepcopy(changed.model_dump(mode="python"))

    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.event_digest_mismatch$",
    ) as caught:
        detector.sanitize(changed, report)

    assert "secret-4242" not in repr(caught.value)
    assert scanned.model_dump(mode="python") == scanned_before
    assert changed.model_dump(mode="python") == changed_before


def test_rfc6901_paths_whole_value_and_ancestor_pruning_are_sanitized() -> None:
    pointer_rule = _rule(
        "test.pointer",
        "secret-1",
        SafetyAction.MASK,
        replacement="[REDACTED_POINTER]",
    )
    second_pointer_rule = _rule(
        "test.pointer_two",
        "secret-2",
        SafetyAction.MASK,
        replacement="[REDACTED_POINTER_TWO]",
    )
    container_rule = SensitiveRule(
        name="test.container",
        pattern=r"(?s)\A(?!\[REDACTED_CONTAINER\]\Z).+\Z",
        path_pattern=r"\A/payload/a~1b/~0container\Z",
        level=SensitiveLevel.MEDIUM,
        action=SafetyAction.MASK,
        replacement="[REDACTED_CONTAINER]",
        reason_code="test.container",
        reason="Replace the whole sensitive container.",
        standard_source="Test threat model",
    )
    child_rule = _rule(
        "test.container_child",
        "nested-secret",
        SafetyAction.MASK,
        path_pattern=r"\A/payload/a~1b/~0container/child\Z",
        replacement="[REDACTED_CHILD]",
    )
    detector = SensitiveDetector(
        rules=[
            pointer_rule,
            second_pointer_rule,
            container_rule,
            child_rule,
        ]
    )
    event = _event(
        payload={
            "a/b": {
                "~key": ["secret-1"],
                "~container": {"child": "nested-secret"},
            },
            "": "secret-2",
        }
    )
    original = deepcopy(event.model_dump(mode="python"))

    result = detector.process(event)

    findings = {
        (finding.rule_name, finding.field_path, finding.target.value)
        for finding in result.report.findings
    }
    assert ("test.pointer", "/payload/a~1b/~0key/0", "text_span") in findings
    assert ("test.pointer_two", "/payload/", "text_span") in findings
    assert ("test.container", "/payload/a~1b/~0container", "whole_value") in findings
    assert (
        "test.container_child",
        "/payload/a~1b/~0container/child",
        "text_span",
    ) in findings

    assert result.decision.action is SafetyAction.MASK
    assert result.sanitized_event is not None
    assert result.sanitized_event.payload["a/b"]["~key"] == ("[REDACTED_POINTER]",)
    assert result.sanitized_event.payload[""] == "[REDACTED_POINTER_TWO]"
    assert result.sanitized_event.payload["a/b"]["~container"] == "[REDACTED_CONTAINER]"
    assert result.verification_report is not None
    assert result.verification_report.findings == ()
    assert event.model_dump(mode="python") == original


def test_process_verifies_with_one_snapshot_and_second_process_is_idempotent() -> None:
    detector = SensitiveDetector(rules=[_mask_rule()])
    first = detector.process(_secret_everywhere_event())

    assert first.decision.action is SafetyAction.MASK
    assert first.sanitized_event is not None
    assert first.verification_report is not None
    assert first.verification_report.scan_complete is True
    assert first.verification_report.findings == ()
    assert (
        first.verification_report.rule_set_digest
        == first.report.rule_set_digest
        == detector.rule_set_digest
    )
    assert first.verification_report.rule_set_version == first.report.rule_set_version

    second = detector.process(first.sanitized_event)

    assert second.decision.action is SafetyAction.ALLOW
    assert second.report.findings == ()
    assert second.verification_report is None
    assert second.sanitized_event is not None
    assert second.sanitized_event.model_dump(
        mode="json"
    ) == first.sanitized_event.model_dump(mode="json")
    assert second.sanitized_event.redactions == ("existing", "test.secret")


def test_incomplete_scan_and_unmaskable_override_fail_closed_to_review() -> None:
    limited = SensitiveDetector(
        rules=[_rule("test.repeated", "x", SafetyAction.MASK)],
        max_candidates=1,
    )

    incomplete = limited.process(_event(text="xx"))

    assert incomplete.report.scan_complete is False
    assert incomplete.report.issues == ("scan.limit.max_candidates",)
    assert incomplete.decision.action is SafetyAction.REVIEW
    assert incomplete.sanitized_event is None

    policy = SafetyPolicy(
        rule_overrides=(
            SafetyRuleOverride(
                rule_name="sensitive_personal.health_field",
                action=SafetyAction.MASK,
            ),
        )
    )
    health = SensitiveDetector(policy=policy).process(
        _event(payload={"health_record": {"diagnosis": "synthetic"}})
    )

    assert health.report.findings[0].maskable is False
    assert health.decision.action is SafetyAction.REVIEW
    assert "policy.rule_override" in health.decision.reason_codes
    assert health.sanitized_event is None


def test_residual_replacement_and_invalid_root_shape_are_quarantined() -> None:
    residual_rule = _rule(
        "test.residual",
        "residual-secret",
        SafetyAction.MASK,
        replacement="residual-secret",
    )
    residual = SensitiveDetector(rules=[residual_rule]).process(
        _event(text="residual-secret")
    )

    assert residual.decision.action is SafetyAction.REVIEW
    assert "policy.verification_failed" in residual.decision.reason_codes
    assert residual.sanitized_event is None
    assert residual.verification_report is None

    root_rule = SensitiveRule(
        name="test.payload_root",
        pattern=r"\{\}",
        path_pattern=r"\A/payload\Z",
        level=SensitiveLevel.MEDIUM,
        action=SafetyAction.MASK,
        replacement="[REDACTED_PAYLOAD]",
        reason_code="test.payload_root",
        reason="Replacing the payload root would violate the event schema.",
        standard_source="Test threat model",
    )
    invalid_shape = SensitiveDetector(rules=[root_rule]).process(
        _event(payload={"safe": "value"})
    )

    assert invalid_shape.report.findings[0].field_path == "/payload"
    assert invalid_shape.decision.action is SafetyAction.REVIEW
    assert "policy.sanitization_failed" in invalid_shape.decision.reason_codes
    assert invalid_shape.sanitized_event is None


def test_matching_scoped_exception_is_applied_by_atomic_process() -> None:
    rule = _rule(
        "test.contextual_ip",
        "10.20.30.40",
        SafetyAction.MASK,
        level=SensitiveLevel.LOW,
    )
    baseline = SensitiveDetector(rules=[rule])
    exception = _scoped_exception(
        rule.name,
        rule_set_digest=baseline.rule_set_digest,
    )
    detector = SensitiveDetector(
        rules=[rule],
        policy=SafetyPolicy(exceptions=(exception,)),
    )
    event = _event(
        payload={"ip": "10.20.30.40"},
        scene="diagnostics",
        task_type="network_check",
    )

    result = detector.process(event)

    assert result.decision.action is SafetyAction.ALLOW
    assert result.decision.exception_ids == (exception.exception_id,)
    assert result.sanitized_event is not None
    assert result.sanitized_event.payload["ip"] == "10.20.30.40"
    assert result.audit.exception_ids == result.decision.exception_ids


def test_legacy_mask_text_uses_full_type_markers_and_verifies_clean() -> None:
    detector = SensitiveDetector()

    sanitized = detector.mask_text(
        "电话 13800138000，邮箱 user@example.com，再次 13800138000"
    )

    assert sanitized == (
        "电话 [REDACTED_PHONE]，邮箱 [REDACTED_EMAIL]，再次 " "[REDACTED_PHONE]"
    )
    assert detector.scan_text(sanitized) == ()


def test_legacy_mask_text_cannot_downgrade_reject_or_policy_block() -> None:
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.blocked_by_decision$",
    ):
        SensitiveDetector().mask_text("Bearer live-secret-777")

    rule = _mask_rule()
    detector = SensitiveDetector(
        rules=[rule],
        policy=SafetyPolicy(
            rule_overrides=(
                SafetyRuleOverride(
                    rule_name=rule.name,
                    action=SafetyAction.REJECT,
                ),
            )
        ),
    )
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.blocked_by_decision$",
    ):
        detector.mask_text("secret-4242")


def test_verification_scan_error_promotes_mask_to_review() -> None:
    oversized_marker = "[REDACTED_" + ("X" * 80) + "]"
    rule = _rule(
        "test.oversized_marker",
        "short-secret",
        SafetyAction.MASK,
        replacement=oversized_marker,
    )
    detector = SensitiveDetector(rules=[rule], max_field_chars=64)

    result = detector.process(_event(text="short-secret"))

    assert result.report.scan_complete is True
    assert result.decision.action is SafetyAction.REVIEW
    assert "policy.verification_failed" in result.decision.reason_codes
    assert result.sanitized_event is None
    assert result.verification_report is None


def test_custom_decision_policy_gets_its_own_digest() -> None:
    rule = _rule(
        "test.contextual_ip",
        "10.20.30.40",
        SafetyAction.MASK,
        level=SensitiveLevel.LOW,
    )
    detector = SensitiveDetector(rules=[rule])
    report = detector.scan(
        _event(
            payload={"ip": "10.20.30.40"},
            scene="diagnostics",
            task_type="network_check",
        )
    )
    custom_policy = SafetyPolicy(
        policy_id="diagnostics",
        version="2.0",
        exceptions=(
            _scoped_exception(
                rule.name,
                rule_set_digest=detector.rule_set_digest,
            ),
        ),
    )

    first = detector.decide(report, custom_policy)
    second = detector.decide(report, custom_policy)
    same_identity_without_exception = detector.decide(
        report,
        SafetyPolicy(policy_id="diagnostics", version="2.0"),
    )

    assert first.policy_digest == second.policy_digest
    assert first.policy_digest != detector.policy_digest
    assert first.policy_digest != same_identity_without_exception.policy_digest
    assert first.policy_id == "diagnostics"
    assert first.policy_version == "2.0"


def test_legacy_mask_text_fails_closed_for_unmaskable_and_residual_rules() -> None:
    unmaskable = _rule(
        "test.unmaskable_text",
        "unmaskable-secret",
        SafetyAction.REVIEW,
        replacement="",
    )
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.unmaskable_finding$",
    ):
        SensitiveDetector(rules=[unmaskable]).mask_text("unmaskable-secret")

    residual = _rule(
        "test.residual_text",
        "residual-secret",
        SafetyAction.MASK,
        replacement="residual-secret",
    )
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.verification_failed$",
    ):
        SensitiveDetector(rules=[residual]).mask_text("residual-secret")
