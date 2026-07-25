"""敏感信息递归扫描、策略决策、全值脱敏与同快照复检。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import islice
from types import MappingProxyType
from typing import Any, Callable, NoReturn

from memoryhub.adapter.schemas import (
    DEFAULT_SENSITIVE_RULES,
    MemoryEvent,
    SafetyAction,
    SafetyAuditFinding,
    SafetyAuditRecord,
    SafetyDecision,
    SafetyDecisionContext,
    SafetyFinding,
    SafetyFindingDecision,
    SafetyFindingTarget,
    SafetyPolicy,
    SafetyPolicyException,
    SafetyReport,
    SafetyResult,
    SensitiveLevel,
    SensitiveRule,
    canonical_sha256,
)
from memoryhub.config import SafetyConfig
from memoryhub.safety_rules import (
    ComponentRegistry,
    RuleSetSnapshot,
    load_builtin_rule_set,
)
from memoryhub.safety_rules.paths import validate_json_path
from memoryhub.safety_rules.regex_safety import validate_regex_safety

_BUILTIN_RULE_SNAPSHOT = load_builtin_rule_set()
_LEVEL_RANK = {
    SensitiveLevel.NONE: 0,
    SensitiveLevel.LOW: 1,
    SensitiveLevel.MEDIUM: 2,
    SensitiveLevel.HIGH: 3,
}
_ACTION_RANK = {
    SafetyAction.ALLOW: 0,
    SafetyAction.MASK: 1,
    SafetyAction.REVIEW: 2,
    SafetyAction.REJECT: 3,
}
_REPORT_METADATA_MARKERS = {
    "/event_id": "[REDACTED_EVENT_ID]",
    "/event_type": "[REDACTED_EVENT_TYPE]",
    "/scene": "[REDACTED_SCENE]",
    "/task_type": "[REDACTED_TASK_TYPE]",
}
_REDACTION_MARKER_RE = re.compile(r"^\[REDACTED(?:_[A-Z0-9_]+)?\]$")
_REDACTION_MARKER_SPAN_RE = re.compile(r"\[REDACTED(?:_[A-Z0-9_]+)?\]")
_OVERLAY_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_OVERLAY_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MIN_OVERLAY_PRIORITY = -1_000_000
_MAX_OVERLAY_PRIORITY = 1_000_000
_DEFAULT_OVERLAY_MASK_PRIORITY = _MIN_OVERLAY_PRIORITY
_DEFAULT_OVERLAY_REJECT_PRIORITY = _MAX_OVERLAY_PRIORITY


class SafetyScanError(ValueError):
    """扫描在生成可信事件摘要前失败；消息只包含稳定代码，不包含输入原文。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SafetySanitizationError(ValueError):
    """脱敏无法安全完成；消息只包含稳定代码，不包含事件内容。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SafetyDecisionError(ValueError):
    """策略或报告无法可信决策；消息只包含稳定代码，不包含输入原文。"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SafetyRuleOverlay:
    """
    由受信任的用户规则存储编译出的不可变附加规则快照。

    ``keyed_digest`` 必须由边界外的持久化服务使用独立密钥计算。Detector
    只校验摘要形状，并以 ``base digest + keyed digest`` 派生有效规则摘要；
    因而持久审计不会包含低熵 matcher 的普通 SHA-256 字典指纹。

    Overlay 只允许收紧为 MASK 或 REJECT。分类固定为 ``user_defined``；
    显式映射用于保证每条运行时规则都有可审计分类和确定性优先级。
    """

    rules: tuple[SensitiveRule, ...]
    keyed_digest: str
    revision: str
    categories: Mapping[str, str] = field(default_factory=dict)
    priorities: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            normalized_rules = tuple(
                SensitiveRule.model_validate(
                    rule.model_dump(mode="python")
                    if isinstance(rule, SensitiveRule)
                    else rule
                )
                for rule in self.rules
            )
        except Exception:
            raise ValueError("overlay rules are invalid") from None
        if not normalized_rules:
            raise ValueError("overlay must contain at least one rule")
        names = tuple(rule.name for rule in normalized_rules)
        if len(names) != len(set(names)):
            raise ValueError("overlay rule names must be unique")
        if re.fullmatch(r"[0-9a-f]{64}", self.keyed_digest) is None:
            raise ValueError("overlay keyed_digest must be a lowercase keyed SHA-256")
        if (
            not isinstance(self.revision, str)
            or _OVERLAY_REVISION_RE.fullmatch(self.revision) is None
        ):
            raise ValueError("overlay revision must be a stable identifier")
        if not isinstance(self.categories, Mapping):
            raise ValueError("overlay categories must be a mapping")
        if not isinstance(self.priorities, Mapping):
            raise ValueError("overlay priorities must be a mapping")

        unknown_categories = set(self.categories) - set(names)
        unknown_priorities = set(self.priorities) - set(names)
        if unknown_categories:
            raise ValueError("overlay categories reference unknown rules")
        if unknown_priorities:
            raise ValueError("overlay priorities reference unknown rules")

        normalized_categories: dict[str, str] = {}
        normalized_priorities: dict[str, int] = {}
        for rule in normalized_rules:
            if not rule.enabled:
                raise ValueError("overlay rules must be enabled")
            if rule.action not in (SafetyAction.MASK, SafetyAction.REJECT):
                raise ValueError("overlay rules may only MASK or REJECT")
            if _REDACTION_MARKER_RE.fullmatch(rule.replacement) is None:
                raise ValueError("overlay rules require a fixed redaction marker")

            category = self.categories.get(rule.name, "user_defined")
            if (
                not isinstance(category, str)
                or _OVERLAY_CATEGORY_RE.fullmatch(category) is None
                or category != "user_defined"
            ):
                raise ValueError("overlay rule category must be user_defined")
            normalized_categories[rule.name] = category

            default_priority = (
                _DEFAULT_OVERLAY_REJECT_PRIORITY
                if rule.action is SafetyAction.REJECT
                else _DEFAULT_OVERLAY_MASK_PRIORITY
            )
            priority = self.priorities.get(rule.name, default_priority)
            if (
                type(priority) is not int
                or priority < _MIN_OVERLAY_PRIORITY
                or priority > _MAX_OVERLAY_PRIORITY
            ):
                raise ValueError("overlay priorities must be bounded integers")
            normalized_priorities[rule.name] = priority

        object.__setattr__(self, "rules", normalized_rules)
        object.__setattr__(
            self,
            "categories",
            MappingProxyType(normalized_categories),
        )
        object.__setattr__(
            self,
            "priorities",
            MappingProxyType(normalized_priorities),
        )

    @property
    def digest(self) -> str:
        """兼容把 overlay 视为快照的调用方；值仍是外部提供的 keyed digest。"""

        return self.keyed_digest

    @property
    def version(self) -> str:
        """将存储 revision 暴露为只读版本标识。"""

        return self.revision


@dataclass(frozen=True, slots=True)
class _NormalizedText:
    """不修改原文的安全扫描视图，以及每个输出字符对应的原文区间。"""

    text: str
    origins: tuple[tuple[int, int], ...]

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        if start < 0 or end <= start or end > len(self.origins):
            raise ValueError("normalized match does not map to a non-empty source span")
        return self.origins[start][0], self.origins[end - 1][1]


@dataclass(frozen=True, slots=True)
class _RuntimeRule:
    rule: SensitiveRule
    content_pattern: re.Pattern[str]
    path_pattern: re.Pattern[str] | None
    validator: Callable[[str], bool] | None
    priority: int
    ordinal: int
    maskable: bool
    is_overlay: bool = False
    is_snapshot_rule: bool = False


@dataclass(frozen=True, slots=True)
class _Candidate:
    runtime_rule: _RuntimeRule
    field_path: str
    target: SafetyFindingTarget
    start: int
    end: int

    @property
    def span_length(self) -> int:
        if self.target is SafetyFindingTarget.WHOLE_VALUE:
            return 2**31 - 1
        return self.end - self.start


@dataclass(slots=True)
class _ScanState:
    max_depth: int
    max_field_chars: int
    max_scan_bytes: int
    max_scanned_fields: int
    max_candidates: int
    max_findings: int
    max_path_chars: int
    scanned_bytes: int = 0
    scanned_field_count: int = 0
    visited_nodes: int = 0
    candidate_count: int = 0
    issues: list[str] = field(default_factory=list)
    stop: bool = False

    def add_issue(self, code: str) -> None:
        if code not in self.issues:
            self.issues.append(code)


@dataclass(frozen=True, slots=True)
class _ScanPlan:
    """一次请求固定使用的规则、组件和扫描预算。"""

    runtime_rules: tuple[_RuntimeRule, ...]
    component_registries: tuple[ComponentRegistry, ...]
    rule_set_version: str
    rule_set_digest: str
    base_rule_set_digest: str
    max_depth: int
    max_field_chars: int
    max_scan_bytes: int
    max_scanned_fields: int
    max_candidates: int
    max_findings: int
    max_path_chars: int
    report_attestation_key: bytes


_DEFAULT_IGNORABLE_RANGES = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x180B, 0x180F),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)


def _is_default_ignorable(character: str) -> bool:
    """删除 Unicode 默认忽略字符，阻断把凭据拆开的绕过写法。"""

    codepoint = ord(character)
    return unicodedata.category(character) == "Cf" or any(
        start <= codepoint <= end for start, end in _DEFAULT_IGNORABLE_RANGES
    )


def _normalized_text(value: str) -> _NormalizedText:
    """
    按 base + combining marks 建立 NFKC 视图，并保留向原文的保守反向映射。

    零宽字符会并入前一个 normalization unit 的原文区间，因此后续按 Finding
    span 脱敏时也会一并移除夹在敏感值中的绕过字符。
    """

    normalized: list[str] = []
    origins: list[tuple[int, int]] = []
    index = 0
    length = len(value)
    while index < length:
        if _is_default_ignorable(value[index]):
            index += 1
            continue

        unit_start = index
        unit_characters = [value[index]]
        index += 1
        while index < length and (
            unicodedata.combining(value[index]) != 0
            or _is_default_ignorable(value[index])
        ):
            if not _is_default_ignorable(value[index]):
                unit_characters.append(value[index])
            index += 1

        unit = unicodedata.normalize("NFKC", "".join(unit_characters))
        for character in unit:
            if _is_default_ignorable(character):
                continue
            normalized.append(character)
            origins.append((unit_start, index))
    return _NormalizedText("".join(normalized), tuple(origins))


def normalize_sensitive_text(value: str) -> str:
    """Return the exact Unicode safety view used by content scanning."""

    if not isinstance(value, str):
        raise TypeError("sensitive text must be a string")
    return _normalized_text(value).text


def _escape_pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _normalized_pointer(value: str) -> str:
    """规范化实际 JSON Pointer 的各解码段，仅用于 path_pattern 匹配。"""

    validate_json_path(value)
    segments = value[1:].split("/")
    normalized_segments: list[str] = []
    for segment in segments:
        decoded = segment.replace("~1", "/").replace("~0", "~")
        normalized_segments.append(
            _escape_pointer_segment(_normalized_text(decoded).text)
        )
    return "/" + "/".join(normalized_segments)


def _utf8_prefix(value: str, byte_limit: int) -> str:
    if byte_limit <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= byte_limit:
        return value
    return encoded[:byte_limit].decode("utf-8", errors="ignore")


def _json_scalar(value: Any) -> str | None:
    if value is None or type(value) in (bool, int, float):
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return None
    return None


class SensitiveDetector:
    """
    敏感信息检测器接口。

    生产写入链必须调用 process()，一次性取得 SafetyResult。detect()、mask()
    和 should_reject() 仅为旧调用方保留，不应在同一请求中串联使用。
    """

    DEFAULT_RULES = _BUILTIN_RULE_SNAPSHOT.compiled_rules
    DEFAULT_RULE_SET_ID = _BUILTIN_RULE_SNAPSHOT.rule_set_id
    DEFAULT_RULE_SET_DIGEST = _BUILTIN_RULE_SNAPSHOT.digest
    DEFAULT_MAX_DEPTH = 32
    DEFAULT_MAX_FIELD_CHARS = 65_536
    DEFAULT_MAX_SCAN_BYTES = 2 * 1024 * 1024
    DEFAULT_MAX_SCANNED_FIELDS = 10_000
    DEFAULT_MAX_CANDIDATES = 2_048
    DEFAULT_MAX_FINDINGS = 1_024
    DEFAULT_MAX_PATH_CHARS = 4_096
    MAX_SUPPORTED_DEPTH = SafetyConfig.MAX_SUPPORTED_DEPTH
    # 兼容旧代码读取纯文本正则。带路径约束的规则不能降级为 dict[str, str]。
    DEFAULT_PATTERNS = {
        rule.name: rule.pattern for rule in DEFAULT_RULES if not rule.path_pattern
    }

    def __init__(
        self,
        custom_patterns: Mapping[str, str] | None = None,
        *,
        rules: Sequence[SensitiveRule] | None = None,
        rule_snapshot: RuleSetSnapshot | None = None,
        rule_overlay: SafetyRuleOverlay | None = None,
        rule_set_id: str | None = None,
        rule_set_version: str | None = None,
        rule_set_digest: str | None = None,
        policy: SafetyPolicy | None = None,
        auto_mask: bool = True,
        reject_on_detect: bool = False,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_field_chars: int = DEFAULT_MAX_FIELD_CHARS,
        max_scan_bytes: int = DEFAULT_MAX_SCAN_BYTES,
        max_scanned_fields: int = DEFAULT_MAX_SCANNED_FIELDS,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
        max_findings: int = DEFAULT_MAX_FINDINGS,
        max_path_chars: int = DEFAULT_MAX_PATH_CHARS,
    ):
        """
        参数:
            custom_patterns: 旧版 ``名称 -> 正则`` 配置；仅作迁移兼容。
            rules: 完整的结构化规则；未传入时使用 DEFAULT_RULES。
            rule_snapshot: 保留声明式规则、溯源和组件注册表的不可变快照。
            rule_overlay: 在基础快照之上追加的不可变用户规则快照。
            rule_set_id: 当前规则集的稳定 ID。
            rule_set_version: 当前规则集的稳定版本。
            policy: 默认决策策略。
            auto_mask: 旧版自动脱敏开关。
            reject_on_detect: 旧版全局拒绝开关；新代码应改用 policy。
            max_depth: payload/工具结果的最大递归深度。
            max_field_chars: 单个键或叶子允许扫描的最大 Unicode 字符数。
            max_scan_bytes: 一次事件扫描允许消费的 UTF-8 总字节数。
            max_scanned_fields: 一次事件允许处理的键与标量叶子数量。
            max_candidates: 语义校验前允许产生的正则候选数。
            max_findings: 报告允许保留的最终命中数。
            max_path_chars: 临时和报告 JSON Pointer 的最大字符数。
        """
        limits = {
            "max_depth": max_depth,
            "max_field_chars": max_field_chars,
            "max_scan_bytes": max_scan_bytes,
            "max_scanned_fields": max_scanned_fields,
            "max_candidates": max_candidates,
            "max_findings": max_findings,
            "max_path_chars": max_path_chars,
        }
        for limit_name, limit_value in limits.items():
            if type(limit_value) is not int or limit_value <= 0:
                raise ValueError(f"{limit_name} must be a positive integer")
        if max_depth > self.MAX_SUPPORTED_DEPTH:
            raise ValueError(f"max_depth must be <= {self.MAX_SUPPORTED_DEPTH}")
        self.max_depth = max_depth
        self.max_field_chars = max_field_chars
        self.max_scan_bytes = max_scan_bytes
        self.max_scanned_fields = max_scanned_fields
        self.max_candidates = max_candidates
        self.max_findings = max_findings
        self.max_path_chars = max_path_chars
        self._report_attestation_key = secrets.token_bytes(32)

        selected_snapshot = rule_snapshot
        if rule_overlay is not None and not isinstance(
            rule_overlay,
            SafetyRuleOverlay,
        ):
            raise ValueError("rule_overlay must be a SafetyRuleOverlay")
        if rule_overlay is not None and custom_patterns:
            raise ValueError("rule_overlay cannot be combined with custom_patterns")
        if (
            selected_snapshot is None
            and rules is None
            and not custom_patterns
            and rule_set_id in (None, self.DEFAULT_RULE_SET_ID)
            and rule_set_version in (None, _BUILTIN_RULE_SNAPSHOT.version)
        ):
            selected_snapshot = _BUILTIN_RULE_SNAPSHOT
        if selected_snapshot is not None:
            if custom_patterns:
                raise ValueError(
                    "custom_patterns cannot mutate an immutable rule snapshot"
                )
            if rules is not None and tuple(rules) != selected_snapshot.compiled_rules:
                raise ValueError("rules do not match the supplied rule snapshot")
            configured = list(selected_snapshot.compiled_rules)
        else:
            configured = list(self.DEFAULT_RULES if rules is None else rules)
        configured = [
            SensitiveRule.model_validate(
                rule.model_dump(mode="python")
                if isinstance(rule, SensitiveRule)
                else rule
            )
            for rule in configured
        ]
        rule_names = [rule.name for rule in configured]
        if len(rule_names) != len(set(rule_names)):
            raise ValueError("sensitive rule names must be unique")

        rule_by_name = {rule.name: rule for rule in configured}
        if custom_patterns:
            for name, pattern in custom_patterns.items():
                existing = rule_by_name.get(name)
                if existing is not None:
                    data = existing.model_dump(mode="python")
                    data["pattern"] = pattern
                    # 旧 custom_patterns 只表达整段正则，不承诺保留默认捕获组。
                    data["match_group"] = 0
                    rule_by_name[name] = SensitiveRule.model_validate(data)
                else:
                    rule_by_name[name] = SensitiveRule(
                        name=name,
                        pattern=pattern,
                        level=SensitiveLevel.HIGH,
                        action=SafetyAction.REVIEW,
                        reason_code="legacy.custom_pattern",
                        reason="Legacy custom pattern requires policy review.",
                        standard_source="Legacy SensitiveDetector.custom_patterns",
                    )

        base_rules = tuple(rule_by_name.values())
        if rule_overlay is not None:
            overlay_names = {rule.name for rule in rule_overlay.rules}
            name_collisions = overlay_names & set(rule_by_name)
            if name_collisions:
                raise ValueError("overlay rule names must not shadow base rules")
            rule_by_name.update({rule.name: rule for rule in rule_overlay.rules})
        self.base_rules = base_rules
        self.rule_overlay = rule_overlay
        self.rules = (*base_rules, *(rule_overlay.rules if rule_overlay else ()))
        self.patterns = {
            rule.name: rule.pattern for rule in self.rules if not rule.path_pattern
        }
        resolved_rule_set_id = (
            selected_snapshot.rule_set_id
            if rule_set_id is None and selected_snapshot is not None
            else (rule_set_id or self.DEFAULT_RULE_SET_ID)
        )
        resolved_rule_set_version = (
            selected_snapshot.version
            if rule_set_version is None and selected_snapshot is not None
            else (rule_set_version or _BUILTIN_RULE_SNAPSHOT.version)
        )
        if not resolved_rule_set_version:
            raise ValueError("rule_set_version must not be empty")
        if not resolved_rule_set_id:
            raise ValueError("rule_set_id must not be empty")
        if selected_snapshot is not None:
            if resolved_rule_set_id != selected_snapshot.rule_set_id:
                raise ValueError("rule_set_id does not match the supplied snapshot")
            if resolved_rule_set_version != selected_snapshot.version:
                raise ValueError(
                    "rule_set_version does not match the supplied snapshot"
                )
        self.rule_snapshot = selected_snapshot
        self.rule_set_id = resolved_rule_set_id
        self.rule_set_version = resolved_rule_set_version
        policy_source = SafetyPolicy() if policy is None else policy
        self.policy = SafetyPolicy.model_validate(
            policy_source.model_dump(mode="python")
            if isinstance(policy_source, SafetyPolicy)
            else policy_source
        )
        unknown_overrides = {
            override.rule_name for override in self.policy.rule_overrides
        } - set(rule_by_name)
        exception_rule_names = {
            rule_name
            for exception in self.policy.exceptions
            for rule_name in exception.scope.rule_names
        }
        unknown_policy_rules = unknown_overrides | (
            exception_rule_names - set(rule_by_name)
        )
        if unknown_policy_rules:
            unknown = ", ".join(sorted(unknown_policy_rules))
            raise ValueError(f"policy references unknown sensitive rules: {unknown}")
        ineligible_exception_rules = {
            rule_name
            for rule_name in exception_rule_names
            if (
                rule_by_name[rule_name].level is not SensitiveLevel.LOW
                or rule_by_name[rule_name].action is SafetyAction.REJECT
            )
        }
        if ineligible_exception_rules:
            ineligible = ", ".join(sorted(ineligible_exception_rules))
            raise ValueError(
                "ALLOW policy exceptions are limited to low-risk contextual "
                f"identifiers: {ineligible}"
            )
        self.auto_mask = auto_mask
        self.reject_on_detect = reject_on_detect
        if selected_snapshot is not None:
            if (
                rule_set_digest is not None
                and rule_set_digest != selected_snapshot.digest
            ):
                raise ValueError("rule_set_digest does not match the supplied snapshot")
            base_rule_set_digest = selected_snapshot.digest
        elif rule_set_digest is not None:
            if re.fullmatch(r"[0-9a-f]{64}", rule_set_digest) is None:
                raise ValueError("rule_set_digest must be a lowercase SHA-256")
            base_rule_set_digest = rule_set_digest
        else:
            base_rule_set_digest = canonical_sha256(
                {
                    "rule_set_id": self.rule_set_id,
                    "rule_set_version": self.rule_set_version,
                    "rules": [rule.model_dump(mode="json") for rule in self.base_rules],
                }
            )
        self.base_rule_set_digest = base_rule_set_digest
        if rule_overlay is None:
            self.rule_set_digest = base_rule_set_digest
        else:
            self.rule_set_digest = canonical_sha256(
                {
                    "domain": "memoryhub.safety_rule_overlay.v1",
                    "base_rule_set_digest": base_rule_set_digest,
                    "overlay_keyed_digest": rule_overlay.keyed_digest,
                }
            )
        overlay_scope_names = (
            frozenset(rule.name for rule in rule_overlay.rules)
            if rule_overlay is not None
            else frozenset()
        )
        mismatched_exception_digests = {
            exception.exception_id
            for exception in self.policy.exceptions
            if exception.rule_set_digest
            and exception.rule_set_digest != self.rule_set_digest
            and not (
                rule_overlay is not None
                and exception.rule_set_digest == self.base_rule_set_digest
                and overlay_scope_names.isdisjoint(exception.scope.rule_names)
            )
        }
        if mismatched_exception_digests:
            mismatched = ", ".join(sorted(mismatched_exception_digests))
            raise ValueError(
                "policy exception rule_set_digest does not match detector: "
                + mismatched
            )
        self.policy_digest = canonical_sha256(
            {
                "policy": self.policy.model_dump(mode="json"),
                "auto_mask": self.auto_mask,
                "reject_on_detect": self.reject_on_detect,
            }
        )
        (
            self._runtime_rules,
            self._component_registries,
            self._effective_rule_categories,
            self._effective_component_registry_digest,
        ) = self._build_runtime_rules(selected_snapshot, rule_overlay)

    def _build_runtime_rules(
        self,
        selected_snapshot: RuleSetSnapshot | None,
        rule_overlay: SafetyRuleOverlay | None,
    ) -> tuple[
        tuple[_RuntimeRule, ...],
        tuple[ComponentRegistry, ...],
        Mapping[tuple[str, str], str],
        str,
    ]:
        """统一完成正则编译，并把声明式 priority/validator 绑定到运行时计划。"""

        builtin_compiled = {
            (rule.name, rule.version): rule
            for rule in _BUILTIN_RULE_SNAPSHOT.compiled_rules
        }
        builtin_definitions = {
            (rule.rule_id, rule.rule_version): rule
            for rule in _BUILTIN_RULE_SNAPSHOT.rules
        }
        legacy_defaults = {
            (rule.name, rule.version): rule for rule in DEFAULT_SENSITIVE_RULES
        }
        trusted_path_patterns = {
            rule.path_pattern
            for rule in (
                *_BUILTIN_RULE_SNAPSHOT.compiled_rules,
                *DEFAULT_SENSITIVE_RULES,
            )
            if rule.path_pattern
        }
        selected_definitions = (
            {
                (rule.rule_id, rule.rule_version): rule
                for rule in selected_snapshot.rules
            }
            if selected_snapshot is not None
            else {}
        )

        registries: list[ComponentRegistry] = []
        runtime_rules: list[_RuntimeRule] = []
        category_by_rule: dict[tuple[str, str], str] = {}
        overlay_rule_names = (
            frozenset(rule.name for rule in rule_overlay.rules)
            if rule_overlay is not None
            else frozenset()
        )
        for ordinal, rule in enumerate(self.rules):
            if not rule.enabled:
                continue
            if len(rule.pattern) > 4_096:
                raise ValueError(
                    f"sensitive rule pattern exceeds 4096 characters: {rule.name}"
                )
            is_overlay = rule.name in overlay_rule_names
            is_legacy_default = (
                not is_overlay
                and legacy_defaults.get((rule.name, rule.version)) == rule
            )
            if is_overlay or not is_legacy_default:
                validate_regex_safety(rule.pattern)

            metadata_snapshot: RuleSetSnapshot | None = None
            definition = None
            if not is_overlay:
                definition = selected_definitions.get((rule.name, rule.version))
                if definition is not None:
                    metadata_snapshot = selected_snapshot
                else:
                    builtin_rule = builtin_compiled.get((rule.name, rule.version))
                    if builtin_rule == rule:
                        definition = builtin_definitions[(rule.name, rule.version)]
                        metadata_snapshot = _BUILTIN_RULE_SNAPSHOT

            if rule.path_pattern:
                if len(rule.path_pattern) > 4_096:
                    raise ValueError(
                        f"sensitive path pattern exceeds 4096 characters: {rule.name}"
                    )
                # 受信快照的路径来自受控 JSON Pointer glob 编译器；外部直接传入的
                # path_pattern 则必须通过和内容正则相同的回溯门禁。
                if is_overlay or (
                    metadata_snapshot is None
                    and not is_legacy_default
                    and rule.path_pattern not in trusted_path_patterns
                ):
                    validate_regex_safety(rule.path_pattern)
                path_pattern = re.compile(rule.path_pattern)
            else:
                path_pattern = None

            validator: Callable[[str], bool] | None = None
            if is_overlay:
                if rule_overlay is None:  # pragma: no cover - guarded above
                    raise AssertionError("overlay runtime rule is missing its snapshot")
                priority = rule_overlay.priorities[rule.name]
                maskable = bool(rule.replacement)
                category = rule_overlay.categories[rule.name]
            elif definition is not None and metadata_snapshot is not None:
                validator = metadata_snapshot.resolve_validator(definition)
                registry = metadata_snapshot.component_registry
                if all(existing is not registry for existing in registries):
                    registries.append(registry)
                priority = definition.priority
                maskable = definition.masker != "builtin.none@1.0"
                category = definition.category.value
            else:
                # 没有与可信快照逐字段一致的直接规则不能仅凭名称/版本继承
                # 内置优先级，否则可通过冒用 rule_id 压制真实高风险命中。
                priority = -ordinal
                maskable = bool(rule.replacement)
                category = "custom"

            runtime_rules.append(
                _RuntimeRule(
                    rule=rule,
                    content_pattern=re.compile(rule.pattern),
                    path_pattern=path_pattern,
                    validator=validator,
                    priority=priority,
                    ordinal=ordinal,
                    maskable=maskable,
                    is_overlay=is_overlay,
                    is_snapshot_rule=metadata_snapshot is not None,
                )
            )
            category_by_rule[(rule.name, rule.version)] = category

        base_priorities = [
            runtime_rule.priority
            for runtime_rule in runtime_rules
            if not runtime_rule.is_overlay
        ]
        if base_priorities:
            lowest_base_priority = min(base_priorities)
            if any(
                runtime_rule.is_overlay
                and runtime_rule.rule.action is SafetyAction.MASK
                and runtime_rule.priority >= lowest_base_priority
                for runtime_rule in runtime_rules
            ):
                raise ValueError(
                    "overlay MASK priorities must be lower than all base rules"
                )

        if selected_snapshot is not None:
            component_digest = selected_snapshot.component_registry_digest
        else:
            component_digest = canonical_sha256(
                {
                    "domain": "memoryhub.safety_audit.custom_components.v1",
                    "registry_digests": sorted(
                        {registry.digest for registry in registries}
                    ),
                }
            )
        return (
            tuple(runtime_rules),
            tuple(registries),
            MappingProxyType(category_by_rule),
            component_digest,
        )

    @property
    def effective_rule_categories(self) -> Mapping[tuple[str, str], str]:
        """Return immutable audit categories for the detector's effective plan."""

        return self._effective_rule_categories

    @property
    def effective_component_registry_digest(self) -> str:
        """Return the component digest bound to the detector's effective plan."""

        return self._effective_component_registry_digest

    @classmethod
    def from_config(cls, config: SafetyConfig) -> "SensitiveDetector":
        """按 SafetyConfig 构造检测器，确保旧开关也被显式传入。"""
        return cls(
            rules=config.rules,
            rule_snapshot=config.rule_snapshot,
            rule_set_id=config.rule_set_id,
            rule_set_version=config.rule_set_version,
            rule_set_digest=config.rule_set_digest,
            policy=config.policy,
            auto_mask=config.auto_mask,
            reject_on_detect=config.reject_on_detect,
            max_depth=config.max_depth,
            max_field_chars=config.max_field_chars,
            max_scan_bytes=config.max_scan_bytes,
            max_scanned_fields=config.max_scanned_fields,
            max_candidates=config.max_candidates,
            max_findings=config.max_findings,
            max_path_chars=config.max_path_chars,
        )

    # ------------------------------------------------------------------
    # 新的原子安全处理契约
    # ------------------------------------------------------------------

    def _capture_scan_plan(self) -> _ScanPlan:
        """固定一次请求使用的规则快照和预算，供初扫与复检共同消费。"""

        return _ScanPlan(
            runtime_rules=self._runtime_rules,
            component_registries=self._component_registries,
            rule_set_version=self.rule_set_version,
            rule_set_digest=self.rule_set_digest,
            base_rule_set_digest=self.base_rule_set_digest,
            max_depth=self.max_depth,
            max_field_chars=self.max_field_chars,
            max_scan_bytes=self.max_scan_bytes,
            max_scanned_fields=self.max_scanned_fields,
            max_candidates=self.max_candidates,
            max_findings=self.max_findings,
            max_path_chars=self.max_path_chars,
            report_attestation_key=self._report_attestation_key,
        )

    def _new_scan_state(self, plan: _ScanPlan | None = None) -> _ScanState:
        selected = plan or self._capture_scan_plan()
        return _ScanState(
            max_depth=selected.max_depth,
            max_field_chars=selected.max_field_chars,
            max_scan_bytes=selected.max_scan_bytes,
            max_scanned_fields=selected.max_scanned_fields,
            max_candidates=selected.max_candidates,
            max_findings=selected.max_findings,
            max_path_chars=selected.max_path_chars,
        )

    def _verify_component_registries(
        self,
        registries: tuple[ComponentRegistry, ...],
    ) -> None:
        """一次扫描开始时各验证一次，候选循环内不再读取组件源码。"""

        for registry in registries:
            registry.verify_integrity()

    @staticmethod
    def _raise_scan_error(code: str) -> NoReturn:
        raise SafetyScanError(code)

    def _preflight_text(self, value: str, state: _ScanState) -> _NormalizedText:
        """在复制/序列化事件前执行有界检查，避免预算被前置操作绕过。"""

        if state.scanned_field_count >= state.max_scanned_fields:
            self._raise_scan_error("scan.limit.max_fields")
        state.scanned_field_count += 1
        if len(value) > state.max_field_chars:
            self._raise_scan_error("scan.limit.max_field_chars")
        try:
            encoded_size = len(value.encode("utf-8"))
        except UnicodeError:
            self._raise_scan_error("scan.invalid_unicode")
        if state.scanned_bytes + encoded_size > state.max_scan_bytes:
            self._raise_scan_error("scan.limit.max_total_bytes")
        state.scanned_bytes += encoded_size
        view = _normalized_text(value)
        if len(view.text) > state.max_field_chars:
            self._raise_scan_error("scan.limit.max_normalized_chars")
        return view

    def _preflight_value(
        self,
        value: Any,
        *,
        field_path: str,
        normalized_path: str,
        depth: int,
        state: _ScanState,
    ) -> Any:
        """在既定结构预算内复制 JSON-like 值；不执行任何内容规则。"""

        root: list[Any] = [None]
        stack: list[
            tuple[
                Any,
                str,
                str,
                int,
                frozenset[int],
                Any,
                str | int,
            ]
        ] = [
            (
                value,
                field_path,
                normalized_path,
                depth,
                frozenset(),
                root,
                0,
            )
        ]
        while stack:
            (
                current,
                current_path,
                current_normalized_path,
                current_depth,
                ancestors,
                parent,
                slot,
            ) = stack.pop()
            if current_depth > state.max_depth:
                self._raise_scan_error("scan.limit.max_depth")
            if state.visited_nodes >= state.max_scanned_fields:
                self._raise_scan_error("scan.limit.max_nodes")
            state.visited_nodes += 1
            if (
                len(current_path) > state.max_path_chars
                or len(current_normalized_path) > state.max_path_chars
            ):
                self._raise_scan_error("scan.limit.max_path_chars")

            if isinstance(current, str):
                self._preflight_text(current, state)
                parent[slot] = current
                continue
            scalar = _json_scalar(current)
            if scalar is not None:
                self._preflight_text(scalar, state)
                parent[slot] = current
                continue

            is_mapping = isinstance(current, Mapping)
            is_sequence = isinstance(current, Sequence) and not isinstance(
                current,
                (str, bytes, bytearray),
            )
            if not is_mapping and not is_sequence:
                self._raise_scan_error("scan.unsupported_value_type")

            container_id = id(current)
            if container_id in ancestors:
                self._raise_scan_error("scan.recursive_reference")
            next_ancestors = ancestors | {container_id}

            if is_mapping:
                mapping = current
                try:
                    mapping_size = len(mapping)
                except Exception:
                    self._raise_scan_error("scan.unsupported_mapping")
                remaining_nodes = state.max_scanned_fields - state.visited_nodes
                if mapping_size > remaining_nodes:
                    self._raise_scan_error("scan.limit.max_nodes")
                try:
                    raw_items = list(islice(mapping.items(), mapping_size + 1))
                except Exception:
                    self._raise_scan_error("scan.unsupported_mapping")
                if len(raw_items) != mapping_size:
                    self._raise_scan_error("scan.unstable_mapping")

                copied_mapping: dict[str, Any] = {}
                parent[slot] = copied_mapping
                children: list[tuple[str, str, str, str, Any]] = []
                for key, _ in raw_items:
                    if not isinstance(key, str):
                        self._raise_scan_error("scan.unsupported_key_type")
                raw_items.sort(key=lambda item: item[0])
                for key, child in raw_items:
                    key_view = self._preflight_text(key, state)
                    raw_segment = _escape_pointer_segment(key)
                    normalized_segment = _escape_pointer_segment(key_view.text)
                    child_path = current_path + "/" + raw_segment
                    child_normalized_path = (
                        current_normalized_path + "/" + normalized_segment
                    )
                    if (
                        len(child_path) > state.max_path_chars
                        or len(child_normalized_path) > state.max_path_chars
                    ):
                        self._raise_scan_error("scan.limit.max_path_chars")
                    children.append(
                        (
                            key_view.text,
                            key,
                            child_path,
                            child_normalized_path,
                            child,
                        )
                    )
                for (
                    _,
                    key,
                    child_path,
                    child_normalized_path,
                    child,
                ) in reversed(sorted(children)):
                    stack.append(
                        (
                            child,
                            child_path,
                            child_normalized_path,
                            current_depth + 1,
                            next_ancestors,
                            copied_mapping,
                            key,
                        )
                    )
                continue

            sequence = current
            try:
                sequence_size = len(sequence)
            except (TypeError, ValueError, OverflowError):
                self._raise_scan_error("scan.unsupported_sequence")
            remaining_nodes = state.max_scanned_fields - state.visited_nodes
            if sequence_size > remaining_nodes:
                self._raise_scan_error("scan.limit.max_nodes")
            try:
                captured_children = [sequence[index] for index in range(sequence_size)]
                if len(sequence) != sequence_size:
                    self._raise_scan_error("scan.unstable_sequence")
            except SafetyScanError:
                raise
            except Exception:
                self._raise_scan_error("scan.unstable_sequence")
            copied_sequence: list[Any] = [None] * sequence_size
            parent[slot] = copied_sequence
            for index in range(sequence_size - 1, -1, -1):
                segment = str(index)
                stack.append(
                    (
                        captured_children[index],
                        current_path + "/" + segment,
                        current_normalized_path + "/" + segment,
                        current_depth + 1,
                        next_ancestors,
                        copied_sequence,
                        index,
                    )
                )
        return root[0]

    def _preflight_event(
        self,
        event: MemoryEvent,
        state: _ScanState,
    ) -> MemoryEvent:
        """建立后续摘要和规则遍历共用的有界快照，消除预检后的可变对象竞态。"""

        metadata_bytes = 0
        metadata_fields = 0

        def metadata_text(value: Any) -> str:
            nonlocal metadata_bytes, metadata_fields
            if not isinstance(value, str):
                self._raise_scan_error("scan.snapshot_invalid")
            metadata_fields += 1
            if metadata_fields > state.max_scanned_fields:
                self._raise_scan_error("scan.limit.max_fields")
            if len(value) > state.max_field_chars:
                self._raise_scan_error("scan.limit.max_field_chars")
            try:
                metadata_bytes += len(value.encode("utf-8"))
            except UnicodeError:
                self._raise_scan_error("scan.invalid_unicode")
            if metadata_bytes > state.max_scan_bytes:
                self._raise_scan_error("scan.limit.max_total_bytes")
            return value

        text_snapshot = self._preflight_value(
            event.text,
            field_path="/text",
            normalized_path="/text",
            depth=0,
            state=state,
        )
        payload_snapshot = self._preflight_value(
            event.payload,
            field_path="/payload",
            normalized_path="/payload",
            depth=0,
            state=state,
        )

        try:
            tool_calls_source = event.tool_calls
            tool_call_count = len(tool_calls_source)
            if tool_call_count > state.max_scanned_fields:
                self._raise_scan_error("scan.limit.max_nodes")
            tool_calls = [tool_calls_source[index] for index in range(tool_call_count)]
            if len(tool_calls_source) != tool_call_count:
                self._raise_scan_error("scan.unstable_sequence")
        except SafetyScanError:
            raise
        except Exception:
            self._raise_scan_error("scan.snapshot_invalid")

        tool_call_snapshots: list[dict[str, Any]] = []
        for index, tool_call in enumerate(tool_calls):
            prefix = f"/tool_calls/{index}"
            arguments_snapshot = self._preflight_value(
                tool_call.arguments,
                field_path=prefix + "/arguments",
                normalized_path=prefix + "/arguments",
                depth=0,
                state=state,
            )
            result_snapshot = self._preflight_value(
                tool_call.result,
                field_path=prefix + "/result",
                normalized_path=prefix + "/result",
                depth=0,
                state=state,
            )
            error_snapshot = self._preflight_value(
                tool_call.error,
                field_path=prefix + "/error",
                normalized_path=prefix + "/error",
                depth=0,
                state=state,
            )
            tool_call_snapshots.append(
                {
                    "call_id": metadata_text(tool_call.call_id),
                    "tool_name": metadata_text(tool_call.tool_name),
                    "arguments": arguments_snapshot,
                    "result": result_snapshot,
                    "status": tool_call.status,
                    "sequence": tool_call.sequence,
                    "error": error_snapshot,
                }
            )

        snapshot_failed = False
        try:
            redactions_source = event.redactions
            redaction_count = len(redactions_source)
            if redaction_count > state.max_scanned_fields:
                self._raise_scan_error("scan.limit.max_fields")
            redactions = [
                metadata_text(redactions_source[index])
                for index in range(redaction_count)
            ]
            if len(redactions_source) != redaction_count:
                self._raise_scan_error("scan.unstable_sequence")

            quality = event.quality
            quality_issues_source = quality.issues
            quality_issue_count = len(quality_issues_source)
            if quality_issue_count > state.max_scanned_fields:
                self._raise_scan_error("scan.limit.max_fields")
            quality_issues = [
                metadata_text(quality_issues_source[index])
                for index in range(quality_issue_count)
            ]
            if len(quality_issues_source) != quality_issue_count:
                self._raise_scan_error("scan.unstable_sequence")

            snapshot_data = {
                "event_id": metadata_text(event.event_id),
                "source_type": event.source_type,
                "event_type": metadata_text(event.event_type),
                "user_id": metadata_text(event.user_id),
                "session_id": metadata_text(event.session_id),
                "turn_id": metadata_text(event.turn_id),
                "scene": metadata_text(event.scene),
                "task_type": metadata_text(event.task_type),
                "occurred_at": metadata_text(event.occurred_at),
                "text": text_snapshot,
                "payload": payload_snapshot,
                "tool_calls": tool_call_snapshots,
                "schema_version": event.schema_version,
                "source_hash": metadata_text(event.source_hash),
                "redactions": redactions,
                "quality": {
                    "score": quality.score,
                    "status": quality.status,
                    "completeness": quality.completeness,
                    "validity": quality.validity,
                    "consistency": quality.consistency,
                    "freshness": quality.freshness,
                    "issues": quality_issues,
                },
            }
            return MemoryEvent.model_validate(snapshot_data)
        except SafetyScanError:
            raise
        except (AttributeError, TypeError, ValueError, RecursionError):
            snapshot_failed = True
        if snapshot_failed:
            raise SafetyScanError("scan.snapshot_failed")
        raise AssertionError("unreachable snapshot state")

    def _prepare_text(
        self,
        value: str,
        state: _ScanState,
    ) -> tuple[_NormalizedText, bool] | None:
        """消费字段/字节预算并建立规范化视图；bool 表示是否扫描了完整原文。"""

        if state.scanned_field_count >= state.max_scanned_fields:
            state.add_issue("scan.limit.max_fields")
            state.stop = True
            return None
        state.scanned_field_count += 1

        complete = True
        bounded = value
        if len(bounded) > state.max_field_chars:
            bounded = bounded[: state.max_field_chars]
            state.add_issue("scan.limit.max_field_chars")
            complete = False

        encoded = bounded.encode("utf-8")
        remaining_bytes = state.max_scan_bytes - state.scanned_bytes
        if len(encoded) > remaining_bytes:
            bounded = _utf8_prefix(bounded, remaining_bytes)
            encoded = bounded.encode("utf-8")
            state.add_issue("scan.limit.max_total_bytes")
            state.stop = True
            complete = False
        state.scanned_bytes += len(encoded)

        view = _normalized_text(bounded)
        if len(view.text) > state.max_field_chars:
            view = _NormalizedText(
                view.text[: state.max_field_chars],
                view.origins[: state.max_field_chars],
            )
            state.add_issue("scan.limit.max_normalized_chars")
            complete = False
        return view, complete

    def _scan_view(
        self,
        view: _NormalizedText,
        *,
        field_path: str,
        normalized_path: str,
        target: SafetyFindingTarget,
        runtime_rules: tuple[_RuntimeRule, ...],
        state: _ScanState,
        path_rules_only: bool = False,
        unscoped_rules_only: bool = False,
        ignore_overlay_mask_in_markers: bool = False,
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        redaction_marker_spans = (
            tuple(
                (match.start(), match.end())
                for match in _REDACTION_MARKER_SPAN_RE.finditer(view.text)
            )
            if ignore_overlay_mask_in_markers
            else ()
        )
        for runtime_rule in runtime_rules:
            if state.stop and state.candidate_count >= state.max_candidates:
                break
            if path_rules_only and runtime_rule.path_pattern is None:
                continue
            if unscoped_rules_only and runtime_rule.path_pattern is not None:
                continue
            if (
                runtime_rule.path_pattern is not None
                and runtime_rule.path_pattern.search(normalized_path) is None
            ):
                continue

            for match in runtime_rule.content_pattern.finditer(view.text):
                if state.candidate_count >= state.max_candidates:
                    state.add_issue("scan.limit.max_candidates")
                    state.stop = True
                    break
                state.candidate_count += 1

                try:
                    normalized_start, normalized_end = match.span(
                        runtime_rule.rule.match_group
                    )
                except (IndexError, KeyError):
                    state.add_issue("scan.rule.invalid_match_group")
                    continue
                if normalized_start < 0 or normalized_end <= normalized_start:
                    continue
                if (
                    runtime_rule.is_overlay
                    and runtime_rule.rule.action is SafetyAction.MASK
                    and any(
                        marker_start <= normalized_start
                        and normalized_end <= marker_end
                        for marker_start, marker_end in redaction_marker_spans
                    )
                ):
                    continue
                candidate_value = match.group(runtime_rule.rule.match_group)
                if not isinstance(candidate_value, str):
                    state.add_issue("scan.rule.invalid_candidate")
                    continue
                if runtime_rule.validator is not None:
                    try:
                        if not runtime_rule.validator(candidate_value):
                            continue
                    except Exception:
                        state.add_issue(
                            f"scan.validator_error.{runtime_rule.rule.name}"
                        )
                        continue

                if target is SafetyFindingTarget.TEXT_SPAN:
                    try:
                        start, end = view.original_span(
                            normalized_start,
                            normalized_end,
                        )
                    except ValueError:
                        state.add_issue("scan.normalization.invalid_span")
                        continue
                else:
                    start = end = 0
                candidates.append(
                    _Candidate(
                        runtime_rule=runtime_rule,
                        field_path=field_path,
                        target=target,
                        start=start,
                        end=end,
                    )
                )
            if state.stop and state.candidate_count >= state.max_candidates:
                break
        return candidates

    @staticmethod
    def _candidate_rank(candidate: _Candidate) -> tuple[Any, ...]:
        rule = candidate.runtime_rule.rule
        return (
            -candidate.runtime_rule.priority,
            -candidate.span_length,
            -_ACTION_RANK[rule.action],
            candidate.field_path,
            candidate.start,
            candidate.end,
            rule.name,
            rule.version,
            candidate.runtime_rule.ordinal,
        )

    @classmethod
    def _candidates_conflict(cls, left: _Candidate, right: _Candidate) -> bool:
        if (
            left.target is SafetyFindingTarget.WHOLE_VALUE
            or right.target is SafetyFindingTarget.WHOLE_VALUE
        ):
            # 不同路径代表不同风险事实。祖先 whole_value 与后代 Finding
            # 同时保留，使低优先级/低动作的整值规则不能吞掉更严格的后代；
            # 未来 sanitize() 可在真正替换时按路径深度消除冗余操作。
            return left.field_path == right.field_path
        return (
            left.field_path == right.field_path
            and left.start < right.end
            and right.start < left.end
        )

    def _resolve_candidates(
        self,
        candidates: list[_Candidate],
        state: _ScanState,
    ) -> tuple[SafetyFinding, ...]:
        """
        确定性消解命中。

        同一值内按 priority → 最长匹配 → 动作严格度排序。整值命中与后代
        路径是不同风险事实，均予保留；这样低优先级 ALLOW 整值规则不能吞掉
        高优先级 REJECT 后代，未来 sanitize() 再按路径深度消除替换冗余。
        """

        unique: dict[tuple[Any, ...], _Candidate] = {}
        for candidate in candidates:
            rule = candidate.runtime_rule.rule
            key = (
                candidate.field_path,
                candidate.target,
                candidate.start,
                candidate.end,
                rule.name,
                rule.version,
            )
            unique.setdefault(key, candidate)

        unique_candidates = tuple(unique.values())

        whole_by_path: dict[str, _Candidate] = {}
        for candidate in unique_candidates:
            if candidate.target is not SafetyFindingTarget.WHOLE_VALUE:
                continue
            existing = whole_by_path.get(candidate.field_path)
            if existing is None or self._candidate_rank(
                candidate
            ) < self._candidate_rank(existing):
                whole_by_path[candidate.field_path] = candidate

        selected: list[_Candidate] = list(whole_by_path.values())
        text_candidates = (
            candidate
            for candidate in unique_candidates
            if candidate.target is SafetyFindingTarget.TEXT_SPAN
        )
        for candidate in sorted(text_candidates, key=self._candidate_rank):
            if any(
                self._candidates_conflict(candidate, existing) for existing in selected
            ):
                continue
            selected.append(candidate)

        selected.sort(key=self._candidate_rank)
        if len(selected) > state.max_findings:
            selected = selected[: state.max_findings]
            state.add_issue("scan.limit.max_findings")

        selected.sort(
            key=lambda candidate: (
                candidate.field_path,
                candidate.start,
                candidate.end,
                -candidate.runtime_rule.priority,
                candidate.runtime_rule.rule.name,
                candidate.runtime_rule.rule.version,
                candidate.target.value,
            )
        )
        findings: list[SafetyFinding] = []
        for candidate in selected:
            rule = candidate.runtime_rule.rule
            finding_key = {
                "field_path": candidate.field_path,
                "target": candidate.target.value,
                "start": candidate.start,
                "end": candidate.end,
                "rule_name": rule.name,
                "rule_version": rule.version,
            }
            findings.append(
                SafetyFinding(
                    finding_id=f"finding_{canonical_sha256(finding_key)[:12]}",
                    rule_name=rule.name,
                    rule_version=rule.version,
                    level=rule.level,
                    suggested_action=rule.action,
                    field_path=candidate.field_path,
                    target=candidate.target,
                    start=candidate.start,
                    end=candidate.end,
                    replacement=rule.replacement,
                    maskable=candidate.runtime_rule.maskable,
                    reason_code=rule.reason_code,
                    reason=rule.reason,
                    standard_source=rule.standard_source,
                )
            )
        return tuple(findings)

    def _traverse_value(
        self,
        value: Any,
        *,
        field_path: str,
        normalized_path: str,
        depth: int,
        runtime_rules: tuple[_RuntimeRule, ...],
        state: _ScanState,
        candidates: list[_Candidate],
        ignore_overlay_mask_in_markers: bool,
    ) -> None:
        """以显式栈递归遍历 JSON-like 值，避免 Python 调用栈被深输入耗尽。"""

        stack: list[tuple[Any, str, str, int, frozenset[int]]] = [
            (value, field_path, normalized_path, depth, frozenset())
        ]
        while stack and not state.stop:
            current, current_path, current_normalized_path, current_depth, ancestors = (
                stack.pop()
            )
            if current_depth > state.max_depth:
                state.add_issue("scan.limit.max_depth")
                continue
            if state.visited_nodes >= state.max_scanned_fields:
                state.add_issue("scan.limit.max_nodes")
                state.stop = True
                break
            state.visited_nodes += 1
            if (
                len(current_path) > state.max_path_chars
                or len(current_normalized_path) > state.max_path_chars
            ):
                state.add_issue("scan.limit.max_path_chars")
                continue

            if isinstance(current, str):
                prepared = self._prepare_text(current, state)
                if prepared is None:
                    continue
                view, _ = prepared
                candidates.extend(
                    self._scan_view(
                        view,
                        field_path=current_path,
                        normalized_path=current_normalized_path,
                        target=SafetyFindingTarget.TEXT_SPAN,
                        runtime_rules=runtime_rules,
                        state=state,
                        ignore_overlay_mask_in_markers=(ignore_overlay_mask_in_markers),
                    )
                )
                continue

            scalar = _json_scalar(current)
            if scalar is not None:
                prepared = self._prepare_text(scalar, state)
                if prepared is None:
                    continue
                view, _ = prepared
                candidates.extend(
                    self._scan_view(
                        view,
                        field_path=current_path,
                        normalized_path=current_normalized_path,
                        target=SafetyFindingTarget.WHOLE_VALUE,
                        runtime_rules=runtime_rules,
                        state=state,
                        ignore_overlay_mask_in_markers=(ignore_overlay_mask_in_markers),
                    )
                )
                continue

            is_mapping = isinstance(current, Mapping)
            is_sequence = isinstance(current, Sequence) and not isinstance(
                current,
                (str, bytes, bytearray),
            )
            if not is_mapping and not is_sequence:
                state.add_issue("scan.unsupported_value_type")
                continue

            container_id = id(current)
            if container_id in ancestors:
                state.add_issue("scan.recursive_reference")
                continue
            next_ancestors = ancestors | {container_id}

            # 非字符串容器若落在 password/token/secret 等路径上，产生明确的
            # whole_value Finding；不把虚构 JSON span 冒充原始字符串区间。
            container_marker = "{}" if is_mapping else "[]"
            candidates.extend(
                self._scan_view(
                    _normalized_text(container_marker),
                    field_path=current_path,
                    normalized_path=current_normalized_path,
                    target=SafetyFindingTarget.WHOLE_VALUE,
                    runtime_rules=runtime_rules,
                    state=state,
                    path_rules_only=True,
                    ignore_overlay_mask_in_markers=ignore_overlay_mask_in_markers,
                )
            )
            if state.stop:
                continue

            if is_mapping:
                mapping = current
                try:
                    mapping_size = len(mapping)
                except Exception:
                    state.add_issue("scan.unsupported_mapping")
                    continue
                remaining_nodes = state.max_scanned_fields - state.visited_nodes
                if mapping_size > remaining_nodes:
                    state.add_issue("scan.limit.max_nodes")
                    state.stop = True
                    continue
                try:
                    raw_items = list(islice(mapping.items(), mapping_size + 1))
                except Exception:
                    state.add_issue("scan.unsupported_mapping")
                    continue
                if len(raw_items) != mapping_size:
                    state.add_issue("scan.unstable_mapping")
                    continue

                children: list[tuple[str, str, str, Any]] = []
                if any(not isinstance(key, str) for key, _ in raw_items):
                    state.add_issue("scan.unsupported_key_type")
                    continue
                raw_items.sort(key=lambda item: item[0])
                for key, child in raw_items:
                    if state.stop:
                        break
                    if not isinstance(key, str):
                        state.add_issue("scan.unsupported_key_type")
                        continue
                    prepared_key = self._prepare_text(key, state)
                    if prepared_key is None:
                        break
                    key_view, key_complete = prepared_key
                    if not key_complete:
                        # 截断键无法构造可信路径；整条分支失败关闭。
                        continue
                    raw_segment = _escape_pointer_segment(key)
                    normalized_segment = _escape_pointer_segment(key_view.text)
                    child_path = current_path + "/" + raw_segment
                    child_normalized_path = (
                        current_normalized_path + "/" + normalized_segment
                    )
                    if (
                        len(child_path) > state.max_path_chars
                        or len(child_normalized_path) > state.max_path_chars
                    ):
                        state.add_issue("scan.limit.max_path_chars")
                        continue
                    key_candidates = self._scan_view(
                        key_view,
                        field_path=child_path,
                        normalized_path=child_normalized_path,
                        target=SafetyFindingTarget.TEXT_SPAN,
                        runtime_rules=runtime_rules,
                        state=state,
                        unscoped_rules_only=True,
                        ignore_overlay_mask_in_markers=(ignore_overlay_mask_in_markers),
                    )
                    if key_candidates:
                        # 现有 JSON Pointer 定位成员值，无法安全表达“键名片段”
                        # 且把原键写入 Finding/field_path 会污染后续审计；因此
                        # 标记不完整并跳过整条分支，交给未来 process() 失败关闭。
                        state.add_issue("scan.sensitive_member_name")
                        continue
                    children.append(
                        (
                            key_view.text,
                            key,
                            child_path,
                            (child_normalized_path, child),
                        )
                    )
                for _, _, child_path, child_data in reversed(sorted(children)):
                    child_normalized_path, child = child_data
                    stack.append(
                        (
                            child,
                            child_path,
                            child_normalized_path,
                            current_depth + 1,
                            next_ancestors,
                        )
                    )
                continue

            sequence = current
            try:
                sequence_size = len(sequence)
            except (TypeError, OverflowError):
                state.add_issue("scan.unsupported_sequence")
                continue
            remaining_nodes = state.max_scanned_fields - state.visited_nodes
            if sequence_size > remaining_nodes:
                state.add_issue("scan.limit.max_nodes")
                state.stop = True
                continue
            for index in range(sequence_size - 1, -1, -1):
                segment = str(index)
                stack.append(
                    (
                        sequence[index],
                        current_path + "/" + segment,
                        current_normalized_path + "/" + segment,
                        current_depth + 1,
                        next_ancestors,
                    )
                )

    def _scan_with_snapshot(
        self,
        event: MemoryEvent,
        plan: _ScanPlan,
        *,
        verification: bool = False,
    ) -> tuple[MemoryEvent, SafetyReport]:
        """在显式计划下建立有界事件快照并扫描，供初扫和复检复用。"""

        # MemoryEvent 的 Any 节点仍可在模型创建后被调用方原地修改。必须先用
        # 显式栈验证结构预算和循环引用，再执行 Pydantic 深拷贝与规范化摘要；
        # 否则深输入或超大工具结果会在扫描预算生效前耗尽资源。
        preflight_state = self._new_scan_state(plan)
        preflight_error = ""
        try:
            event_snapshot = self._preflight_event(event, preflight_state)
        except SafetyScanError as exc:
            preflight_error = exc.code
        except Exception:
            preflight_error = "scan.snapshot_failed"
        if preflight_error:
            # 在 except 块外重建公开异常，确保 __cause__/__context__ 也不会
            # 保留 Pydantic 或自定义容器可能携带的敏感 input_value。
            raise SafetyScanError(preflight_error)
        self._verify_component_registries(plan.component_registries)

        # 后续摘要和规则遍历都消费上面的同一份有界快照。
        snapshot_failed = False
        try:
            event_payload = event_snapshot.model_dump(mode="json")
            event_digest = canonical_sha256(event_payload)
        except Exception:
            snapshot_failed = True
        if snapshot_failed:
            raise SafetyScanError("scan.snapshot_failed")

        state = self._new_scan_state(plan)
        candidates: list[_Candidate] = []

        def scan_scalar(value: str, field_path: str) -> None:
            self._traverse_value(
                value,
                field_path=field_path,
                normalized_path=field_path,
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )

        report_metadata = (
            ("/event_id", event_snapshot.event_id),
            ("/event_type", event_snapshot.event_type),
            ("/scene", event_snapshot.scene),
            ("/task_type", event_snapshot.task_type),
        )
        protect_all_report_metadata = False
        for field_path, value in report_metadata:
            if state.stop:
                protect_all_report_metadata = True
                break
            issue_count = len(state.issues)
            scan_scalar(value, field_path)
            if state.stop or len(state.issues) != issue_count:
                protect_all_report_metadata = True
                break
        protected_report_paths = {
            candidate.field_path
            for candidate in candidates
            if candidate.field_path in _REPORT_METADATA_MARKERS
        }

        if not state.stop:
            self._traverse_value(
                event_snapshot.text,
                field_path="/text",
                normalized_path="/text",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )
        if not state.stop:
            self._traverse_value(
                event_snapshot.payload,
                field_path="/payload",
                normalized_path="/payload",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )
        for index, tool_call in enumerate(event_snapshot.tool_calls):
            if state.stop:
                break
            prefix = f"/tool_calls/{index}"
            self._traverse_value(
                tool_call.arguments,
                field_path=prefix + "/arguments",
                normalized_path=prefix + "/arguments",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )
            if state.stop:
                break
            self._traverse_value(
                tool_call.result,
                field_path=prefix + "/result",
                normalized_path=prefix + "/result",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )
            if state.stop:
                break
            self._traverse_value(
                tool_call.error,
                field_path=prefix + "/error",
                normalized_path=prefix + "/error",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )
            if state.stop:
                break
            scan_scalar(tool_call.call_id, prefix + "/call_id")
            if state.stop:
                break
            scan_scalar(tool_call.tool_name, prefix + "/tool_name")
            if state.stop:
                break
            self._traverse_value(
                tool_call.sequence,
                field_path=prefix + "/sequence",
                normalized_path=prefix + "/sequence",
                depth=0,
                runtime_rules=plan.runtime_rules,
                state=state,
                candidates=candidates,
                ignore_overlay_mask_in_markers=verification,
            )

        remaining_root_metadata = (
            ("/user_id", event_snapshot.user_id),
            ("/session_id", event_snapshot.session_id),
            ("/turn_id", event_snapshot.turn_id),
        )
        for field_path, value in remaining_root_metadata:
            if state.stop:
                break
            scan_scalar(value, field_path)
        for index, value in enumerate(event_snapshot.redactions):
            if state.stop:
                break
            scan_scalar(value, f"/redactions/{index}")
        for index, value in enumerate(event_snapshot.quality.issues):
            if state.stop:
                break
            scan_scalar(value, f"/quality/issues/{index}")

        findings = self._resolve_candidates(candidates, state)
        highest_level = SensitiveLevel.NONE
        if findings:
            highest_level = max(
                (finding.level for finding in findings),
                key=lambda level: _LEVEL_RANK[level],
            )
        if protect_all_report_metadata:
            protected_report_paths = set(_REPORT_METADATA_MARKERS)
        protected_report_paths.update(
            finding.field_path
            for finding in findings
            if finding.field_path in _REPORT_METADATA_MARKERS
        )

        def report_metadata_value(field_path: str, value: str) -> str:
            if field_path in protected_report_paths:
                return _REPORT_METADATA_MARKERS[field_path]
            return value

        report = SafetyReport(
            event_id=report_metadata_value("/event_id", event_snapshot.event_id),
            event_digest=event_digest,
            source_hash=event_snapshot.source_hash,
            rule_set_version=plan.rule_set_version,
            rule_set_digest=plan.rule_set_digest,
            context=SafetyDecisionContext(
                source_type=event_snapshot.source_type,
                event_type=report_metadata_value(
                    "/event_type",
                    event_snapshot.event_type,
                ),
                scene=report_metadata_value("/scene", event_snapshot.scene),
                task_type=report_metadata_value(
                    "/task_type",
                    event_snapshot.task_type,
                ),
            ),
            findings=findings,
            highest_level=highest_level,
            scanned_field_count=state.scanned_field_count,
            scan_complete=not state.issues,
            issues=tuple(state.issues),
        )
        report = report.model_copy(
            update={
                "attestation": self._report_attestation_for(
                    report,
                    plan.report_attestation_key,
                )
            }
        )
        return event_snapshot, report

    def scan(self, event: MemoryEvent) -> SafetyReport:
        """
        递归扫描 MemoryEvent，返回结构化且可复用的 SafetyReport。

        覆盖 text、payload、工具调用内容与标识，以及会持久化的事件字符串元数据；
        嵌套键参与路径匹配，字符串保留原文 span，路径规则命中的非字符串节点
        产生 whole_value Finding。扫描开始时捕获一次规则快照，并在报告中记录
        版本和摘要。
        """
        _, report = self._scan_with_snapshot(event, self._capture_scan_plan())
        return report

    def decide(
        self,
        report: SafetyReport,
        policy: SafetyPolicy | None = None,
    ) -> SafetyDecision:
        """
        仅消费 SafetyReport 进行策略决策，不得重新扫描事件。

        level 只表示风险；最终动作由规则建议动作、policy 覆盖和失败策略共同
        决定，不得硬编码为 ``HIGH -> REJECT``。兼容开关只允许收紧：
        reject_on_detect=True 强制拒绝，关闭自动脱敏时 MASK 必须升级为 REVIEW。
        """
        selected_policy_source = self.policy if policy is None else policy
        try:
            report_payload = (
                report.model_dump(mode="python")
                if isinstance(report, SafetyReport)
                else report
            )
            trusted_report = SafetyReport.model_validate(report_payload)
        except Exception:
            raise SafetyDecisionError("decide.invalid_report") from None
        try:
            policy_payload = (
                selected_policy_source.model_dump(mode="python")
                if isinstance(selected_policy_source, SafetyPolicy)
                else selected_policy_source
            )
            selected_policy = SafetyPolicy.model_validate(policy_payload)
        except Exception:
            raise SafetyDecisionError("decide.invalid_policy") from None
        plan = self._capture_scan_plan()
        try:
            return self._decide_with_snapshot(
                trusted_report,
                selected_policy,
                auto_mask=self.auto_mask,
                reject_on_detect=self.reject_on_detect,
                plan=plan,
            )
        except SafetyDecisionError:
            raise
        except Exception:
            raise SafetyDecisionError("decide.invalid_policy_or_report") from None

    @staticmethod
    def _stricter_action(
        first: SafetyAction,
        second: SafetyAction,
    ) -> SafetyAction:
        if _ACTION_RANK[first] >= _ACTION_RANK[second]:
            return first
        return second

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)

    @staticmethod
    def _policy_digest_for(
        policy: SafetyPolicy,
        *,
        auto_mask: bool,
        reject_on_detect: bool,
    ) -> str:
        return canonical_sha256(
            {
                "policy": policy.model_dump(mode="json"),
                "auto_mask": auto_mask,
                "reject_on_detect": reject_on_detect,
            }
        )

    @staticmethod
    def _report_uses_plan(report: SafetyReport, plan: _ScanPlan) -> bool:
        return (
            report.rule_set_version == plan.rule_set_version
            and report.rule_set_digest == plan.rule_set_digest
        )

    @staticmethod
    def _report_context_is_bound(report: SafetyReport) -> bool:
        expected = canonical_sha256(
            {
                "event_digest": report.event_digest,
                "context": report.context.model_dump(mode="json"),
            }
        )
        return report.context_digest == expected

    @staticmethod
    def _report_attestation_for(report: SafetyReport, key: bytes) -> str:
        payload = report.model_dump(mode="json", exclude={"attestation"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hmac.new(key, encoded, hashlib.sha256).hexdigest()

    @classmethod
    def _report_is_attested(cls, report: SafetyReport, plan: _ScanPlan) -> bool:
        if not report.attestation:
            return False
        expected = cls._report_attestation_for(
            report,
            plan.report_attestation_key,
        )
        return hmac.compare_digest(report.attestation, expected)

    @staticmethod
    def _result_attestation_for(result: SafetyResult, key: bytes) -> str:
        payload = result.model_dump(mode="json", exclude={"attestation"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        domain_separated = b"memoryhub.safety_result.v1\x00" + encoded
        return hmac.new(key, domain_separated, hashlib.sha256).hexdigest()

    @classmethod
    def _result_is_attested(cls, result: SafetyResult, plan: _ScanPlan) -> bool:
        if not result.attestation:
            return False
        expected = cls._result_attestation_for(
            result,
            plan.report_attestation_key,
        )
        return hmac.compare_digest(result.attestation, expected)

    def _validate_policy_for_plan(
        self,
        policy: SafetyPolicy,
        plan: _ScanPlan,
    ) -> None:
        known_rules = {
            runtime.rule.name: runtime.rule for runtime in plan.runtime_rules
        }
        referenced_rules = {override.rule_name for override in policy.rule_overrides}
        referenced_rules.update(
            rule_name
            for exception in policy.exceptions
            for rule_name in exception.scope.rule_names
        )
        unknown = referenced_rules - set(known_rules)
        if unknown:
            raise ValueError(
                "policy references unknown sensitive rules: "
                + ", ".join(sorted(unknown))
            )

        ineligible = {
            rule_name
            for exception in policy.exceptions
            for rule_name in exception.scope.rule_names
            if (
                known_rules[rule_name].level is not SensitiveLevel.LOW
                or known_rules[rule_name].action is SafetyAction.REJECT
            )
        }
        if ineligible:
            raise ValueError(
                "ALLOW policy exceptions are limited to low-risk contextual "
                "identifiers: " + ", ".join(sorted(ineligible))
            )
        overlay_names = {
            runtime.rule.name for runtime in plan.runtime_rules if runtime.is_overlay
        }
        mismatched = {
            exception.exception_id
            for exception in policy.exceptions
            if exception.rule_set_digest
            and exception.rule_set_digest != plan.rule_set_digest
            and not (
                exception.rule_set_digest == plan.base_rule_set_digest
                and overlay_names.isdisjoint(exception.scope.rule_names)
            )
        }
        if mismatched:
            raise ValueError(
                "policy exception rule_set_digest does not match report: "
                + ", ".join(sorted(mismatched))
            )

    @staticmethod
    def _exception_matches(
        exception: SafetyPolicyException,
        finding: SafetyFinding,
        report: SafetyReport,
        *,
        at: datetime,
        plan: _ScanPlan,
        runtime_rule: _RuntimeRule | None,
    ) -> bool:
        if not exception.enabled:
            return False
        if exception.rule_set_digest:
            binds_effective_plan = exception.rule_set_digest == report.rule_set_digest
            binds_base_rule = (
                exception.rule_set_digest == plan.base_rule_set_digest
                and runtime_rule is not None
                and not runtime_rule.is_overlay
            )
            if not binds_effective_plan and not binds_base_rule:
                return False
        if at >= exception.expires_at:
            return False
        if exception.valid_from is not None and at < exception.valid_from:
            return False
        if finding.field_path in _REPORT_METADATA_MARKERS:
            return False

        scope = exception.scope
        context = report.context
        if finding.rule_name not in scope.rule_names:
            return False
        if scope.source_types and context.source_type not in scope.source_types:
            return False
        if scope.event_types and context.event_type not in scope.event_types:
            return False
        if scope.scenes and context.scene not in scope.scenes:
            return False
        if scope.task_types and context.task_type not in scope.task_types:
            return False
        if scope.field_paths and finding.field_path not in scope.field_paths:
            return False
        return True

    @staticmethod
    def _finding_matches_runtime(
        finding: SafetyFinding,
        runtime_rule: _RuntimeRule | None,
    ) -> bool:
        if runtime_rule is None:
            return False
        rule = runtime_rule.rule
        return (
            finding.rule_version == rule.version
            and finding.level is rule.level
            and finding.suggested_action is rule.action
            and finding.replacement == rule.replacement
            and finding.maskable is runtime_rule.maskable
            and finding.reason_code == rule.reason_code
            and finding.reason == rule.reason
            and finding.standard_source == rule.standard_source
        )

    def _decide_with_snapshot(
        self,
        report: SafetyReport,
        policy: SafetyPolicy,
        *,
        auto_mask: bool,
        reject_on_detect: bool,
        plan: _ScanPlan,
    ) -> SafetyDecision:
        if not self._report_uses_plan(report, plan):
            raise SafetyDecisionError("decide.rule_snapshot_mismatch")
        if not self._report_context_is_bound(report):
            raise SafetyDecisionError("decide.context_digest_mismatch")
        if not self._report_is_attested(report, plan):
            raise SafetyDecisionError("decide.report_attestation_mismatch")
        if report.scanned_field_count == 0 or report.scan_complete == bool(
            report.issues
        ):
            raise SafetyDecisionError("decide.invalid_scan_state")
        self._validate_policy_for_plan(policy, plan)
        # Some target platforms expose a wall-clock resolution coarser than one
        # microsecond. Preserve causal ordering so an exception that expires just
        # after the scan cannot remain valid because both reads returned the same
        # timestamp.
        decision_time = max(
            datetime.now(timezone.utc),
            report.scanned_at + timedelta(microseconds=1),
        )

        runtime_by_name = {runtime.rule.name: runtime for runtime in plan.runtime_rules}
        rule_overrides = {
            override.rule_name: override.action for override in policy.rule_overrides
        }
        level_overrides = {
            override.level: override.action for override in policy.level_overrides
        }
        ordered_exceptions = tuple(
            sorted(
                policy.exceptions, key=lambda item: (item.exception_id, item.version)
            )
        )

        reason_codes: list[str] = []
        applied_exception_ids: list[str] = []
        pending: list[tuple[SafetyFinding, SafetyAction]] = []
        for finding in report.findings:
            self._append_unique(reason_codes, finding.reason_code)
            runtime_rule = runtime_by_name.get(finding.rule_name)
            finding_is_trusted = self._finding_matches_runtime(finding, runtime_rule)
            if not finding_is_trusted:
                action = self._stricter_action(
                    policy.fallback_action,
                    SafetyAction.REVIEW,
                )
                self._append_unique(reason_codes, "policy.untrusted_finding")
            elif finding.rule_name in rule_overrides:
                action = self._stricter_action(
                    finding.suggested_action,
                    rule_overrides[finding.rule_name],
                )
                self._append_unique(reason_codes, "policy.rule_override")
            elif finding.level in level_overrides:
                action = self._stricter_action(
                    finding.suggested_action,
                    level_overrides[finding.level],
                )
                self._append_unique(reason_codes, "policy.level_override")
            else:
                action = finding.suggested_action

            matching_exceptions = tuple(
                exception
                for exception in ordered_exceptions
                if finding_is_trusted
                and self._exception_matches(
                    exception,
                    finding,
                    report,
                    at=decision_time,
                    plan=plan,
                    runtime_rule=runtime_rule,
                )
            )
            if matching_exceptions:
                action = SafetyAction.ALLOW
                for exception in matching_exceptions:
                    self._append_unique(
                        applied_exception_ids,
                        exception.exception_id,
                    )
                    self._append_unique(
                        reason_codes,
                        f"policy.exception.{exception.exception_id}",
                    )

            if action is SafetyAction.MASK and not finding.maskable:
                action = self._stricter_action(
                    policy.on_unmaskable,
                    SafetyAction.REVIEW,
                )
                self._append_unique(reason_codes, "policy.unmaskable")
            if action is SafetyAction.MASK and (
                not auto_mask or not policy.auto_sanitize
            ):
                action = SafetyAction.REVIEW
                self._append_unique(reason_codes, "policy.auto_sanitize_disabled")
            pending.append((finding, action))

        global_guard = SafetyAction.ALLOW
        if not report.scan_complete:
            global_guard = self._stricter_action(
                policy.on_scan_error,
                SafetyAction.REVIEW,
            )
            self._append_unique(reason_codes, "policy.scan_incomplete")
        if reject_on_detect and report.findings:
            global_guard = SafetyAction.REJECT
            self._append_unique(reason_codes, "policy.reject_on_detect")

        finding_decisions = tuple(
            SafetyFindingDecision(
                finding_id=finding.finding_id,
                action=self._stricter_action(action, global_guard),
                reason_code=finding.reason_code,
            )
            for finding, action in pending
        )
        if finding_decisions:
            final_action = max(
                (item.action for item in finding_decisions),
                key=lambda action: _ACTION_RANK[action],
            )
        else:
            final_action = global_guard
        if report.scan_complete and not report.findings:
            final_action = SafetyAction.ALLOW
            self._append_unique(reason_codes, "policy.no_findings")

        return SafetyDecision(
            report_id=report.report_id,
            action=final_action,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_digest=self._policy_digest_for(
                policy,
                auto_mask=auto_mask,
                reject_on_detect=reject_on_detect,
            ),
            finding_decisions=finding_decisions,
            reason_codes=tuple(reason_codes),
            exception_ids=tuple(applied_exception_ids),
            reason=f"Safety policy selected {final_action.value}.",
            decided_at=decision_time,
        )

    def sanitize(self, event: MemoryEvent, report: SafetyReport) -> MemoryEvent:
        """
        按 report 中的路径和字符区间生成脱敏副本，不得重新扫描事件。

        实现必须校验 report.event_digest 与 event 匹配、保持 source_hash
        不变，并返回可重新通过 MemoryEvent 校验的新对象。
        """
        try:
            report_payload = (
                report.model_dump(mode="python")
                if isinstance(report, SafetyReport)
                else report
            )
            trusted_report = SafetyReport.model_validate(report_payload)
        except Exception:
            raise SafetySanitizationError("sanitize.invalid_report") from None
        return self._sanitize_with_snapshot(
            event,
            trusted_report,
            self._capture_scan_plan(),
        )

    @staticmethod
    def _decode_pointer(path: str) -> tuple[str, ...]:
        try:
            validate_json_path(path)
        except Exception:
            raise SafetySanitizationError("sanitize.invalid_path") from None
        return tuple(
            segment.replace("~1", "/").replace("~0", "~")
            for segment in path[1:].split("/")
        )

    @staticmethod
    def _is_sanitizable_path(segments: tuple[str, ...]) -> bool:
        if segments in {
            ("text",),
            ("event_type",),
            ("user_id",),
            ("session_id",),
            ("turn_id",),
            ("scene",),
            ("task_type",),
        }:
            return True
        if segments and segments[0] == "payload":
            return True
        if (
            len(segments) == 2
            and segments[0] == "redactions"
            and re.fullmatch(r"(?:0|[1-9][0-9]*)", segments[1]) is not None
        ):
            return True
        if (
            len(segments) == 3
            and segments[:2] == ("quality", "issues")
            and re.fullmatch(r"(?:0|[1-9][0-9]*)", segments[2]) is not None
        ):
            return True
        if (
            len(segments) >= 3
            and segments[0] == "tool_calls"
            and re.fullmatch(r"(?:0|[1-9][0-9]*)", segments[1]) is not None
            and (
                segments[2] in {"arguments", "result", "error"}
                or (len(segments) == 3 and segments[2] in {"call_id", "tool_name"})
            )
        ):
            return True
        return False

    @staticmethod
    def _resolve_pointer(
        document: Any,
        segments: tuple[str, ...],
    ) -> tuple[Any, str | int, Any]:
        current = document
        for segment in segments[:-1]:
            if isinstance(current, dict):
                if segment not in current:
                    raise SafetySanitizationError("sanitize.path_not_found")
                current = current[segment]
                continue
            if isinstance(current, list):
                if re.fullmatch(r"(?:0|[1-9][0-9]*)", segment) is None:
                    raise SafetySanitizationError("sanitize.invalid_array_index")
                index = int(segment)
                if index >= len(current):
                    raise SafetySanitizationError("sanitize.path_not_found")
                current = current[index]
                continue
            raise SafetySanitizationError("sanitize.path_not_found")

        final = segments[-1]
        if isinstance(current, dict):
            if final not in current:
                raise SafetySanitizationError("sanitize.path_not_found")
            return current, final, current[final]
        if isinstance(current, list):
            if re.fullmatch(r"(?:0|[1-9][0-9]*)", final) is None:
                raise SafetySanitizationError("sanitize.invalid_array_index")
            index = int(final)
            if index >= len(current):
                raise SafetySanitizationError("sanitize.path_not_found")
            return current, index, current[index]
        raise SafetySanitizationError("sanitize.path_not_found")

    def _sanitize_with_snapshot(
        self,
        event: MemoryEvent,
        report: SafetyReport,
        plan: _ScanPlan,
    ) -> MemoryEvent:
        if not self._report_uses_plan(report, plan):
            raise SafetySanitizationError("sanitize.rule_snapshot_mismatch")
        if not self._report_context_is_bound(report):
            raise SafetySanitizationError("sanitize.context_digest_mismatch")
        if not self._report_is_attested(report, plan):
            raise SafetySanitizationError("sanitize.report_attestation_mismatch")
        if not report.scan_complete:
            raise SafetySanitizationError("sanitize.incomplete_report")
        if report.event_id != event.event_id:
            raise SafetySanitizationError("sanitize.event_id_mismatch")
        if report.source_hash != event.source_hash:
            raise SafetySanitizationError("sanitize.source_hash_mismatch")

        snapshot_failed = False
        try:
            event_payload = event.model_dump(mode="json")
            event_digest = canonical_sha256(event_payload)
        except Exception:
            snapshot_failed = True
            event_payload = {}
            event_digest = ""
        if snapshot_failed:
            raise SafetySanitizationError("sanitize.event_snapshot_failed")
        if event_digest != report.event_digest:
            raise SafetySanitizationError("sanitize.event_digest_mismatch")

        runtime_by_name = {runtime.rule.name: runtime for runtime in plan.runtime_rules}
        operations: list[tuple[SafetyFinding, tuple[str, ...], Any, str | int, Any]] = (
            []
        )
        for finding in report.findings:
            runtime_rule = runtime_by_name.get(finding.rule_name)
            if not self._finding_matches_runtime(finding, runtime_rule):
                raise SafetySanitizationError("sanitize.untrusted_finding")
            if not finding.maskable or not finding.replacement:
                raise SafetySanitizationError("sanitize.unmaskable_finding")
            segments = self._decode_pointer(finding.field_path)
            if not segments or not self._is_sanitizable_path(segments):
                raise SafetySanitizationError("sanitize.path_outside_scanned_fields")
            parent, key, current = self._resolve_pointer(event_payload, segments)
            if finding.target is SafetyFindingTarget.TEXT_SPAN:
                if not isinstance(current, str):
                    raise SafetySanitizationError("sanitize.span_target_not_text")
                if finding.end > len(current):
                    raise SafetySanitizationError("sanitize.span_out_of_bounds")
            operations.append((finding, segments, parent, key, current))

        whole_paths = sorted(
            {
                segments
                for finding, segments, _, _, _ in operations
                if finding.target is SafetyFindingTarget.WHOLE_VALUE
            },
            key=lambda value: (len(value), value),
        )
        selected_whole_paths: list[tuple[str, ...]] = []
        for path in whole_paths:
            if any(
                path[: len(ancestor)] == ancestor for ancestor in selected_whole_paths
            ):
                continue
            selected_whole_paths.append(path)

        whole_by_path: dict[tuple[str, ...], SafetyFinding] = {}
        text_by_path: dict[tuple[str, ...], list[SafetyFinding]] = {}
        targets_by_path: dict[tuple[str, ...], tuple[Any, str | int]] = {}
        for finding, segments, parent, key, _ in operations:
            targets_by_path[segments] = (parent, key)
            shadowed = any(
                segments[: len(ancestor)] == ancestor
                for ancestor in selected_whole_paths
                if segments != ancestor
            )
            if shadowed:
                continue
            if (
                finding.target is SafetyFindingTarget.TEXT_SPAN
                and segments in selected_whole_paths
            ):
                continue
            if finding.target is SafetyFindingTarget.WHOLE_VALUE:
                existing = whole_by_path.get(segments)
                if existing is not None and (
                    existing.replacement != finding.replacement
                ):
                    raise SafetySanitizationError(
                        "sanitize.conflicting_whole_replacements"
                    )
                whole_by_path[segments] = finding
            else:
                text_by_path.setdefault(segments, []).append(finding)

        for path, finding in sorted(
            whole_by_path.items(),
            key=lambda item: (-len(item[0]), item[0]),
        ):
            parent, key = targets_by_path[path]
            parent[key] = finding.replacement

        for path, findings in sorted(text_by_path.items()):
            parent, key = targets_by_path[path]
            current = parent[key]
            if not isinstance(current, str):
                raise SafetySanitizationError("sanitize.span_target_not_text")
            ordered = sorted(
                findings,
                key=lambda item: (item.start, item.end, item.finding_id),
            )
            previous_end = -1
            for finding in ordered:
                if finding.start < previous_end:
                    raise SafetySanitizationError("sanitize.overlapping_spans")
                previous_end = finding.end
            for finding in reversed(ordered):
                current = (
                    current[: finding.start]
                    + finding.replacement
                    + current[finding.end :]
                )
            parent[key] = current

        existing_redactions = event_payload.get("redactions", [])
        if not isinstance(existing_redactions, list) or any(
            not isinstance(value, str) for value in existing_redactions
        ):
            raise SafetySanitizationError("sanitize.invalid_redactions")
        redactions = list(dict.fromkeys(existing_redactions))
        for rule_name in sorted({finding.rule_name for finding in report.findings}):
            if rule_name not in redactions:
                redactions.append(rule_name)
        event_payload["redactions"] = redactions

        validation_failed = False
        try:
            sanitized = MemoryEvent.model_validate(event_payload)
        except Exception:
            validation_failed = True
            sanitized = None
        if validation_failed or sanitized is None:
            raise SafetySanitizationError("sanitize.invalid_result")
        if sanitized.source_hash != event.source_hash:
            raise SafetySanitizationError("sanitize.source_hash_changed")
        return sanitized

    def build_audit(
        self,
        report: SafetyReport,
        decision: SafetyDecision,
        *,
        processing_time_ms: float = 0.0,
    ) -> SafetyAuditRecord:
        """仅根据报告和决策构建不含敏感原文的审计记录。"""
        if decision.report_id != report.report_id:
            raise ValueError("SafetyDecision does not belong to SafetyReport")
        report_ids = {finding.finding_id for finding in report.findings}
        decision_ids = {finding.finding_id for finding in decision.finding_decisions}
        if report_ids != decision_ids:
            raise ValueError("SafetyDecision must cover every report finding")
        decision_by_id = {
            finding.finding_id: finding for finding in decision.finding_decisions
        }
        audit_findings = tuple(
            SafetyAuditFinding(
                finding_id=finding.finding_id,
                rule_name=finding.rule_name,
                rule_version=finding.rule_version,
                level=finding.level,
                field_path=finding.field_path,
                target=finding.target,
                start=finding.start,
                end=finding.end,
                reason_code=finding.reason_code,
                standard_source=finding.standard_source,
            )
            for finding in report.findings
        )
        redaction_types: tuple[str, ...] = ()
        if decision.action is SafetyAction.MASK:
            redaction_types = tuple(
                dict.fromkeys(finding.rule_name for finding in report.findings)
            )
        if any(
            decision_by_id[finding.finding_id].reason_code != finding.reason_code
            for finding in report.findings
        ):
            raise ValueError("finding decision reason_code does not match report")
        return SafetyAuditRecord(
            report_id=report.report_id,
            event_id=report.event_id,
            source_hash=report.source_hash,
            rule_set_version=report.rule_set_version,
            rule_set_digest=report.rule_set_digest,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            policy_digest=decision.policy_digest,
            decision_action=decision.action,
            reason_codes=decision.reason_codes,
            exception_ids=decision.exception_ids,
            findings=audit_findings,
            redaction_types=redaction_types,
            processing_time_ms=processing_time_ms,
        )

    def _promote_decision(
        self,
        decision: SafetyDecision,
        action: SafetyAction,
        reason_code: str,
    ) -> SafetyDecision:
        promoted = self._stricter_action(action, SafetyAction.REVIEW)
        finding_decisions = tuple(
            SafetyFindingDecision(
                finding_id=finding.finding_id,
                action=self._stricter_action(finding.action, promoted),
                reason_code=finding.reason_code,
            )
            for finding in decision.finding_decisions
        )
        if finding_decisions:
            final_action = max(
                (finding.action for finding in finding_decisions),
                key=lambda item: _ACTION_RANK[item],
            )
        else:
            final_action = self._stricter_action(decision.action, promoted)
        reason_codes = list(decision.reason_codes)
        self._append_unique(reason_codes, reason_code)
        return SafetyDecision(
            report_id=decision.report_id,
            action=final_action,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            policy_digest=decision.policy_digest,
            finding_decisions=finding_decisions,
            reason_codes=tuple(reason_codes),
            exception_ids=decision.exception_ids,
            reason=f"Safety policy selected {final_action.value}.",
        )

    def process(self, event: MemoryEvent) -> SafetyResult:
        """
        原子安全处理主入口。

        请求开始时捕获一次规则和策略快照，再依次完成 scan、decide、
        必要的 sanitize、同快照复检和内存审计投影。不会通过调用
        detect()/mask()/should_reject() 拼装该流程。
        """
        started_ns = time.perf_counter_ns()
        plan = self._capture_scan_plan()
        try:
            policy = SafetyPolicy.model_validate(self.policy.model_dump(mode="python"))
        except Exception:
            raise SafetyDecisionError("process.invalid_policy") from None
        auto_mask = self.auto_mask
        reject_on_detect = self.reject_on_detect
        event_snapshot, report = self._scan_with_snapshot(event, plan)
        decision = self._decide_with_snapshot(
            report,
            policy,
            auto_mask=auto_mask,
            reject_on_detect=reject_on_detect,
            plan=plan,
        )

        sanitized_event: MemoryEvent | None = None
        verification_report: SafetyReport | None = None
        if decision.action is SafetyAction.ALLOW:
            sanitized_event = event_snapshot
        elif decision.action is SafetyAction.MASK:
            try:
                candidate = self._sanitize_with_snapshot(
                    event_snapshot,
                    report,
                    plan,
                )
            except SafetySanitizationError:
                decision = self._promote_decision(
                    decision,
                    policy.on_unmaskable,
                    "policy.sanitization_failed",
                )
            else:
                try:
                    verified_event, verification = self._scan_with_snapshot(
                        candidate,
                        plan,
                        verification=True,
                    )
                except SafetyScanError:
                    decision = self._promote_decision(
                        decision,
                        policy.on_scan_error,
                        "policy.verification_failed",
                    )
                else:
                    verification_failed = (
                        not verification.scan_complete
                        or verification.scanned_field_count == 0
                        or bool(verification.findings)
                    )
                    if verification_failed:
                        failure_action = (
                            policy.on_scan_error
                            if not verification.scan_complete
                            else policy.on_unmaskable
                        )
                        decision = self._promote_decision(
                            decision,
                            failure_action,
                            "policy.verification_failed",
                        )
                    else:
                        try:
                            idempotent = self._sanitize_with_snapshot(
                                verified_event,
                                verification,
                                plan,
                            )
                            idempotent_digest = canonical_sha256(
                                idempotent.model_dump(mode="json")
                            )
                        except (SafetySanitizationError, TypeError, ValueError):
                            idempotent_digest = ""
                        if idempotent_digest != verification.event_digest:
                            decision = self._promote_decision(
                                decision,
                                policy.on_unmaskable,
                                "policy.sanitization_not_idempotent",
                            )
                        else:
                            sanitized_event = verified_event
                            verification_report = verification

        processing_time_ms = max(
            0.0,
            (time.perf_counter_ns() - started_ns) / 1_000_000,
        )
        audit = self.build_audit(
            report,
            decision,
            processing_time_ms=processing_time_ms,
        )
        unsigned_result = SafetyResult(
            report=report,
            decision=decision,
            audit=audit,
            sanitized_event=sanitized_event,
            verification_report=verification_report,
        )
        result_payload = unsigned_result.model_dump(mode="python")
        result_payload["attestation"] = self._result_attestation_for(
            unsigned_result,
            plan.report_attestation_key,
        )
        return SafetyResult.model_validate(result_payload)

    def scan_text(
        self,
        text: str,
        field_path: str = "/text",
    ) -> tuple[SafetyFinding, ...]:
        """扫描单个字符串并返回带字段路径和字符区间的结构化命中。"""
        validate_json_path(field_path)
        invalid_path_unicode = False
        try:
            field_path.encode("utf-8")
        except UnicodeError:
            invalid_path_unicode = True
        if invalid_path_unicode:
            raise SafetyScanError("scan.invalid_unicode")
        if len(field_path) > self.max_path_chars:
            raise SafetyScanError("scan.limit.max_path_chars")
        normalized_path = _normalized_pointer(field_path)
        if len(normalized_path) > self.max_path_chars:
            raise SafetyScanError("scan.limit.max_path_chars")

        runtime_rules = self._runtime_rules
        state = self._new_scan_state()
        preflight_error = ""
        try:
            view = self._preflight_text(text, state)
        except SafetyScanError as exc:
            preflight_error = exc.code
        if preflight_error:
            raise SafetyScanError(preflight_error)
        self._verify_component_registries(self._component_registries)
        candidates = self._scan_view(
            view,
            field_path=field_path,
            normalized_path=normalized_path,
            target=SafetyFindingTarget.TEXT_SPAN,
            runtime_rules=runtime_rules,
            state=state,
        )
        findings = self._resolve_candidates(candidates, state)
        if state.issues:
            raise SafetyScanError(state.issues[0])
        return findings

    # ------------------------------------------------------------------
    # v0.1 兼容包装
    # ------------------------------------------------------------------

    def _compat_result(
        self,
        event: MemoryEvent,
        result: SafetyResult | None,
    ) -> SafetyResult:
        """复用调用方提供的原子结果，或为单个兼容调用执行一次 process。"""
        resolved = self.process(event) if result is None else result
        try:
            resolved = SafetyResult.model_validate(resolved.model_dump(mode="python"))
            event_digest = canonical_sha256(event.model_dump(mode="json"))
            plan = self._capture_scan_plan()
            policy = SafetyPolicy.model_validate(self.policy.model_dump(mode="python"))
            expected_decision = self._decide_with_snapshot(
                resolved.report,
                policy,
                auto_mask=self.auto_mask,
                reject_on_detect=self.reject_on_detect,
                plan=plan,
            )
        except Exception:
            raise SafetySanitizationError("result.invalid") from None
        if resolved.verification_report is not None and not self._report_is_attested(
            resolved.verification_report, plan
        ):
            raise SafetySanitizationError("result.invalid_verification_attestation")
        expected_policy = (
            expected_decision.policy_id,
            expected_decision.policy_version,
            expected_decision.policy_digest,
            expected_decision.exception_ids,
        )
        actual_policy = (
            resolved.decision.policy_id,
            resolved.decision.policy_version,
            resolved.decision.policy_digest,
            resolved.decision.exception_ids,
        )
        if actual_policy != expected_policy:
            raise SafetySanitizationError("result.decision_snapshot_mismatch")
        if (
            _ACTION_RANK[resolved.decision.action]
            < _ACTION_RANK[expected_decision.action]
        ):
            raise SafetySanitizationError("result.decision_weakened")
        expected_findings = {
            finding.finding_id: finding
            for finding in expected_decision.finding_decisions
        }
        for finding in resolved.decision.finding_decisions:
            expected_finding = expected_findings[finding.finding_id]
            if (
                finding.reason_code != expected_finding.reason_code
                or _ACTION_RANK[finding.action] < _ACTION_RANK[expected_finding.action]
            ):
                raise SafetySanitizationError("result.finding_decision_weakened")
        if any(
            code not in resolved.decision.reason_codes
            for code in expected_decision.reason_codes
        ):
            raise SafetySanitizationError("result.reason_codes_incomplete")
        event_id_matches = resolved.report.event_id == event.event_id
        if resolved.report.event_id == _REPORT_METADATA_MARKERS["/event_id"]:
            event_id_matches = not resolved.report.scan_complete or any(
                finding.field_path == "/event_id"
                for finding in resolved.report.findings
            )
        if not event_id_matches:
            raise SafetySanitizationError("result.event_id_mismatch")
        if resolved.report.source_hash != event.source_hash:
            raise SafetySanitizationError("result.source_hash_mismatch")
        if resolved.report.event_digest != event_digest:
            raise SafetySanitizationError("result.event_digest_mismatch")
        if resolved.decision.action is SafetyAction.MASK:
            if resolved.sanitized_event is None:
                raise SafetySanitizationError(
                    "result.sanitized_event_derivation_mismatch"
                )
            try:
                derived_event = self._sanitize_with_snapshot(
                    event,
                    resolved.report,
                    plan,
                )
                derived_digest = canonical_sha256(derived_event.model_dump(mode="json"))
                returned_digest = canonical_sha256(
                    resolved.sanitized_event.model_dump(mode="json")
                )
            except Exception:
                raise SafetySanitizationError(
                    "result.sanitized_event_derivation_mismatch"
                ) from None
            if not hmac.compare_digest(derived_digest, returned_digest):
                raise SafetySanitizationError(
                    "result.sanitized_event_derivation_mismatch"
                )
        if not self._result_is_attested(resolved, plan):
            raise SafetySanitizationError("result.attestation_mismatch")
        return resolved

    def validate_result(
        self,
        event: MemoryEvent,
        result: SafetyResult,
    ) -> SafetyResult:
        """
        在信任边界重新验证外部传入或反序列化的原子结果。

        校验会验证整份结果和报告的同实例 attestation，绑定原事件与当前规则/
        策略快照，重新计算不能被削弱的有效决策，并重新派生 MASK 安全副本。
        下游写入门禁不得直接信任手工构造的 SafetyResult。
        """
        return self._compat_result(event, result)

    def detect(
        self,
        event: MemoryEvent,
        *,
        result: SafetyResult | None = None,
    ) -> SensitiveLevel:
        """
        兼容旧接口：返回最高敏感等级。

        多个兼容视图必须显式传入同一个 ``result=detector.process(event)``，
        才能共享同一请求快照；生产调用方应直接消费 SafetyResult。
        """
        return self._compat_result(event, result).report.highest_level

    def detect_text(self, text: str) -> tuple[SensitiveLevel, list[str]]:
        """兼容旧接口；详细定位信息请使用 scan_text()。"""
        findings = self.scan_text(text)
        rank = {
            SensitiveLevel.NONE: 0,
            SensitiveLevel.LOW: 1,
            SensitiveLevel.MEDIUM: 2,
            SensitiveLevel.HIGH: 3,
        }
        level = SensitiveLevel.NONE
        if findings:
            level = max(
                (finding.level for finding in findings),
                key=lambda finding_level: rank[finding_level],
            )
        matched_rules = list(dict.fromkeys(finding.rule_name for finding in findings))
        return level, matched_rules

    def mask(
        self,
        event: MemoryEvent,
        *,
        result: SafetyResult | None = None,
    ) -> MemoryEvent:
        """
        兼容旧接口：返回脱敏事件。

        仅 ALLOW/MASK 分支可返回已由 process() 验证的安全副本；
        REVIEW/REJECT 必须失败关闭。多个兼容视图应传入同一个 result。
        """
        resolved = self._compat_result(event, result)
        if resolved.decision.action in (SafetyAction.REVIEW, SafetyAction.REJECT):
            raise SafetySanitizationError("sanitize.blocked_by_decision")
        if resolved.sanitized_event is not None:
            return resolved.sanitized_event
        raise SafetySanitizationError("result.missing_safe_event")

    def mask_text(self, text: str) -> str:
        """兼容旧接口：对单个文本做全量替换并执行一次无残留复检。"""
        findings = self.scan_text(text)
        if any(not finding.maskable for finding in findings):
            raise SafetySanitizationError("sanitize.unmaskable_finding")
        try:
            policy = SafetyPolicy.model_validate(self.policy.model_dump(mode="python"))
            plan = self._capture_scan_plan()
            self._validate_policy_for_plan(policy, plan)
        except Exception:
            raise SafetySanitizationError("sanitize.invalid_policy") from None
        rule_overrides = {
            override.rule_name: override.action for override in policy.rule_overrides
        }
        level_overrides = {
            override.level: override.action for override in policy.level_overrides
        }
        for finding in findings:
            configured_action = rule_overrides.get(
                finding.rule_name,
                level_overrides.get(finding.level, finding.suggested_action),
            )
            action = self._stricter_action(
                finding.suggested_action,
                configured_action,
            )
            if self.reject_on_detect:
                action = SafetyAction.REJECT
            if action is not SafetyAction.MASK:
                raise SafetySanitizationError("sanitize.blocked_by_decision")
            if not self.auto_mask or not policy.auto_sanitize:
                raise SafetySanitizationError("sanitize.blocked_by_decision")
        ordered = sorted(
            findings,
            key=lambda item: (item.start, item.end, item.finding_id),
        )
        previous_end = -1
        for finding in ordered:
            if finding.start < previous_end:
                raise SafetySanitizationError("sanitize.overlapping_spans")
            previous_end = finding.end
        sanitized = text
        for finding in reversed(ordered):
            sanitized = (
                sanitized[: finding.start]
                + finding.replacement
                + sanitized[finding.end :]
            )
        if self.scan_text(sanitized):
            raise SafetySanitizationError("sanitize.verification_failed")
        return sanitized

    def should_reject(
        self,
        event: MemoryEvent,
        *,
        result: SafetyResult | None = None,
    ) -> tuple[bool, str]:
        """
        兼容旧接口：REVIEW/REJECT 均映射为阻止普通入库。

        旧布尔值无法区分隔离复核与最终拒绝，因此新写入链必须读取 decision。
        """
        decision = self._compat_result(event, result).decision
        blocked = decision.action in (SafetyAction.REVIEW, SafetyAction.REJECT)
        return blocked, decision.reason
