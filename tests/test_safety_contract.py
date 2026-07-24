import inspect
import re
from datetime import datetime
from typing import get_type_hints
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import (
    DEFAULT_SENSITIVE_RULES,
    MemoryEvent,
    SafetyAction,
    SafetyAuditFinding,
    SafetyAuditRecord,
    SafetyDecision,
    SafetyDecisionContext,
    SafetyExceptionScope,
    SafetyFinding,
    SafetyFindingDecision,
    SafetyLevelOverride,
    SafetyPolicy,
    SafetyPolicyException,
    SafetyReport,
    SafetyResult,
    SafetyRuleOverride,
    SensitiveLevel,
    SensitiveRule,
    canonical_sha256,
)
from memoryhub.config import SafetyConfig
from memoryhub.core import safety as safety_api
from memoryhub.core.safety import (
    SafetyDecisionError,
    SafetySanitizationError,
    SensitiveDetector,
)


def canonical_event() -> MemoryEvent:
    return MemoryEvent.model_validate(
        {
            "event_id": "evt_safety_001",
            "source_type": "tool_result",
            "event_type": "agent_response",
            "user_id": "u001",
            "session_id": "session_001",
            "turn_id": "turn_007",
            "scene": "office",
            "task_type": "weekly_report",
            "occurred_at": "2026-07-22T10:30:00Z",
            "text": "已生成周报。",
            "payload": {"response_status": "success"},
            "tool_calls": [
                {
                    "call_id": "call_001",
                    "tool_name": "file_search",
                    "arguments": {"query": "项目周报"},
                    "result": {"files": ["weekly-report.docx"]},
                    "status": "success",
                    "sequence": 1,
                }
            ],
            "schema_version": "1.1",
            "source_hash": "a" * 64,
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


def high_mask_finding() -> SafetyFinding:
    return SafetyFinding(
        finding_id="finding_001",
        rule_name="id_card",
        rule_version="1.0",
        level=SensitiveLevel.HIGH,
        suggested_action=SafetyAction.MASK,
        field_path="/payload/profile/id_card",
        start=0,
        end=18,
        replacement="[REDACTED_ID_CARD]",
        reason_code="personal.id_card",
        reason="Government identity numbers require redaction.",
        standard_source="GB/T 35273-2020",
    )


def canonical_context() -> SafetyDecisionContext:
    event = canonical_event()
    return SafetyDecisionContext(
        source_type=event.source_type,
        event_type=event.event_type,
        scene=event.scene,
        task_type=event.task_type,
    )


def safety_report() -> SafetyReport:
    return SafetyReport(
        report_id="report_001",
        event_id="evt_safety_001",
        event_digest=canonical_sha256(canonical_event().model_dump(mode="json")),
        source_hash="a" * 64,
        rule_set_version="1.0",
        rule_set_digest="c" * 64,
        context=canonical_context(),
        findings=(high_mask_finding(),),
        highest_level=SensitiveLevel.HIGH,
        scanned_field_count=8,
    )


def safety_decision(action: SafetyAction = SafetyAction.MASK) -> SafetyDecision:
    return SafetyDecision(
        report_id="report_001",
        action=action,
        policy_id="default",
        policy_version="1.0",
        policy_digest="f" * 64,
        finding_decisions=(
            SafetyFindingDecision(
                finding_id="finding_001",
                action=action,
                reason_code="personal.id_card",
            ),
        ),
        reason_codes=("personal.id_card",),
        exception_ids=("test_exception",) if action is SafetyAction.ALLOW else (),
        reason="policy selected action",
    )


def safety_audit(action: SafetyAction = SafetyAction.MASK) -> SafetyAuditRecord:
    finding = high_mask_finding()
    return SafetyAuditRecord(
        audit_id="audit_001",
        report_id="report_001",
        event_id="evt_safety_001",
        source_hash="a" * 64,
        rule_set_version="1.0",
        rule_set_digest="c" * 64,
        policy_id="default",
        policy_version="1.0",
        policy_digest="f" * 64,
        decision_action=action,
        reason_codes=("personal.id_card",),
        exception_ids=("test_exception",) if action is SafetyAction.ALLOW else (),
        findings=(
            SafetyAuditFinding(
                finding_id=finding.finding_id,
                rule_name=finding.rule_name,
                rule_version=finding.rule_version,
                level=finding.level,
                field_path=finding.field_path,
                start=finding.start,
                end=finding.end,
                reason_code=finding.reason_code,
                standard_source=finding.standard_source,
            ),
        ),
        redaction_types=("id_card",),
    )


def safety_result(action: SafetyAction = SafetyAction.MASK) -> SafetyResult:
    verification = None
    safe_event = None
    if action in (SafetyAction.ALLOW, SafetyAction.MASK):
        safe_event = canonical_event()
    if action is SafetyAction.MASK:
        event_digest = canonical_sha256(safe_event.model_dump(mode="json"))
        verification = SafetyReport(
            report_id="report_verify_001",
            event_id="evt_safety_001",
            event_digest=event_digest,
            source_hash="a" * 64,
            rule_set_version="1.0",
            rule_set_digest="c" * 64,
            context=canonical_context(),
            scanned_field_count=8,
        )
    return SafetyResult(
        report=safety_report(),
        decision=safety_decision(action),
        audit=safety_audit(action),
        sanitized_event=safe_event,
        verification_report=verification,
    )


def base_rule_data() -> dict:
    return {
        "name": "custom_secret",
        "version": "1.0",
        "pattern": r"secret=(?P<value>\S+)",
        "level": "high",
        "action": "mask",
        "reason_code": "secret.custom",
        "reason": "Custom secret requires redaction.",
        "standard_source": "Project threat model v1.0",
        "replacement": "[REDACTED_CUSTOM_SECRET]",
        "match_group": "value",
    }


def test_default_rules_are_named_versioned_and_actionable() -> None:
    config = SafetyConfig()
    rules = {rule.name: rule for rule in config.sensitive_patterns}

    assert len(rules) == len(config.sensitive_patterns)
    assert all(
        rule.version and rule.reason and rule.standard_source for rule in rules.values()
    )
    high_actions = {
        rule.action for rule in rules.values() if rule.level is SensitiveLevel.HIGH
    }
    assert {SafetyAction.MASK, SafetyAction.REJECT} <= high_actions
    credential_rule = rules["credential_field"]
    assert re.search(credential_rule.path_pattern, "/tool_calls/0/arguments/api_key")
    assert re.search(credential_rule.pattern, "sk-secret")
    assert re.search(credential_rule.pattern, credential_rule.replacement) is None
    api_key_rule = rules["api_key"]
    assert re.search(api_key_rule.pattern, "api_key=sk-secret")
    assert (
        re.search(api_key_rule.pattern, f"api_key={api_key_rule.replacement}") is None
    )
    assert config.rule_set_version == "1.0"
    assert config.rules == tuple(config.sensitive_patterns)
    assert config.sensitive_patterns is not SafetyConfig().sensitive_patterns


def test_safety_config_normalizes_mapping_rules_and_rejects_anonymous_patterns() -> (
    None
):
    rule_data = DEFAULT_SENSITIVE_RULES[0].model_dump(mode="json")
    config = SafetyConfig(
        sensitive_patterns=[rule_data],
        policy={"policy_id": "strict", "version": "2.0"},
    )

    assert isinstance(config.sensitive_patterns[0], SensitiveRule)
    assert isinstance(config.policy, SafetyPolicy)
    assert config.policy.policy_id == "strict"

    with pytest.raises(ValidationError):
        SafetyConfig(sensitive_patterns=[r"\bsecret\b"])


def test_safety_config_rejects_duplicate_rule_names() -> None:
    rule = DEFAULT_SENSITIVE_RULES[0]

    with pytest.raises(ValueError, match="unique"):
        SafetyConfig(sensitive_patterns=[rule, rule])


@pytest.mark.parametrize(
    "updates",
    [
        {"pattern": "["},
        {"pattern": r".*"},
        {"match_group": "missing"},
        {"match_group": True},
        {"match_group": 1.0},
        {"replacement": ""},
        {"level": "none"},
    ],
)
def test_sensitive_rule_validates_regex_group_and_mask_replacement(
    updates: dict,
) -> None:
    data = {**base_rule_data(), **updates}

    with pytest.raises(ValidationError):
        SensitiveRule.model_validate(data)


def test_finding_uses_json_pointer_and_unicode_half_open_span_without_raw_value() -> (
    None
):
    text = "中文 user@example.com"
    start = text.index("user@example.com")
    end = start + len("user@example.com")
    finding = SafetyFinding(
        rule_name="email",
        rule_version="1.0",
        level="medium",
        suggested_action="mask",
        field_path="/tool_calls/0/result/a~1b/~0email",
        start=start,
        end=end,
        replacement="[REDACTED_EMAIL]",
        reason_code="personal.email",
        reason="Personal email addresses require redaction.",
        standard_source="GB/T 35273-2020",
    )

    assert text[finding.start : finding.end] == "user@example.com"
    assert "matched_text" not in type(finding).model_fields

    with pytest.raises(ValidationError):
        SafetyFinding.model_validate(
            {
                **finding.model_dump(mode="python"),
                "matched_text": "user@example.com",
            }
        )

    for invalid_path in ("payload/email", "/payload/~2email"):
        with pytest.raises(ValidationError):
            SafetyFinding.model_validate(
                {
                    **finding.model_dump(mode="python"),
                    "field_path": invalid_path,
                }
            )


def test_report_validates_highest_level_and_timezone() -> None:
    report_data = safety_report().model_dump(mode="python")

    with pytest.raises(ValidationError, match="highest_level"):
        SafetyReport.model_validate(
            {
                **report_data,
                "highest_level": SensitiveLevel.MEDIUM,
            }
        )

    with pytest.raises(ValidationError, match="timezone-aware"):
        SafetyReport.model_validate(
            {
                **report_data,
                "scanned_at": datetime(2026, 7, 24, 10, 0, 0),
            }
        )

    with pytest.raises(ValidationError, match="scanned_field_count"):
        SafetyReport.model_validate({**report_data, "scanned_field_count": 0})

    with pytest.raises(ValidationError, match="issue"):
        SafetyReport.model_validate(
            {
                **report_data,
                "scan_complete": False,
                "issues": (),
            }
        )

    with pytest.raises(ValidationError, match="absence of issues"):
        SafetyReport.model_validate(
            {
                **report_data,
                "scan_complete": True,
                "issues": ("scan.limit.max_candidates",),
            }
        )


def test_result_requires_one_report_event_and_rule_snapshot() -> None:
    result = safety_result()
    serialized = result.model_dump_json()

    assert result.report.report_id == result.decision.report_id
    assert "11010519491231002X" not in serialized

    verification = SafetyReport(
        report_id="report_verify_001",
        event_id="evt_safety_001",
        event_digest="d" * 64,
        source_hash="a" * 64,
        rule_set_version="2.0",
        rule_set_digest="e" * 64,
        scanned_field_count=1,
    )
    with pytest.raises(ValidationError, match="same rule snapshot"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=safety_audit(),
            sanitized_event=canonical_event(),
            verification_report=verification,
        )


def test_policy_overrides_are_deeply_immutable_and_fail_closed() -> None:
    policy = SafetyPolicy(
        rule_overrides=(
            SafetyRuleOverride(rule_name="api_key", action=SafetyAction.REVIEW),
        ),
        level_overrides=(
            SafetyLevelOverride(level=SensitiveLevel.LOW, action=SafetyAction.MASK),
        ),
    )

    assert isinstance(policy.rule_overrides, tuple)
    assert isinstance(policy.level_overrides, tuple)
    with pytest.raises(ValidationError):
        policy.rule_overrides[0].action = SafetyAction.ALLOW
    with pytest.raises(ValidationError):
        policy.rule_overrides = ()
    with pytest.raises(ValidationError, match="scan errors"):
        SafetyPolicy(fail_closed=True, on_scan_error=SafetyAction.ALLOW)
    with pytest.raises(ValidationError, match="unique"):
        SafetyPolicy(
            rule_overrides=(
                {"rule_name": "api_key", "action": "mask"},
                {"rule_name": "api_key", "action": "review"},
            )
        )


def test_config_rejects_policy_override_for_unknown_rule() -> None:
    with pytest.raises(ValueError, match="unknown"):
        SafetyConfig(
            policy=SafetyPolicy(
                rule_overrides=(
                    SafetyRuleOverride(
                        rule_name="not_configured",
                        action=SafetyAction.REVIEW,
                    ),
                )
            )
        )


def test_decision_action_must_aggregate_effective_finding_actions() -> None:
    decision_data = safety_decision().model_dump(mode="python")

    with pytest.raises(ValidationError, match="aggregate"):
        SafetyDecision.model_validate(
            {
                **decision_data,
                "action": SafetyAction.ALLOW,
            }
        )


def test_mask_result_requires_safe_event_and_clean_same_snapshot_verification() -> None:
    with pytest.raises(ValidationError, match="verification"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=safety_audit(),
            sanitized_event=canonical_event(),
        )

    residual = SafetyReport(
        report_id="report_verify_residual",
        event_id="evt_safety_001",
        event_digest=canonical_sha256(canonical_event().model_dump(mode="json")),
        source_hash="a" * 64,
        rule_set_version="1.0",
        rule_set_digest="c" * 64,
        context=canonical_context(),
        findings=(high_mask_finding(),),
        highest_level=SensitiveLevel.HIGH,
        scanned_field_count=8,
    )
    with pytest.raises(ValidationError, match="residual"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=safety_audit(),
            sanitized_event=canonical_event(),
            verification_report=residual,
        )

    wrong_event_data = safety_result().verification_report.model_dump(mode="python")
    wrong_event_data.update(
        {
            "event_digest": "e" * 64,
            "context_digest": "",
        }
    )
    wrong_event_verification = SafetyReport.model_validate(wrong_event_data)
    with pytest.raises(ValidationError, match="sanitized event"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=safety_audit(),
            sanitized_event=canonical_event(),
            verification_report=wrong_event_verification,
        )

    empty_verification = safety_result().verification_report.model_copy(
        update={"scanned_field_count": 0}
    )
    with pytest.raises(ValidationError, match="scanned_field_count"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=safety_audit(),
            sanitized_event=canonical_event(),
            verification_report=empty_verification,
        )

    with pytest.raises(ValidationError, match="must not expose"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(SafetyAction.REVIEW),
            audit=safety_audit(SafetyAction.REVIEW),
            sanitized_event=canonical_event(),
        )


def test_allow_result_must_return_the_exact_scanned_event() -> None:
    tampered_event = canonical_event().model_copy(deep=True)
    tampered_event.text = "token=secret-after-scan"

    with pytest.raises(ValidationError, match="scanned event"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(SafetyAction.ALLOW),
            audit=safety_audit(SafetyAction.ALLOW),
            sanitized_event=tampered_event,
        )


def test_incomplete_report_cannot_be_packaged_as_allow() -> None:
    incomplete_data = safety_report().model_dump(mode="python")
    incomplete_data.update(
        {
            "scan_complete": False,
            "issues": ("scan.limit.max_candidates",),
        }
    )
    incomplete = SafetyReport.model_validate(incomplete_data)

    with pytest.raises(ValidationError, match="must REVIEW or REJECT"):
        SafetyResult(
            report=incomplete,
            decision=safety_decision(SafetyAction.ALLOW),
            audit=safety_audit(SafetyAction.ALLOW),
            sanitized_event=canonical_event(),
        )


def test_audit_must_be_exact_safe_projection_of_report() -> None:
    audit_data = safety_audit().model_dump(mode="python")
    audit_data["findings"][0]["field_path"] = "/payload/wrong"
    mismatched_audit = SafetyAuditRecord.model_validate(audit_data)

    with pytest.raises(ValidationError, match="does not match report finding"):
        SafetyResult(
            report=safety_report(),
            decision=safety_decision(),
            audit=mismatched_audit,
            sanitized_event=canonical_event(),
            verification_report=safety_result().verification_report,
        )

    with pytest.raises(ValidationError):
        SafetyAuditRecord.model_validate(
            {
                **safety_audit().model_dump(mode="python"),
                "payload": {"id_card": "11010519491231002X"},
            }
        )


def test_detector_constructor_accepts_config_and_legacy_custom_patterns() -> None:
    config = SafetyConfig(auto_mask=False, reject_on_detect=True)
    detector = SensitiveDetector.from_config(config)

    assert detector.rules == config.rules
    assert detector.rule_set_version == config.rule_set_version
    assert len(detector.rule_set_digest) == 64
    assert len(detector.policy_digest) == 64
    assert detector.policy == config.policy
    assert detector.auto_mask is False
    assert detector.reject_on_detect is True
    assert "reject_on_detect" in inspect.signature(SensitiveDetector).parameters
    assert "credential_field" not in detector.DEFAULT_PATTERNS
    assert "credential_field" not in detector.patterns

    legacy = SensitiveDetector(
        {"custom_secret": r"secret-\d+"},
        rules=[],
    )
    assert legacy.rules[0].name == "custom_secret"
    assert legacy.rules[0].action is SafetyAction.REVIEW


def test_detector_digests_are_canonical_and_version_sensitive() -> None:
    first = SensitiveDetector()
    same = SensitiveDetector()
    new_version = SensitiveDetector(rule_set_version="2.0")
    reordered = SensitiveDetector(rules=tuple(reversed(DEFAULT_SENSITIVE_RULES)))
    overridden = SensitiveDetector(
        policy=SafetyPolicy(
            rule_overrides=(
                SafetyRuleOverride(rule_name="api_key", action=SafetyAction.MASK),
            )
        )
    )

    assert first.rule_set_digest == same.rule_set_digest
    assert first.policy_digest == same.policy_digest
    assert first.rule_set_digest != new_version.rule_set_digest
    assert first.rule_set_digest != reordered.rule_set_digest
    assert first.policy_digest != overridden.policy_digest


def test_public_safety_exports_and_pipeline_signatures_are_stable() -> None:
    expected_exports = {
        "SafetyAction": SafetyAction,
        "SafetyAuditRecord": SafetyAuditRecord,
        "SafetyDecision": SafetyDecision,
        "SafetyDecisionContext": SafetyDecisionContext,
        "SafetyDecisionError": SafetyDecisionError,
        "SafetyExceptionScope": SafetyExceptionScope,
        "SafetyFinding": SafetyFinding,
        "SafetyLevelOverride": SafetyLevelOverride,
        "SafetyPolicy": SafetyPolicy,
        "SafetyPolicyException": SafetyPolicyException,
        "SafetyReport": SafetyReport,
        "SafetyResult": SafetyResult,
        "SafetyRuleOverride": SafetyRuleOverride,
        "SafetySanitizationError": SafetySanitizationError,
        "SensitiveRule": SensitiveRule,
        "canonical_sha256": canonical_sha256,
    }
    for name, expected in expected_exports.items():
        assert getattr(safety_api, name) is expected

    assert get_type_hints(SensitiveDetector.scan)["return"] is SafetyReport
    assert get_type_hints(SensitiveDetector.decide)["return"] is SafetyDecision
    assert get_type_hints(SensitiveDetector.sanitize)["return"] is MemoryEvent
    assert get_type_hints(SensitiveDetector.build_audit)["return"] is SafetyAuditRecord
    assert get_type_hints(SensitiveDetector.process)["return"] is SafetyResult
    assert get_type_hints(SensitiveDetector.validate_result)["return"] is SafetyResult


def test_legacy_wrappers_accept_one_shared_result_without_reprocessing() -> None:
    event = canonical_event()
    event.payload = {"profile": {"id_card": "11010519491231002X"}}
    detector = SensitiveDetector()
    result = detector.process(event)
    review_event = canonical_event()
    review_event.payload = {"medical_record": {"diagnosis": "synthetic"}}
    review_result = detector.process(review_event)
    detector.process = Mock(side_effect=AssertionError("must reuse shared result"))

    assert detector.detect(event, result=result) is SensitiveLevel.HIGH
    assert detector.mask(event, result=result) == result.sanitized_event
    assert detector.should_reject(event, result=result) == (
        False,
        result.decision.reason,
    )
    assert detector.should_reject(review_event, result=review_result) == (
        True,
        review_result.decision.reason,
    )
    with pytest.raises(ValidationError):
        result.sanitized_event.text = "token=tampered-after-verification"
    with pytest.raises(
        SafetySanitizationError,
        match=r"^sanitize\.blocked_by_decision$",
    ):
        detector.mask(review_event, result=review_result)
    detector.process.assert_not_called()

    detector.scan_text = Mock(return_value=(high_mask_finding(),))
    level, names = detector.detect_text("placeholder")
    assert level is SensitiveLevel.HIGH
    assert names == ["id_card"]
