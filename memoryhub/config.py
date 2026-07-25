"""全局配置管理"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from memoryhub.adapter.schemas import (
    SafetyPolicy,
    SensitiveRule,
    canonical_sha256,
)

if TYPE_CHECKING:
    from memoryhub.safety_rules import RuleSetSnapshot

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class StorageConfig:
    """存储相关配置"""

    db_path: str = "data/memoryhub.db"
    vector_index_path: str = "data/vector_index"
    evidence_path: str = "data/evidence"
    cache_max_size: int = 1000


@dataclass
class RetrievalConfig:
    """检索相关配置"""

    default_top_k: int = 5
    vector_weight: float = 0.6
    keyword_weight: float = 0.3
    metadata_weight: float = 0.1
    rerank_enabled: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class LLMConfig:
    """LLM 调用配置"""

    provider: str = "openai"  # "openai" | "ollama"
    api_base: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "qwen2:1.5b"
    temperature: float = 0.1
    max_tokens: int = 2048


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""

    provider: str = "mock"  # "kylin" | "mock"
    dimension: int = 1024
    model_name: str = ""


@dataclass(frozen=True)
class SafetyAuditConfig:
    """安全处置审计日志配置；密钥只通过环境变量或设备密钥服务提供。"""

    enabled: bool = True
    directory: str = "data/safety-audit"
    hmac_key_env: str = "MEMORYHUB_AUDIT_HMAC_KEY"
    key_id: str = "device-local-v1"
    rotate_max_bytes: int = 16 * 1024 * 1024
    retention_days: int = 180
    max_record_bytes: int = 64 * 1024
    lock_timeout_seconds: float = 5.0
    strict_permissions: bool = True
    fsync: bool = True
    fail_closed: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.directory, str)
            or not self.directory
            or "\x00" in self.directory
        ):
            raise ValueError("audit directory must not be empty")
        if (
            not isinstance(self.hmac_key_env, str)
            or _ENV_NAME_RE.fullmatch(self.hmac_key_env) is None
        ):
            raise ValueError("audit hmac_key_env must be an environment variable name")
        if (
            not isinstance(self.key_id, str)
            or _KEY_ID_RE.fullmatch(self.key_id) is None
        ):
            raise ValueError("audit key_id must be a stable identifier")
        if type(self.rotate_max_bytes) is not int or self.rotate_max_bytes <= 0:
            raise ValueError("audit rotate_max_bytes must be a positive integer")
        if type(self.retention_days) is not int or self.retention_days <= 0:
            raise ValueError("audit retention_days must be a positive integer")
        if type(self.max_record_bytes) is not int or self.max_record_bytes <= 0:
            raise ValueError("audit max_record_bytes must be a positive integer")
        if (
            type(self.lock_timeout_seconds) not in (int, float)
            or not math.isfinite(float(self.lock_timeout_seconds))
            or self.lock_timeout_seconds <= 0
        ):
            raise ValueError("audit lock_timeout_seconds must be finite and positive")
        for field_name in (
            "enabled",
            "strict_permissions",
            "fsync",
            "fail_closed",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"audit {field_name} must be a boolean")
        if not self.strict_permissions or not self.fsync or not self.fail_closed:
            raise ValueError(
                "audit permissions, fsync and fail_closed cannot be disabled"
            )


@dataclass(frozen=True)
class ReviewQuarantineConfig:
    """REVIEW 隔离区配置；原事件只能以设备密钥加密后的密文落盘。"""

    enabled: bool = True
    directory: str = "data/review-quarantine"
    encryption_key_env: str = "MEMORYHUB_QUARANTINE_KEY"
    key_id: str = "device-local-v1"
    retention_days: int = 30
    max_record_bytes: int = 4 * 1024 * 1024
    strict_permissions: bool = True
    fsync: bool = True
    fail_closed: bool = True

    def __post_init__(self) -> None:
        if (
            not isinstance(self.directory, str)
            or not self.directory
            or "\x00" in self.directory
        ):
            raise ValueError("quarantine directory must not be empty")
        if (
            not isinstance(self.encryption_key_env, str)
            or _ENV_NAME_RE.fullmatch(self.encryption_key_env) is None
        ):
            raise ValueError(
                "quarantine encryption_key_env must be an environment variable name"
            )
        if (
            not isinstance(self.key_id, str)
            or _KEY_ID_RE.fullmatch(self.key_id) is None
        ):
            raise ValueError("quarantine key_id must be a stable identifier")
        if type(self.retention_days) is not int or self.retention_days <= 0:
            raise ValueError("quarantine retention_days must be a positive integer")
        if type(self.max_record_bytes) is not int or self.max_record_bytes <= 0:
            raise ValueError("quarantine max_record_bytes must be a positive integer")
        for field_name in (
            "enabled",
            "strict_permissions",
            "fsync",
            "fail_closed",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"quarantine {field_name} must be a boolean")
        if not self.strict_permissions or not self.fsync or not self.fail_closed:
            raise ValueError(
                "quarantine permissions, fsync and fail_closed cannot be disabled"
            )


@dataclass
class SafetyConfig:
    """安全过滤配置；sensitive_patterns 保留旧字段名，但元素已结构化。"""

    MAX_SUPPORTED_DEPTH: ClassVar[int] = 64

    rule_set_id: str | None = None
    rule_set_version: str | None = None
    rule_set_digest: str = field(init=False, default="")
    rule_snapshot: "RuleSetSnapshot | None" = field(default=None, repr=False)
    sensitive_patterns: list[SensitiveRule] | None = None
    policy: SafetyPolicy = field(default_factory=SafetyPolicy)
    auto_mask: bool = True
    # 仅供旧调用方迁移；新代码应通过 policy 决定 ALLOW/MASK/REVIEW/REJECT。
    reject_on_detect: bool = False
    audit: SafetyAuditConfig = field(default_factory=SafetyAuditConfig)
    quarantine: ReviewQuarantineConfig = field(default_factory=ReviewQuarantineConfig)
    max_depth: int = 32
    max_field_chars: int = 65_536
    max_scan_bytes: int = 2 * 1024 * 1024
    max_scanned_fields: int = 10_000
    max_candidates: int = 2_048
    max_findings: int = 1_024
    max_path_chars: int = 4_096

    def __post_init__(self) -> None:
        """把 YAML 风格映射归一化为强类型契约，并校验规则名唯一。"""
        if isinstance(self.audit, Mapping):
            self.audit = SafetyAuditConfig(**dict(self.audit))
        elif not isinstance(self.audit, SafetyAuditConfig):
            raise ValueError("audit must be a SafetyAuditConfig or mapping")
        if isinstance(self.quarantine, Mapping):
            self.quarantine = ReviewQuarantineConfig(**dict(self.quarantine))
        elif not isinstance(self.quarantine, ReviewQuarantineConfig):
            raise ValueError("quarantine must be a ReviewQuarantineConfig or mapping")
        for field_name in (
            "max_depth",
            "max_field_chars",
            "max_scan_bytes",
            "max_scanned_fields",
            "max_candidates",
            "max_findings",
            "max_path_chars",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_depth > self.MAX_SUPPORTED_DEPTH:
            raise ValueError(f"max_depth must be <= {self.MAX_SUPPORTED_DEPTH}")
        builtin_digest = ""
        if self.rule_snapshot is not None and self.sensitive_patterns is not None:
            raise ValueError(
                "rule_snapshot and sensitive_patterns are mutually exclusive"
            )
        if self.rule_snapshot is not None:
            if self.rule_set_id not in (None, self.rule_snapshot.rule_set_id):
                raise ValueError("rule_set_id does not match rule_snapshot")
            if self.rule_set_version not in (None, self.rule_snapshot.version):
                raise ValueError("rule_set_version does not match rule_snapshot")
            self.rule_set_id = self.rule_snapshot.rule_set_id
            self.rule_set_version = self.rule_snapshot.version
            self.sensitive_patterns = list(self.rule_snapshot.compiled_rules)
            builtin_digest = self.rule_snapshot.digest
        elif self.sensitive_patterns is None:
            # 延迟导入避免 adapter/config 与 core.safety 的初始化环。
            from memoryhub.safety_rules import load_builtin_rule_set

            snapshot = load_builtin_rule_set(version=self.rule_set_version)
            if self.rule_set_id not in (None, snapshot.rule_set_id):
                raise ValueError(
                    "configured rule_set_id does not match the builtin rule library"
                )
            self.rule_set_id = snapshot.rule_set_id
            self.rule_set_version = snapshot.version
            self.sensitive_patterns = list(snapshot.compiled_rules)
            self.rule_snapshot = snapshot
            builtin_digest = snapshot.digest
        else:
            self.rule_set_id = self.rule_set_id or "custom.safety"
            self.rule_set_version = self.rule_set_version or "1.0"
        if not self.rule_set_id:
            raise ValueError("rule_set_id must not be empty")
        if not self.rule_set_version:
            raise ValueError("rule_set_version must not be empty")
        self.sensitive_patterns = [
            SensitiveRule.model_validate(
                rule.model_dump(mode="python")
                if isinstance(rule, SensitiveRule)
                else rule
            )
            for rule in self.sensitive_patterns
        ]
        self.policy = SafetyPolicy.model_validate(
            self.policy.model_dump(mode="python")
            if isinstance(self.policy, SafetyPolicy)
            else self.policy
        )
        names = [rule.name for rule in self.sensitive_patterns]
        if len(names) != len(set(names)):
            raise ValueError("sensitive rule names must be unique")
        unknown_overrides = {
            override.rule_name for override in self.policy.rule_overrides
        } - set(names)
        if unknown_overrides:
            unknown = ", ".join(sorted(unknown_overrides))
            raise ValueError(f"policy references unknown sensitive rules: {unknown}")
        self.rule_set_digest = builtin_digest or canonical_sha256(
            {
                "rule_set_id": self.rule_set_id,
                "rule_set_version": self.rule_set_version,
                "rules": [
                    rule.model_dump(mode="json") for rule in self.sensitive_patterns
                ],
            }
        )

    @property
    def rules(self) -> tuple[SensitiveRule, ...]:
        """返回供检测器捕获不可变快照的规则视图。"""
        assert self.sensitive_patterns is not None
        return tuple(self.sensitive_patterns)


@dataclass
class AppConfig:
    """应用总配置"""

    storage: StorageConfig = field(default_factory=StorageConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    debug: bool = False


def load_config() -> AppConfig:
    """加载配置，优先从环境变量/配置文件读取"""
    return AppConfig()
