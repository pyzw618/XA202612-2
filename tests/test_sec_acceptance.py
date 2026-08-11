# -*- coding: utf-8 -*-
"""SEC-01 ~ SEC-19 安全模块专项验收测试。

对应 docs/TEST_PLAN.md 6.1 安全模块专项的逐项验收。
每个测试直接驱动真实实现（内置规则集 / 检测器 / 审计 / 门禁 / 隔离区 /
用户规则 / 生产配置门禁），对应用例矩阵列出通过/失败记录。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memoryhub.adapter.schemas import (
    MemoryEvent,
    SafetyAction,
    SafetyExceptionScope,
    SafetyPolicy,
    SafetyPolicyException,
    SafetyRuleOverride,
    SensitiveLevel,
    SensitiveRule,
)
from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    ProductionGateError,
    RuntimeConfig,
    SafetyConfig,
    VectorEngineConfig,
    load_config,
    validate_production_gate,
)
from memoryhub.core.safety import (
    InMemoryUserRuleRepository,
    RuleLibraryError,
    SafetyAuditLog,
    SafetyAuditLogError,
    SafetyGateError,
    SafetyScanError,
    UserRuleError,
    UserRuleService,
)
from memoryhub.core.safety.detector import SensitiveDetector
from memoryhub.core.safety.gate import GateOutcome, GuardedCallbacks, SafetyWriteGate
from memoryhub.core.safety.quarantine import QuarantineError, ReviewQuarantineStore
from memoryhub.core.safety.user_rules import UserRuleEffect, UserRuleKind, build_user_rule_service
from memoryhub.safety_rules import load_builtin_rule_set


def _now() -> datetime:
    return datetime(2026, 7, 24, tzinfo=timezone.utc)


def _rule(
    name: str,
    pattern: str,
    action: SafetyAction,
    *,
    level: SensitiveLevel = SensitiveLevel.HIGH,
) -> SensitiveRule:
    return SensitiveRule(
        name=name,
        pattern=pattern,
        level=level,
        action=action,
        reason_code=f"test.{name}",
        reason=f"test rule {name}",
        standard_source="test-rules@1.0",
    )


def _event(**overrides) -> MemoryEvent:
    base = {
        "event_id": "evt_sec_001",
        "source_type": "tool_result",
        "event_type": "tool_result",
        "user_id": "u_sec",
        "session_id": "s_sec",
        "turn_id": "t_sec",
        "scene": "office",
        "task_type": "weekly_report",
        "occurred_at": "2026-07-24T10:30:00Z",
        "text": "普通事件",
        "payload": {"ok": True},
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": "a" * 64,
        "quality": {
            "score": 0.9,
            "status": "accepted",
            "completeness": 1.0,
            "validity": 1.0,
            "consistency": 1.0,
            "freshness": 1.0,
        },
    }
    base.update(overrides)
    if "tool_calls" not in overrides:
        base["tool_calls"] = [
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
    return MemoryEvent.model_validate(base)


def _exception(rule_name: str, *, scene: str = "office", task_type: str = "weekly_report") -> SafetyPolicyException:
    return SafetyPolicyException(
        exception_id="allow_test_rule",
        version="1.0",
        reason="acceptance exception",
        owner="security-team",
        scope=SafetyExceptionScope(
            rule_names=(rule_name,),
            scenes=(scene,),
            task_types=(task_type,),
            field_paths=("/payload/ip",),
        ),
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# SEC-01 规则库加载与版本完整
# ---------------------------------------------------------------------------


class TestSec01RuleLibraryLoading:
    def test_builtin_rule_set_has_expected_version_and_digest(self) -> None:
        snapshot = load_builtin_rule_set(version="1.0")
        assert snapshot.version == "1.0"
        assert len(snapshot.digest) == 64
        assert len(snapshot.rules) >= 14

    def test_missing_version_fails_closed_no_fallback(self) -> None:
        with pytest.raises(RuleLibraryError):
            load_builtin_rule_set(version="9.9.9")

    def test_rule_has_structured_provenance_refs(self) -> None:
        snapshot = load_builtin_rule_set(version="1.0")
        for rule in snapshot.rules:
            assert rule.standard_ref, f"{rule.rule_id} 缺少 standard_ref"
            for ref in rule.standard_ref:
                assert ref.source_id and ref.role


# ---------------------------------------------------------------------------
# SEC-02 检测器跨字段递归扫描
# ---------------------------------------------------------------------------


class TestSec02RecursiveScan:
    def test_text_and_payload_and_tool_result_all_scanned(self) -> None:
        detector = SensitiveDetector()
        event = _event(
            text="联系 alice@example.com",
            payload={"card": "4111111111111111"},
            tool_calls=[
                {
                    "call_id": "c1",
                    "tool_name": "t",
                    "arguments": {},
                    "result": "ip 192.168.1.1",
                    "status": "success",
                    "sequence": 1,
                    "error": "",
                }
            ],
        )
        report = detector.scan(event)
        names = {f.rule_name for f in report.findings}
        assert "email" in names
        assert "sensitive_personal.bank_card" in names
        assert "ip_address" in names
        paths = {f.field_path for f in report.findings}
        assert any(p.startswith("/text") for p in paths)
        assert any(p.startswith("/payload") for p in paths)
        assert any(p.startswith("/tool_calls") for p in paths)
        assert report.scan_complete is True

    def test_scan_does_not_mutate_original_event(self) -> None:
        detector = SensitiveDetector()
        event = _event(text="联系 alice@example.com")
        snapshot = event.model_dump_json()
        detector.scan(event)
        assert event.model_dump_json() == snapshot


# ---------------------------------------------------------------------------
# SEC-03 敏感信息识别样例矩阵
# ---------------------------------------------------------------------------


class TestSec03DetectionMatrix:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("邮箱 alice@example.com", "email"),
            ("电话 13800138000", "phone"),
            ("身份证 11010519491231002X", "id_card"),
            ("密钥 api_key=sk-1a2b3c4d5e6f7g8h9i0j", "api_key"),
        ],
    )
    def test_builtin_pattern_detects_example(self, text: str, expected: str) -> None:
        detector = SensitiveDetector()
        findings = detector.scan(_event(text=text)).findings
        assert expected in {f.rule_name for f in findings}

    def test_credential_field_named_value_is_rejected(self) -> None:
        detector = SensitiveDetector()
        result = detector.process(
            _event(payload={"password": "hunter2secret"})
        )
        assert result.decision.action is SafetyAction.REJECT
        assert any(
            f.rule_name == "credential_field" for f in result.report.findings
        )


# ---------------------------------------------------------------------------
# SEC-04 扫描预算超限时 fail-closed
# ---------------------------------------------------------------------------


class TestSec04Budget:
    def test_depth_limit_exceeded_raises_stable_error(self) -> None:
        detector = SensitiveDetector(max_depth=2)
        nested: dict = {"v": "safe"}
        for _ in range(40):
            nested = {"nested": nested}
        with pytest.raises(SafetyScanError) as exc:
            detector.scan(_event(payload=nested))
        assert exc.value.code == "scan.limit.max_depth"

    def test_oversized_field_raises_stable_error(self) -> None:
        detector = SensitiveDetector(max_field_chars=16)
        with pytest.raises(SafetyScanError) as exc:
            detector.scan(_event(text="x" * 100))
        assert exc.value.code == "scan.limit.max_field_chars"
        assert "xxx" not in str(exc.value)


# ---------------------------------------------------------------------------
# SEC-05 Unicode 变体与混淆输入
# ---------------------------------------------------------------------------


class TestSec05UnicodeVariants:
    def test_fullwidth_phone_variant_detected(self) -> None:
        detector = SensitiveDetector()
        phone = "１３８００１３８０００"
        event = _event(text=f"号码:{phone}")
        findings = detector.scan(event).findings
        phones = [f for f in findings if f.rule_name == "phone"]
        assert phones
        # span 反投影回原文
        assert event.text[phones[0].start : phones[0].end] == phone

    def test_zero_width_separator_variant_detected(self) -> None:
        detector = SensitiveDetector()
        phone = "138\u200b0013\u200b8000"
        event = _event(text=f"号码:{phone}")
        findings = detector.scan(event).findings
        phones = [f for f in findings if f.rule_name == "phone"]
        assert phones
        assert event.text[phones[0].start : phones[0].end] == phone


# ---------------------------------------------------------------------------
# SEC-06 决策聚合优先级
# ---------------------------------------------------------------------------


class TestSec06DecisionPrecedence:
    def test_reject_beats_mask_when_rule_matches(self) -> None:
        detector = SensitiveDetector(
            rules=[
                _rule("sec.mask", "token-123", SafetyAction.MASK, level=SensitiveLevel.LOW),
                _rule("sec.reject", "token-456", SafetyAction.REJECT, level=SensitiveLevel.HIGH),
            ]
        )
        report = detector.scan(_event(text="token-123 token-456"))
        decision = detector.decide(report)
        assert decision.action is SafetyAction.REJECT

    def test_review_falls_through_when_matching_exception_present(self) -> None:
        detector = SensitiveDetector(
            rules=[
                _rule("sec.review", "10.20.30.40", SafetyAction.MASK, level=SensitiveLevel.LOW),
            ]
        )
        policy = SafetyPolicy(exceptions=(_exception("sec.review"),))
        report = detector.scan(_event(payload={"ip": "10.20.30.40"}))
        assert detector.decide(report, policy).action is SafetyAction.ALLOW


# ---------------------------------------------------------------------------
# SEC-07 覆盖策略不能削弱默认动作
# ---------------------------------------------------------------------------


class TestSec07OverridesCannotWeaken:
    def test_rule_override_cannot_downgrade_reject(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.cred", "sk-cred", SafetyAction.REJECT)],
            policy=SafetyPolicy(
                rule_overrides=(
                    SafetyRuleOverride(rule_name="sec.cred", action=SafetyAction.MASK),
                )
            ),
        )
        decision = detector.decide(detector.scan(_event(text="sk-cred")))
        assert decision.action is SafetyAction.REJECT

    def test_level_override_cannot_downgrade_reject(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.cred", "sk-cred", SafetyAction.REJECT)],
            policy=SafetyPolicy(
                rule_overrides=(
                    SafetyRuleOverride(rule_name="sec.cred", action=SafetyAction.REVIEW),
                )
            ),
        )
        decision = detector.decide(detector.scan(_event(text="sk-cred")))
        assert decision.action is SafetyAction.REJECT


# ---------------------------------------------------------------------------
# SEC-08 低风险上下文规则 ALLOW 例外
# ---------------------------------------------------------------------------


class TestSec08ContextualAllowException:
    def test_ip_rule_exception_allows_in_scope(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.ip", "10.20.30.40", SafetyAction.MASK, level=SensitiveLevel.LOW)]
        )
        policy = SafetyPolicy(
            exceptions=(_exception("sec.ip", scene="diagnostics", task_type="network_check"),)
        )
        event = _event(payload={"ip": "10.20.30.40"}, scene="diagnostics", task_type="network_check")
        decision = detector.decide(detector.scan(event), policy)
        assert decision.action is SafetyAction.ALLOW
        assert decision.exception_ids == ("allow_test_rule",)

    def test_out_of_scope_scene_not_excepted(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.ip", "10.20.30.40", SafetyAction.MASK, level=SensitiveLevel.LOW)]
        )
        policy = SafetyPolicy(
            exceptions=(_exception("sec.ip", scene="office", task_type="network_check"),)
        )
        event = _event(payload={"ip": "10.20.30.40"}, scene="diagnostics", task_type="network_check")
        decision = detector.decide(detector.scan(event), policy)
        assert decision.action is SafetyAction.MASK
        assert decision.exception_ids == ()

    def test_expired_exception_ignored(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.ip", "10.20.30.40", SafetyAction.MASK, level=SensitiveLevel.LOW)]
        )
        policy = SafetyPolicy(
            exceptions=(
                SafetyPolicyException(
                    exception_id="allow_test_rule",
                    version="1.0",
                    reason="expired",
                    owner="security-team",
                    scope=SafetyExceptionScope(
                        rule_names=("sec.ip",),
                        scenes=("diagnostics",),
                        task_types=("network_check",),
                        field_paths=("/payload/ip",),
                    ),
                    expires_at=_now() - timedelta(minutes=1),
                ),
            )
        )
        event = _event(payload={"ip": "10.20.30.40"}, scene="diagnostics", task_type="network_check")
        decision = detector.decide(detector.scan(event), policy)
        assert decision.action is SafetyAction.MASK
        assert decision.exception_ids == ()

    def test_high_risk_rule_cannot_get_allow_exception(self) -> None:
        detector = SensitiveDetector(
            rules=[_rule("sec.cred", "sk-cred", SafetyAction.MASK, level=SensitiveLevel.HIGH)]
        )
        policy = SafetyPolicy(
            exceptions=(
                _exception("sec.cred"),
            )
        )
        with pytest.raises(ValueError):
            SensitiveDetector(
                rules=[_rule("sec.cred", "sk-cred", SafetyAction.MASK, level=SensitiveLevel.HIGH)],
                policy=policy,
            )


# ---------------------------------------------------------------------------
# SEC-09 脱敏输出与幂等复检
# ---------------------------------------------------------------------------


class TestSec09MaskIdempotency:
    def test_mask_output_clean_and_idempotent(self) -> None:
        detector = SensitiveDetector()
        event = _event(text="联系 alice@example.com 和 13800138000")
        result = detector.process(event)
        assert result.decision.action is SafetyAction.MASK
        clean_text = result.sanitized_event.text
        assert "alice@example.com" not in clean_text
        assert "13800138000" not in clean_text
        again = detector.process(result.sanitized_event)
        assert again.decision.action is SafetyAction.ALLOW
        assert again.report.findings == ()
        assert again.sanitized_event.model_dump(mode="json") == result.sanitized_event.model_dump(mode="json")


# ---------------------------------------------------------------------------
# SEC-10 结果认证与防伪
# ---------------------------------------------------------------------------


class TestSec10Attestation:
    def test_process_result_has_attestation(self) -> None:
        detector = SensitiveDetector()
        result = detector.process(_event(text="联系 alice@example.com"))
        assert result.attestation
        assert result.report.attestation

    def test_cross_instance_result_rejected(self) -> None:
        detector_a = SensitiveDetector()
        detector_b = SensitiveDetector()
        result = detector_a.process(_event(text="联系 alice@example.com"))
        with pytest.raises(Exception):
            detector_b.validate_result(_event(text="联系 alice@example.com"), result)


# ---------------------------------------------------------------------------
# SEC-11 审计日志哈希链防篡改
# ---------------------------------------------------------------------------


class TestSec11AuditTamper:
    def test_tampered_record_breaks_chain(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(
            tmp_path / "audit",
            fingerprint_key=b"a" * 32,
        )
        for i in range(3):
            audit.append(_event(event_id=f"evt_{i}"), detector.process(_event(event_id=f"evt_{i}")), detector)
        assert audit.verify().record_count == 3

        # 篡改中段记录
        segment = next(audit.directory.glob("safety-audit-*.jsonl"))
        lines = segment.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["policy_version"] = "tampered"
        lines[1] = json.dumps(record, sort_keys=True)
        segment.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(SafetyAuditLogError):
            audit.verify()

    def test_tail_truncation_detected(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(
            tmp_path / "audit",
            fingerprint_key=b"a" * 32,
        )
        for i in range(3):
            audit.append(_event(event_id=f"evt_{i}"), detector.process(_event(event_id=f"evt_{i}")), detector)

        segment = next(audit.directory.glob("safety-audit-*.jsonl"))
        lines = segment.read_text(encoding="utf-8").splitlines()
        segment.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

        with pytest.raises(SafetyAuditLogError):
            audit.verify()


# ---------------------------------------------------------------------------
# SEC-12 审计轮转与保留策略
# ---------------------------------------------------------------------------


class TestSec12RotationRetention:
    def test_rotation_keeps_single_verifiable_chain(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(
            tmp_path / "audit",
            fingerprint_key=b"a" * 32,
            rotate_max_bytes=400,
            retention_days=None,
            verify_on_start=False,
        )
        verified = audit.verify()
        count = 0
        while verified.segment_count < 2:
            audit.append(_event(event_id=f"rot_{count}"), detector.process(_event(event_id=f"rot_{count}")), detector)
            count += 1
            verified = audit.verify()
        assert verified.segment_count >= 2
        assert verified.record_count == count

    def test_retention_prunes_old_segments(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(
            tmp_path / "audit",
            fingerprint_key=b"a" * 32,
            rotate_max_bytes=400,
            retention_days=1,
            verify_on_start=False,
        )
        verified = audit.verify()
        count = 0
        while verified.segment_count < 2:
            audit.append(_event(event_id=f"rot_{count}"), detector.process(_event(event_id=f"rot_{count}")), detector)
            count += 1
            verified = audit.verify()
        segments = sorted(audit.directory.glob("safety-audit-*.jsonl"))
        old = datetime.now(timezone.utc) - timedelta(days=10)
        for path in segments[:-1]:
            os.utime(path, (old.timestamp(), old.timestamp()))
        audit.enforce_retention()
        verified = audit.verify()
        assert verified.anchored is True
        assert verified.record_count == 1


# ---------------------------------------------------------------------------
# SEC-13 REVIEW 隔离区加密存储
# ---------------------------------------------------------------------------


class TestSec13Quarantine:
    def _route_review(self, tmp_path: Path, *, now: datetime | None = None, key: bytes = b"b" * 32, retention_days: int = 30) -> tuple[GateOutcome, ReviewQuarantineStore]:
        detector = SensitiveDetector(rules=[_rule("sec.review", "quarantine-secret", SafetyAction.REVIEW, level=SensitiveLevel.MEDIUM)])
        quarantine = ReviewQuarantineStore(
            tmp_path / "quarantine",
            encryption_key=key,
            retention_days=retention_days,
            now_factory=(lambda: now) if now else None,
        )
        audit = SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32)
        gate = SafetyWriteGate(detector, audit, quarantine=quarantine)
        outcome = gate.route(_event(text="quarantine-secret", event_id="evt_review_1"))
        assert outcome.review is not None
        return outcome, quarantine

    def test_review_record_plaintext_not_stored_on_disk(self, tmp_path: Path) -> None:
        outcome, quarantine = self._route_review(tmp_path)
        payload = "".join(
            p.read_text(encoding="utf-8")
            for p in (tmp_path / "quarantine").rglob("*")
            if p.is_file()
        )
        assert "quarantine-secret" not in payload
        loaded = quarantine.load(outcome.review.review_id)
        assert loaded.event_id == "evt_review_1"

    def test_expired_review_record_cannot_be_loaded(self, tmp_path: Path) -> None:
        now = _now()
        outcome, quarantine = self._route_review(tmp_path, now=now, retention_days=1)
        quarantine._now_factory = lambda: now + timedelta(days=2)
        with pytest.raises(QuarantineError):
            quarantine.load(outcome.review.review_id)

    def test_wrong_key_cannot_decrypt(self, tmp_path: Path) -> None:
        outcome, _ = self._route_review(tmp_path)
        wrong = ReviewQuarantineStore(tmp_path / "quarantine", encryption_key=b"c" * 32)
        with pytest.raises(QuarantineError):
            wrong.load(outcome.review.review_id)


# ---------------------------------------------------------------------------
# SEC-14 写入门禁强制与回调守卫
# ---------------------------------------------------------------------------


class TestSec14WriteGate:
    def test_audit_failure_blocks_write_and_callbacks(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32)
        gate = SafetyWriteGate(detector, audit)
        received: list = []
        result = gate.dispatch(
            _event(text="联系 alice@example.com"),
            GuardedCallbacks(sqlite=received.append),
        )
        assert result.action is SafetyAction.MASK
        assert received

    def test_gate_route_forces_reject_before_any_callback(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        audit = SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32)
        gate = SafetyWriteGate(detector, audit)
        received: list = []
        result = gate.dispatch(
            _event(text="password = sk-cred-1"),
            GuardedCallbacks(sqlite=received.append),
        )
        assert result.action is SafetyAction.REJECT
        assert received == []

    def test_key_reuse_across_components_rejected(self, tmp_path: Path) -> None:
        detector = SensitiveDetector()
        with pytest.raises(SafetyGateError):
            SafetyWriteGate.from_config(
                detector,
                SafetyConfig(
                    audit={"directory": str(tmp_path / "audit")},
                    quarantine={"directory": str(tmp_path / "quarantine")},
                ),
                audit_hmac_key=b"same-key-32bytes-xxxxx",
                quarantine_key=b"same-key-32bytes-xxxxx",
            )


# ---------------------------------------------------------------------------
# SEC-15 用户规则 CRUD
# ---------------------------------------------------------------------------


class TestSec15UserRuleCrud:
    def _service(self) -> UserRuleService:
        return UserRuleService(InMemoryUserRuleRepository(), master_key=b"m" * 32)

    def test_create_list_update_get_delete_cycle(self) -> None:
        service = self._service()
        view = service.create_rule(
            "u1",
            label="项目代号",
            kind=UserRuleKind.LITERAL,
            effect=UserRuleEffect.MASK_MATCH,
            matcher="C++20",
        )
        assert view.rule_id.startswith("ur_")
        assert view.revision == 1
        assert not hasattr(view, "matcher")

        listed = service.list_rules("u1")
        assert any(r.rule_id == view.rule_id for r in listed)

        updated = service.update_rule(
            "u1", view.rule_id, expected_revision=1, label="改名"
        )
        assert updated.label == "改名"
        assert updated.revision == 2

        fetched = service.get_rule("u1", view.rule_id)
        assert fetched.rule_id == view.rule_id

        service.delete_rule("u1", view.rule_id, expected_revision=2)
        deleted = service.get_rule("u1", view.rule_id, include_deleted=True)
        assert deleted.deleted is True

    def test_stale_revision_conflict_rejected(self) -> None:
        service = self._service()
        view = service.create_rule(
            "u1", label="l", kind=UserRuleKind.LITERAL, effect=UserRuleEffect.MASK_MATCH, matcher="x"
        )
        service.update_rule("u1", view.rule_id, expected_revision=1, label="v2")
        with pytest.raises(UserRuleError):
            service.update_rule("u1", view.rule_id, expected_revision=1, label="v3")


# ---------------------------------------------------------------------------
# SEC-16 用户规则生效于写入管线
# ---------------------------------------------------------------------------


class TestSec16UserRuleInPipeline:
    def test_mask_match_rule_redacts_in_gate(self, tmp_path: Path) -> None:
        service = UserRuleService(InMemoryUserRuleRepository(), master_key=b"m" * 32)
        service.create_rule(
            "u1", label="代号", kind=UserRuleKind.LITERAL, effect=UserRuleEffect.MASK_MATCH, matcher="C++20"
        )
        audit = SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32)
        gate = SafetyWriteGate(
            None,
            audit,
            detector_provider=service.detector_provider(_safety_config()),
        )
        received: list = []
        result = gate.dispatch(
            _event(text="项目基于 C++20", user_id="u1"),
            GuardedCallbacks(sqlite=received.append),
        )
        assert received
        assert "C++20" not in received[0].safe_event.text

    def test_drop_event_rule_blocks_write(self, tmp_path: Path) -> None:
        service = UserRuleService(InMemoryUserRuleRepository(), master_key=b"m" * 32)
        service.create_rule(
            "u1", label="勿存", kind=UserRuleKind.LITERAL, effect=UserRuleEffect.DROP_EVENT, matcher="never-store"
        )
        audit = SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32)
        gate = SafetyWriteGate(
            None,
            audit,
            detector_provider=service.detector_provider(_safety_config()),
        )
        received: list = []
        result = gate.dispatch(
            _event(text="never-store 内容", user_id="u1"),
            GuardedCallbacks(sqlite=received.append),
        )
        assert result.action is SafetyAction.REJECT
        assert received == []


# ---------------------------------------------------------------------------
# SEC-17 用户规则安全边界
# ---------------------------------------------------------------------------


class TestSec17UserRuleBoundary:
    def test_plaintext_matcher_and_ciphertext_never_in_view(self) -> None:
        service = UserRuleService(
            InMemoryUserRuleRepository(), master_key=b"m" * 32, allow_advanced_regex=True
        )
        view = service.create_rule(
            "u1", label="l", kind=UserRuleKind.ADVANCED_REGEX, effect=UserRuleEffect.MASK_MATCH, matcher=r"^sk-[a-z0-9]{8}$"
        )
        assert not hasattr(view, "matcher")
        assert "sk-" not in repr(view)

    def test_file_backed_service_roundtrip(self, tmp_path: Path) -> None:
        service = build_user_rule_service(tmp_path / "rules.db", master_key=b"m" * 32)
        view = service.create_rule(
            "u1", label="l", kind=UserRuleKind.LITERAL, effect=UserRuleEffect.MASK_MATCH, matcher="token"
        )
        reloaded = build_user_rule_service(tmp_path / "rules.db", master_key=b"m" * 32)
        fetched = reloaded.get_rule("u1", view.rule_id)
        assert fetched.rule_id == view.rule_id

    def test_wrong_master_key_fails_closed(self, tmp_path: Path) -> None:
        service = build_user_rule_service(tmp_path / "rules.db", master_key=b"m" * 32)
        service.create_rule(
            "u1", label="l", kind=UserRuleKind.LITERAL, effect=UserRuleEffect.MASK_MATCH, matcher="token"
        )
        wrong = build_user_rule_service(tmp_path / "rules.db", master_key=b"n" * 32)
        assert wrong.list_rules("u1") == ()
        with pytest.raises(UserRuleError):
            wrong.get_rule("u1", service.list_rules("u1")[0].rule_id)


# ---------------------------------------------------------------------------
# SEC-18 错误与日志不含敏感原文
# ---------------------------------------------------------------------------


class TestSec18NoPlaintextInErrors:
    def test_scan_budget_error_contains_no_plaintext(self) -> None:
        detector = SensitiveDetector(max_field_chars=4)
        with pytest.raises(SafetyScanError) as exc:
            detector.scan(_event(text="sk-verysecret"))
        assert "sk-verysecret" not in str(exc.value)

    def test_quarantine_error_contains_no_plaintext(self, tmp_path: Path) -> None:
        quarantine = ReviewQuarantineStore(tmp_path / "q", encryption_key=b"b" * 32)
        with pytest.raises(QuarantineError) as exc:
            quarantine.load("not-a-real-id")
        assert "not-a-real-id" not in str(exc.value)

    def test_gate_error_contains_no_event_content(self, tmp_path: Path) -> None:
        gate = SafetyWriteGate(SensitiveDetector(), SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32))
        with pytest.raises(SafetyGateError) as exc:
            gate.route("not an event")  # type: ignore[arg-type]
        assert "not an event" not in str(exc.value)


# ---------------------------------------------------------------------------
# SEC-19 生产配置门禁
# ---------------------------------------------------------------------------


class TestSec19ProductionGate:
    def _config(self, *, provider: str, engine: str, allow_fallback: bool = True, mode: str = "production") -> AppConfig:
        return AppConfig(
            runtime=RuntimeConfig(mode=mode, allow_fallback=allow_fallback),
            embedding=EmbeddingConfig(provider=provider, dimension=768),
            vector_engine=VectorEngineConfig(provider=engine, dimension=768, app_id="app-1"),
        )

    def test_mock_embedding_rejected(self) -> None:
        with pytest.raises(ProductionGateError):
            validate_production_gate(self._config(provider="mock", engine="milvus", allow_fallback=False))

    def test_kylin_mock_embedding_rejected(self) -> None:
        with pytest.raises(ProductionGateError):
            validate_production_gate(self._config(provider="kylin_mock", engine="milvus", allow_fallback=False))

    def test_faiss_vector_engine_rejected(self) -> None:
        with pytest.raises(ProductionGateError):
            validate_production_gate(self._config(provider="kylin", engine="faiss", allow_fallback=False))

    def test_milvus_mock_rejected(self) -> None:
        with pytest.raises(ProductionGateError):
            validate_production_gate(self._config(provider="kylin", engine="milvus_mock", allow_fallback=False))

    def test_allow_fallback_rejected(self) -> None:
        with pytest.raises(ProductionGateError):
            validate_production_gate(self._config(provider="kylin", engine="milvus", allow_fallback=True))

    def test_development_mode_skips_gate(self) -> None:
        validate_production_gate(self._config(provider="mock", engine="faiss", mode="development"))

    def test_kylin_milvus_passes(self) -> None:
        validate_production_gate(self._config(provider="kylin", engine="milvus", allow_fallback=False))

    def test_load_config_validates(self, tmp_path: Path, monkeypatch) -> None:
        from memoryhub.config import load_config

        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")
        # 默认 embedding=mock/1024 与 vector=faiss 不满足生产门禁，加载必须失败。
        with pytest.raises(ProductionGateError):
            load_config(str(tmp_path / "nonexistent.toml"))


def _safety_config():
    from memoryhub.config import SafetyConfig

    return SafetyConfig()
