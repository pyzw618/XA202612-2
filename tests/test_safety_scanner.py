from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from copy import deepcopy
from pathlib import Path

import pytest

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SafetyFinding,
    SafetyFindingTarget,
    SensitiveLevel,
    SensitiveRule,
    canonical_sha256,
)
from memoryhub.config import SafetyConfig
from memoryhub.core import safety as safety_api
from memoryhub.core.safety import (
    RuleLibraryError,
    SafetyScanError,
    SensitiveDetector,
    load_builtin_rule_set,
    load_rule_set_file,
)


def _event(
    *,
    text: str = "普通文本",
    payload: dict | None = None,
    arguments: dict | None = None,
    result: object = None,
    error: str = "",
) -> MemoryEvent:
    return MemoryEvent.model_validate(
        {
            "event_id": "evt_scan_001",
            "source_type": "tool_result",
            "event_type": "tool_result",
            "user_id": "u001",
            "session_id": "session_001",
            "turn_id": "turn_001",
            "scene": "office",
            "task_type": "weekly_report",
            "occurred_at": "2026-07-24T10:30:00Z",
            "text": text,
            "payload": payload or {"status": "success"},
            "tool_calls": [
                {
                    "call_id": "call_001",
                    "tool_name": "fixture",
                    "arguments": arguments or {},
                    "result": result,
                    "status": "success",
                    "sequence": 1,
                    "error": error,
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


def _finding_projection(report: object) -> list[tuple[object, ...]]:
    return [
        (
            finding.finding_id,
            finding.rule_name,
            finding.field_path,
            finding.target,
            finding.start,
            finding.end,
        )
        for finding in report.findings
    ]


def test_scan_recurses_required_scopes_and_builds_exact_paths() -> None:
    event = _event(
        text="电话 13800138000",
        payload={"a/b": {"~email": "alice@example.com"}},
        arguments={"": {"card": "4111111111111111"}},
        result={"*": ["192.168.1.1"]},
        error="身份证 11010519491231002X",
    )
    original = deepcopy(event.model_dump(mode="python"))

    detector = SensitiveDetector()
    report = detector.scan(event)

    by_rule = {finding.rule_name: finding for finding in report.findings}
    assert by_rule["phone"].field_path == "/text"
    assert by_rule["email"].field_path == "/payload/a~1b/~0email"
    assert (
        by_rule["sensitive_personal.bank_card"].field_path
        == "/tool_calls/0/arguments//card"
    )
    assert by_rule["ip_address"].field_path == "/tool_calls/0/result/*/0"
    assert by_rule["id_card"].field_path == "/tool_calls/0/error"
    assert report.event_digest == canonical_sha256(event.model_dump(mode="json"))
    assert report.event_id == event.event_id
    assert report.source_hash == event.source_hash
    assert report.rule_set_version == detector.rule_set_version
    assert report.rule_set_digest == detector.rule_set_digest
    assert report.scan_complete is True
    assert event.model_dump(mode="python") == original


def test_unicode_normalization_detects_bypasses_and_maps_original_spans() -> None:
    phone = "１３８\u180b００１３\u200c８０００"
    identity = "１１０１０５１９４９１２３１００２Ｘ"
    event = _event(
        text=f"{phone} / {identity}",
        payload={"ｐａｓｓ\u200bｗｏｒｄ": "value"},
    )

    report = SensitiveDetector().scan(event)
    by_rule = {finding.rule_name: finding for finding in report.findings}

    phone_finding = by_rule["phone"]
    assert event.text[phone_finding.start : phone_finding.end] == phone
    identity_finding = by_rule["id_card"]
    assert event.text[identity_finding.start : identity_finding.end] == identity
    credential = by_rule["credential_field"]
    assert credential.field_path == "/payload/ｐａｓｓ\u200bｗｏｒｄ"
    assert credential.start == 0
    assert credential.end == len("value")


def test_sensitive_content_in_a_member_name_fails_closed_without_leaking_it() -> None:
    sensitive_key = "alice@example.com"

    report = SensitiveDetector().scan(
        _event(payload={sensitive_key: {"phone": "13800138000"}})
    )

    assert report.scan_complete is False
    assert report.issues == ("scan.sensitive_member_name",)
    assert report.findings == ()
    assert sensitive_key not in repr(report)


@pytest.mark.parametrize(
    ("value", "target"),
    [
        (123, SafetyFindingTarget.WHOLE_VALUE),
        (False, SafetyFindingTarget.WHOLE_VALUE),
        (None, SafetyFindingTarget.WHOLE_VALUE),
        ({"nested": "value"}, SafetyFindingTarget.WHOLE_VALUE),
        (["nested"], SafetyFindingTarget.WHOLE_VALUE),
    ],
)
def test_sensitive_non_string_field_is_a_whole_value_finding(
    value: object,
    target: SafetyFindingTarget,
) -> None:
    event = _event(payload={"token": value})

    finding = next(
        item
        for item in SensitiveDetector().scan(event).findings
        if item.rule_name == "credential_field"
    )

    assert finding.field_path == "/payload/token"
    assert finding.target is target
    assert (finding.start, finding.end) == (0, 0)


def test_whole_value_and_descendant_risk_are_both_preserved() -> None:
    report = SensitiveDetector().scan(
        _event(payload={"token": {"email": "alice@example.com"}})
    )

    assert [
        (finding.rule_name, finding.field_path, finding.target)
        for finding in report.findings
    ] == [
        (
            "credential_field",
            "/payload/token",
            SafetyFindingTarget.WHOLE_VALUE,
        ),
        (
            "email",
            "/payload/token/email",
            SafetyFindingTarget.TEXT_SPAN,
        ),
    ]


def test_ancestor_review_does_not_hide_higher_priority_descendant() -> None:
    report = SensitiveDetector().scan(
        _event(
            payload={
                "medical_record": {
                    "payment_card": "4111111111111111",
                }
            }
        )
    )

    assert [
        (
            finding.rule_name,
            finding.field_path,
            finding.target,
            finding.suggested_action,
        )
        for finding in report.findings
    ] == [
        (
            "sensitive_personal.health_field",
            "/payload/medical_record",
            SafetyFindingTarget.WHOLE_VALUE,
            SafetyAction.REVIEW,
        ),
        (
            "sensitive_personal.bank_card",
            "/payload/medical_record/payment_card",
            SafetyFindingTarget.TEXT_SPAN,
            SafetyAction.MASK,
        ),
    ]


def test_mask_whole_value_rule_cannot_hide_reject_descendant() -> None:
    ancestor = SensitiveRule(
        name="test.mask_ancestor",
        pattern=r"(?s).+",
        path_pattern=r"/payload/container$",
        level=SensitiveLevel.LOW,
        action=SafetyAction.MASK,
        reason_code="test.mask_ancestor",
        reason="test ancestor",
        standard_source="test",
    )
    descendant = SensitiveRule(
        name="test.reject_descendant",
        pattern=r"secret",
        path_pattern=r"/payload/container/child$",
        level=SensitiveLevel.HIGH,
        action=SafetyAction.REJECT,
        reason_code="test.reject_descendant",
        reason="test descendant",
        standard_source="test",
    )

    report = SensitiveDetector(rules=[ancestor, descendant]).scan(
        _event(payload={"container": {"child": "secret"}})
    )

    assert {
        (finding.rule_name, finding.suggested_action) for finding in report.findings
    } == {
        ("test.mask_ancestor", SafetyAction.MASK),
        ("test.reject_descendant", SafetyAction.REJECT),
    }


def test_snapshot_validators_filter_invalid_identity_card_luhn_and_ip() -> None:
    event = _event(
        payload={
            "valid_id": "11010519491231002X",
            "invalid_id": "110105194912310021",
            "valid_card": "4111111111111111",
            "invalid_card": "4111111111111112",
            "valid_ip": "192.168.1.1",
            "invalid_ip": "999.999.999.999",
        }
    )

    report = SensitiveDetector().scan(event)
    paths = {(finding.rule_name, finding.field_path) for finding in report.findings}

    assert ("id_card", "/payload/valid_id") in paths
    assert ("id_card", "/payload/invalid_id") not in paths
    assert ("sensitive_personal.bank_card", "/payload/valid_card") in paths
    assert ("sensitive_personal.bank_card", "/payload/invalid_card") not in paths
    assert ("ip_address", "/payload/valid_ip") in paths
    assert ("ip_address", "/payload/invalid_ip") not in paths


def test_overlap_resolution_prefers_snapshot_priority() -> None:
    detector = SensitiveDetector()

    findings = detector.scan_text("api_key=4111111111111111")

    assert [finding.rule_name for finding in findings] == ["api_key"]
    assert findings[0].start == len("api_key=")
    assert findings[0].end == len("api_key=4111111111111111")


def test_overlap_resolution_uses_priority_then_longest(
    tmp_path: Path,
) -> None:
    builtin = load_builtin_rule_set()
    rules = []
    patterns = (
        ("abc", 100),
        ("abcde", 100),
        ("abcdef", 90),
    )
    for original, (pattern, priority) in zip(
        builtin.rules[:3],
        patterns,
        strict=True,
    ):
        rule = original.model_dump(mode="json")
        rule.update(
            {
                "pattern": pattern,
                "validator": "builtin.regex@1.0",
                "masker": "builtin.none@1.0",
                "target_paths": ["/**"],
                "priority": priority,
                "default_action": "review",
                "match_group": 0,
            }
        )
        rules.append(rule)
    document = {
        "schema_version": builtin.schema_version,
        "rule_set_id": "test.overlap",
        "version": "1.0",
        "released_on": None,
        "status_as_of": None,
        "sources": [source.model_dump(mode="json") for source in builtin.sources],
        "governance_ref": [],
        "rules": rules,
    }
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    snapshot = load_rule_set_file(path)
    expected_rule = builtin.rules[1].rule_id

    findings = SensitiveDetector(rule_snapshot=snapshot).scan_text("abcdef")

    assert [finding.rule_name for finding in findings] == [expected_rule]
    assert (findings[0].start, findings[0].end) == (0, 5)


def test_mapping_insertion_order_does_not_change_finding_projection() -> None:
    first = _event(
        payload={
            "z": "alice@example.com",
            "a": {"phone": "13800138000"},
        }
    )
    second = _event(
        payload={
            "a": {"phone": "13800138000"},
            "z": "alice@example.com",
        }
    )
    detector = SensitiveDetector()

    first_report = detector.scan(first)
    second_report = detector.scan(second)

    assert first_report.event_digest == second_report.event_digest
    assert _finding_projection(first_report) == _finding_projection(second_report)
    assert first_report.scanned_field_count == second_report.scanned_field_count


def test_structural_budget_error_is_independent_of_mapping_insertion_order() -> None:
    long_key = "0" * 20
    first_inner = {
        long_key: "x",
        "a": "x",
        "b": "x",
        "c": "x",
        "d": "x",
    }
    second_inner = {
        "a": "x",
        "b": "x",
        "c": "x",
        "d": "x",
        long_key: "x",
    }
    detector = SensitiveDetector(max_scanned_fields=8, max_scan_bytes=16)

    error_codes = []
    for inner in (first_inner, second_inner):
        with pytest.raises(SafetyScanError) as caught:
            detector.scan(
                _event(
                    text="",
                    payload={"a": inner, "b": "x", "c": "x"},
                )
            )
        error_codes.append(caught.value.code)

    assert error_codes == [
        "scan.limit.max_total_bytes",
        "scan.limit.max_total_bytes",
    ]


def test_oversized_mapping_is_rejected_before_items_are_enumerated() -> None:
    class OversizedMapping(Mapping[str, object]):
        items_called = False

        def __getitem__(self, key: str) -> object:
            raise KeyError(key)

        def __iter__(self) -> Iterator[str]:
            return iter(())

        def __len__(self) -> int:
            return 1_000

        def items(self) -> object:
            self.items_called = True
            raise AssertionError(
                "items must not be enumerated after len exceeds budget"
            )

    oversized = OversizedMapping()
    event = _event()
    event.tool_calls[0].result = oversized

    with pytest.raises(SafetyScanError) as caught:
        SensitiveDetector(max_scanned_fields=5).scan(event)

    assert caught.value.code == "scan.limit.max_nodes"
    assert oversized.items_called is False


@pytest.mark.parametrize(
    ("detector_kwargs", "event", "issue"),
    [
        (
            {"max_depth": 1},
            _event(payload={"a": {"b": {"c": "alice@example.com"}}}),
            "scan.limit.max_depth",
        ),
        (
            {"max_field_chars": 8},
            _event(text="token=secret-value"),
            "scan.limit.max_field_chars",
        ),
        (
            {"max_scan_bytes": 4},
            _event(text="token=secret-value"),
            "scan.limit.max_total_bytes",
        ),
        (
            {"max_scanned_fields": 1},
            _event(),
            "scan.limit.max_nodes",
        ),
    ],
)
def test_structural_scan_limits_fail_before_unbounded_snapshot(
    detector_kwargs: dict[str, int],
    event: MemoryEvent,
    issue: str,
) -> None:
    with pytest.raises(SafetyScanError) as caught:
        SensitiveDetector(**detector_kwargs).scan(event)

    assert caught.value.code == issue
    assert "secret-value" not in str(caught.value)


@pytest.mark.parametrize(
    ("detector_kwargs", "event", "issue"),
    [
        (
            {"max_candidates": 1},
            _event(text="a@b.com c@d.com"),
            "scan.limit.max_candidates",
        ),
        (
            {"max_findings": 1},
            _event(text="a@b.com c@d.com"),
            "scan.limit.max_findings",
        ),
    ],
)
def test_post_snapshot_limits_return_incomplete_non_leaking_reports(
    detector_kwargs: dict[str, int],
    event: MemoryEvent,
    issue: str,
) -> None:
    report = SensitiveDetector(**detector_kwargs).scan(event)

    assert report.scan_complete is False
    assert issue in report.issues


def test_deep_or_recursive_mutation_raises_a_stable_scan_error() -> None:
    nested: dict[str, object] = {"leaf": "safe"}
    for _ in range(120):
        nested = {"next": nested}

    with pytest.raises(SafetyScanError) as deep_error:
        SensitiveDetector().scan(_event(payload=nested))
    assert deep_error.value.code == "scan.limit.max_depth"

    recursive_event = _event(payload={"safe": "value"})
    recursive_event.payload["loop"] = recursive_event.payload
    with pytest.raises(SafetyScanError) as recursive_error:
        SensitiveDetector().scan(recursive_event)
    assert recursive_error.value.code == "scan.recursive_reference"


def test_maximum_supported_depth_is_explicit_and_reachable() -> None:
    nested: object = "safe"
    for _ in range(SafetyConfig.MAX_SUPPORTED_DEPTH):
        nested = {"next": nested}
    assert isinstance(nested, dict)

    report = SensitiveDetector(max_depth=SafetyConfig.MAX_SUPPORTED_DEPTH).scan(
        _event(payload=nested)
    )

    assert report.scan_complete is True
    with pytest.raises(ValueError, match="max_depth must be <= 64"):
        SensitiveDetector(max_depth=SafetyConfig.MAX_SUPPORTED_DEPTH + 1)
    with pytest.raises(ValueError, match="max_depth must be <= 64"):
        SafetyConfig(max_depth=SafetyConfig.MAX_SUPPORTED_DEPTH + 1)


def test_large_field_is_rejected_before_event_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = SensitiveDetector(max_field_chars=8)
    event = _event(text="x" * (1024 * 1024))

    def unexpected_model_dump(*args: object, **kwargs: object) -> object:
        raise AssertionError("event serialization ran before the structural preflight")

    monkeypatch.setattr(MemoryEvent, "model_dump", unexpected_model_dump)
    with pytest.raises(SafetyScanError) as caught:
        detector.scan(event)
    assert caught.value.code == "scan.limit.max_field_chars"


def test_scan_text_rejects_invalid_path_and_oversized_text() -> None:
    detector = SensitiveDetector(max_field_chars=4)

    with pytest.raises(RuleLibraryError):
        detector.scan_text("safe", "payload/value")
    with pytest.raises(SafetyScanError, match="max_field_chars"):
        detector.scan_text("12345")


def test_invalid_unicode_uses_a_stable_non_leaking_error() -> None:
    invalid = "\ud800"
    detector = SensitiveDetector()

    with pytest.raises(SafetyScanError) as event_error:
        detector.scan(_event(text=invalid))
    with pytest.raises(SafetyScanError) as text_error:
        detector.scan_text(invalid)
    with pytest.raises(SafetyScanError) as path_error:
        detector.scan_text("safe", f"/payload/{invalid}")

    assert {
        event_error.value.code,
        text_error.value.code,
        path_error.value.code,
    } == {"scan.invalid_unicode"}
    assert invalid not in str(event_error.value)


def test_snapshot_errors_do_not_retain_sensitive_exception_context() -> None:
    secret = "TOP_SECRET_TOKEN_123"
    event = _event()
    event.tool_calls[0].status = secret

    with pytest.raises(SafetyScanError) as caught:
        SensitiveDetector().scan(event)

    error = caught.value
    assert error.code == "scan.snapshot_failed"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert secret not in repr(error)


def test_invalid_post_validation_tool_call_uses_stable_snapshot_error() -> None:
    event = _event()
    event.tool_calls[0] = object()

    with pytest.raises(SafetyScanError) as caught:
        SensitiveDetector().scan(event)

    assert caught.value.code == "scan.snapshot_failed"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_scan_limits_are_validated_and_forwarded_from_config() -> None:
    config = SafetyConfig(
        max_depth=3,
        max_field_chars=128,
        max_scan_bytes=512,
        max_scanned_fields=20,
        max_candidates=10,
        max_findings=5,
        max_path_chars=64,
    )
    detector = SensitiveDetector.from_config(config)

    assert detector.max_depth == 3
    assert detector.max_field_chars == 128
    assert detector.max_scan_bytes == 512
    assert detector.max_scanned_fields == 20
    assert detector.max_candidates == 10
    assert detector.max_findings == 5
    assert detector.max_path_chars == 64
    with pytest.raises(ValueError, match="positive integer"):
        SafetyConfig(max_depth=True)


def test_direct_rules_use_the_same_regex_safety_gate() -> None:
    with pytest.raises(RuleLibraryError, match="repeat"):
        SensitiveDetector({"dangerous": r"(a+)+$"}, rules=[])

    dangerous_path = SensitiveRule(
        name="dangerous_path",
        pattern=r"secret",
        path_pattern=r"(a+)+$",
        level=SensitiveLevel.HIGH,
        action=SafetyAction.REVIEW,
        reason_code="secret.test",
        reason="test",
        standard_source="test",
    )
    with pytest.raises(RuleLibraryError, match="repeat"):
        SensitiveDetector(rules=[dangerous_path])


def test_legacy_content_override_can_reuse_a_trusted_compiled_path() -> None:
    detector = SensitiveDetector(
        {"credential_field": r"(?s)\A.+\Z"},
    )

    findings = detector.scan(_event(payload={"password": "value"})).findings

    assert any(finding.rule_name == "credential_field" for finding in findings)


def test_direct_rule_cannot_inherit_builtin_priority_by_impersonating_its_name() -> (
    None
):
    builtin = load_builtin_rule_set()
    credential = next(
        rule for rule in builtin.compiled_rules if rule.name == "credential_field"
    )
    bank_card = next(
        rule
        for rule in builtin.compiled_rules
        if rule.name == "sensitive_personal.bank_card"
    )
    data = credential.model_dump(mode="python")
    data.update(
        {
            "pattern": r"\b4111111111111111\b",
            "path_pattern": "",
            "action": SafetyAction.MASK,
            "reason_code": "test.impersonated_name",
            "reason": "untrusted direct rule",
            "standard_source": "test",
            "match_group": 0,
        }
    )
    impostor = SensitiveRule.model_validate(data)

    findings = SensitiveDetector(rules=[impostor, bank_card]).scan_text(
        "4111111111111111"
    )

    assert [finding.rule_name for finding in findings] == [
        "sensitive_personal.bank_card"
    ]


def test_whole_value_contract_does_not_accept_a_fabricated_text_span() -> None:
    assert safety_api.SafetyFindingTarget is SafetyFindingTarget
    with pytest.raises(ValueError, match="start=end=0"):
        SafetyFinding(
            rule_name="credential_field",
            rule_version="1.0",
            level=SensitiveLevel.HIGH,
            suggested_action=SafetyAction.REJECT,
            field_path="/payload/password",
            target=SafetyFindingTarget.WHOLE_VALUE,
            start=0,
            end=1,
            reason_code="secret.credential_field",
            reason="credential",
            standard_source="test",
        )
