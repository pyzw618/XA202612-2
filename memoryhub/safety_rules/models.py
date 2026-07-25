"""版本化安全规则与溯源数据模型。"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from memoryhub.adapter.schemas import SensitiveLevel, SensitiveRule
from memoryhub.safety_rules.components import ComponentRegistry, Masker, Validator
from memoryhub.safety_rules.errors import RuleLibraryError
from memoryhub.safety_rules.paths import validate_target_path
from memoryhub.safety_rules.regex_safety import validate_regex_safety
from memoryhub.safety_rules.versions import (
    normalized_version,
    validate_component_reference,
)


_IDENTIFIER_RE = r"^[a-z][a-z0-9_.-]*$"
_REDACTION_MARKER_RE = re.compile(r"^\[REDACTED(?:_[A-Z0-9_]+)?\]$")
_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _strict_date_input(value: Any) -> Any:
    if value is None or type(value) is date:
        return value
    if type(value) is str and _ISO_DATE_RE.fullmatch(value) is not None:
        return value
    raise ValueError("dates must be YYYY-MM-DD strings")


class SensitiveCategory(str, Enum):
    """秘密凭据与两类个人信息在规则层显式分离。"""

    CREDENTIAL = "credential"
    PERSONAL = "personal"
    SENSITIVE_PERSONAL = "sensitive_personal"


class RuleDefaultAction(str, Enum):
    """声明式规则动作；REDACT_ALLOW 在运行时编译为 SafetyAction.MASK。"""

    REJECT = "reject"
    REDACT_ALLOW = "redact_allow"
    REVIEW = "review"
    ALLOW = "allow"


class SourceKind(str, Enum):
    """规则依据的来源类型与效力边界。"""

    LAW = "law"
    MANDATORY_GB = "mandatory_gb"
    RECOMMENDED_GBT = "recommended_gbt"
    TC260_GUIDE = "tc260_guide"
    IETF_RFC = "ietf_rfc"
    VENDOR_DOC = "vendor_doc"
    SECURITY_GUIDANCE = "security_guidance"
    PROJECT_POLICY = "project_policy"


class SourceRole(str, Enum):
    """一项依据与一条规则之间的用途，而不是笼统的“符合”。"""

    CLASSIFICATION = "classification"
    SYNTAX = "syntax"
    SEMANTIC_VALIDATION = "semantic_validation"
    HANDLING = "handling"
    DEIDENTIFICATION = "deidentification"
    EFFECTIVENESS = "effectiveness"
    LIFECYCLE = "lifecycle"
    AUDIT = "audit"
    RISK_POLICY = "risk_policy"
    THREAT_MODEL = "threat_model"


class RuleSource(BaseModel):
    """顶层来源目录中的一项法律、标准、协议、指南或项目策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=_IDENTIFIER_RE)
    source_kind: SourceKind
    identifier: str = Field(min_length=1)
    title: str = Field(min_length=1)
    edition: str = ""
    issuer: str = Field(min_length=1)
    normative_force: str = Field(min_length=1)
    published_on: date | None = None
    effective_on: date | None = None
    status: str = Field(min_length=1)
    status_as_of: date
    official_url: str = Field(pattern=r"^(?:https://|urn:)")
    supersession_candidate: str = ""
    caveat: str = Field(min_length=1)

    @field_validator(
        "published_on",
        "effective_on",
        "status_as_of",
        mode="before",
    )
    @classmethod
    def validate_date_input(cls, value: Any) -> Any:
        return _strict_date_input(value)


class RuleSourceLink(BaseModel):
    """规则到来源的结构化关联，明确该来源在此处承担什么作用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(pattern=_IDENTIFIER_RE)
    role: SourceRole
    locator: str = ""
    derivation_note: str = Field(min_length=1)
    caveat: str = Field(min_length=1)


class RuleDefinition(BaseModel):
    """规则资产的声明式对象；不包含任意 Python 可执行代码。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(pattern=_IDENTIFIER_RE)
    category: SensitiveCategory
    risk_level: SensitiveLevel
    default_action: RuleDefaultAction
    pattern: str = Field(min_length=1)
    validator: str = Field(min_length=1)
    masker: str = Field(min_length=1)
    target_paths: tuple[str, ...] = Field(min_length=1)
    target_path_case_sensitive: StrictBool = True
    priority: int = Field(ge=0, le=10_000)
    standard_ref: tuple[RuleSourceLink, ...] = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    enabled: StrictBool = True

    reason_code: str = Field(pattern=_IDENTIFIER_RE)
    reason: str = Field(min_length=1)
    replacement: str = "[REDACTED]"
    match_group: int | str = 0

    @field_validator("rule_version")
    @classmethod
    def validate_rule_version(cls, value: str) -> str:
        try:
            normalized_version(value)
        except RuleLibraryError as exc:
            raise ValueError(
                "rule_version must be a two- or three-part semantic version"
            ) from exc
        return value

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        if len(value) > 4096:
            raise ValueError("rule pattern exceeds the 4096-character safety limit")
        try:
            compiled = re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid rule pattern: {exc}") from exc
        if compiled.search("") is not None:
            raise ValueError("rule pattern must not match an empty string")
        validate_regex_safety(value)
        return value

    @field_validator("validator", "masker")
    @classmethod
    def validate_component_reference_shape(cls, value: str) -> str:
        try:
            return validate_component_reference(value)
        except RuleLibraryError as exc:
            raise ValueError(
                "rule components must use strict versioned allow-list references"
            ) from exc

    @field_validator("target_paths", mode="before")
    @classmethod
    def validate_target_paths_type(cls, value: Any) -> Any:
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            raise ValueError("target_paths must be a non-empty list")
        return value

    @field_validator("target_paths")
    @classmethod
    def normalize_target_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(validate_target_path(path) for path in value))
        if len(normalized) != len(set(normalized)):
            raise ValueError("target_paths must not contain duplicates")
        if "/**" in normalized:
            return ("/**",)
        return normalized

    @field_validator("standard_ref", mode="before")
    @classmethod
    def validate_standard_ref_type(cls, value: Any) -> Any:
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            raise ValueError("standard_ref must be a non-empty list of source links")
        return value

    @field_validator("standard_ref")
    @classmethod
    def normalize_standard_ref(
        cls, value: tuple[RuleSourceLink, ...]
    ) -> tuple[RuleSourceLink, ...]:
        keys = [
            (
                link.source_id,
                link.role.value,
                link.locator,
                link.derivation_note,
                link.caveat,
            )
            for link in value
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("standard_ref must not contain duplicate links")
        return tuple(
            sorted(
                value,
                key=lambda link: (
                    link.source_id,
                    link.role.value,
                    link.locator,
                    link.derivation_note,
                    link.caveat,
                ),
            )
        )

    @field_validator("priority", mode="before")
    @classmethod
    def validate_priority_type(cls, value: Any) -> int:
        if type(value) is not int:
            raise ValueError("priority must be an integer")
        return value

    @field_validator("match_group", mode="before")
    @classmethod
    def validate_match_group_type(cls, value: Any) -> int | str:
        if type(value) not in (int, str):
            raise ValueError("match_group must be an int or str")
        return value

    @model_validator(mode="after")
    def validate_runtime_semantics(self) -> "RuleDefinition":
        compiled = re.compile(self.pattern)
        if not self.target_path_case_sensitive:
            ascii_folded = tuple(
                path.translate(
                    str.maketrans(
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
                    )
                )
                for path in self.target_paths
            )
            if len(ascii_folded) != len(set(ascii_folded)):
                raise ValueError(
                    "case-insensitive target_paths must not contain equivalent paths"
                )
        if isinstance(self.match_group, int):
            if self.match_group < 0 or self.match_group > compiled.groups:
                raise ValueError("match_group index does not exist in pattern")
        elif self.match_group not in compiled.groupindex:
            raise ValueError("named match_group does not exist in pattern")
        if self.default_action is RuleDefaultAction.REDACT_ALLOW:
            if self.masker == "builtin.none@1.0":
                raise ValueError("redact_allow requires a real masker")
            if _REDACTION_MARKER_RE.fullmatch(self.replacement) is None:
                raise ValueError(
                    "redact_allow replacement must be a fixed redaction marker"
                )
        if self.enabled and self.risk_level is SensitiveLevel.NONE:
            raise ValueError("enabled rule cannot use risk_level none")
        return self


class RuleSetDocument(BaseModel):
    """磁盘上的一个完整、不可部分加载的规则集版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    rule_set_id: str = Field(pattern=_IDENTIFIER_RE)
    version: str = Field(min_length=1)
    released_on: date | None = None
    status_as_of: date | None = None
    sources: tuple[RuleSource, ...] = Field(min_length=1)
    governance_ref: tuple[RuleSourceLink, ...] = Field(default_factory=tuple)
    rules: tuple[RuleDefinition, ...] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        try:
            normalized_version(value)
        except RuleLibraryError as exc:
            raise ValueError(
                "rule-set version must be a two- or three-part semantic version"
            ) from exc
        return value

    @field_validator("released_on", "status_as_of", mode="before")
    @classmethod
    def validate_date_input(cls, value: Any) -> Any:
        return _strict_date_input(value)

    @model_validator(mode="after")
    def validate_and_canonicalize(self) -> "RuleSetDocument":
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("rule source_id values must be unique")

        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError(
                "a rule-set snapshot may activate only one version of a rule_id"
            )
        governance_keys = [
            (
                link.source_id,
                link.role.value,
                link.locator,
                link.derivation_note,
                link.caveat,
            )
            for link in self.governance_ref
        ]
        if len(governance_keys) != len(set(governance_keys)):
            raise ValueError("governance_ref must not contain duplicate links")

        known_sources = set(source_ids)
        dangling = {
            link.source_id
            for rule in self.rules
            for link in rule.standard_ref
            if link.source_id not in known_sources
        }
        dangling.update(
            link.source_id
            for link in self.governance_ref
            if link.source_id not in known_sources
        )
        if dangling:
            raise ValueError(
                "rules reference unknown provenance sources: "
                + ", ".join(sorted(dangling))
            )

        ordered_sources = tuple(
            sorted(self.sources, key=lambda source: source.source_id)
        )
        ordered_governance_ref = tuple(
            sorted(
                self.governance_ref,
                key=lambda link: (
                    link.source_id,
                    link.role.value,
                    link.locator,
                    link.derivation_note,
                    link.caveat,
                ),
            )
        )
        ordered_rules = tuple(
            sorted(
                self.rules,
                key=lambda rule: (-rule.priority, rule.rule_id, rule.rule_version),
            )
        )
        object.__setattr__(self, "sources", ordered_sources)
        object.__setattr__(self, "governance_ref", ordered_governance_ref)
        object.__setattr__(self, "rules", ordered_rules)
        return self


class RuleSetSnapshot(BaseModel):
    """校验、组件解析和编译全部成功后的深度不可变快照。"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    schema_version: Literal["1.0"]
    rule_set_id: str
    version: str
    released_on: date | None = None
    status_as_of: date | None = None
    sources: tuple[RuleSource, ...]
    governance_ref: tuple[RuleSourceLink, ...]
    rules: tuple[RuleDefinition, ...]
    compiled_rules: tuple[SensitiveRule, ...]
    component_registry_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_registry: ComponentRegistry = Field(exclude=True, repr=False)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def get_rule(self, rule_id: str) -> RuleDefinition:
        """按稳定 ID 取得规则；缺失时显式失败，不做版本回退。"""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise KeyError(rule_id)

    def resolve_validator(self, rule: RuleDefinition | str) -> Validator:
        """从此快照绑定的组件注册表解析 validator。"""
        reference = rule.validator if isinstance(rule, RuleDefinition) else rule
        if reference not in {item.validator for item in self.rules}:
            raise RuleLibraryError(
                f"validator is outside this rule snapshot: {reference}"
            )
        return self.component_registry.resolve_validator(reference)

    def resolve_masker(self, rule: RuleDefinition | str) -> Masker:
        """从此快照绑定的组件注册表解析 masker。"""
        reference = rule.masker if isinstance(rule, RuleDefinition) else rule
        if reference not in {item.masker for item in self.rules}:
            raise RuleLibraryError(f"masker is outside this rule snapshot: {reference}")
        return self.component_registry.resolve_masker(reference)

    @property
    def traceability_matrix(self) -> tuple[dict[str, str], ...]:
        """导出“来源—用途—规则”矩阵的只读视图。"""
        rule_rows = tuple(
            {
                "source_id": link.source_id,
                "role": link.role.value,
                "rule_id": rule.rule_id,
                "rule_version": rule.rule_version,
                "locator": link.locator,
                "derivation_note": link.derivation_note,
                "caveat": link.caveat,
            }
            for rule in self.rules
            for link in rule.standard_ref
        )
        governance_rows = tuple(
            {
                "source_id": link.source_id,
                "role": link.role.value,
                "rule_id": "@rule_set",
                "rule_version": self.version,
                "locator": link.locator,
                "derivation_note": link.derivation_note,
                "caveat": link.caveat,
            }
            for link in self.governance_ref
        )
        return rule_rows + governance_rows
