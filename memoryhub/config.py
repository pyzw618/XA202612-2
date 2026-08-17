"""全局配置管理"""

from __future__ import annotations

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


class ProductionGateError(ValueError):
    """生产环境启动门禁未通过。"""


_RUNTIME_MODES = frozenset({"production", "development", "test"})
_PRODUCTION_EMBEDDING_PROVIDER = "kylin"
_PRODUCTION_VECTOR_ENGINE_PROVIDER = "milvus"
_PRODUCTION_DIMENSION = 768


def is_production_mode() -> bool:
    """根据当前生效的运行时配置判断是否处于 production 模式。

    优先读取 ``MEMORYHUB_RUNTIME_MODE`` 环境变量；未设置时返回 False，
    避免低层模块在导入阶段依赖完整 ``load_config()`` 流程。
    """
    import os

    mode = os.environ.get("MEMORYHUB_RUNTIME_MODE", "")
    return mode == "production"


@dataclass
class RuntimeConfig:
    """运行时模式与降级策略配置"""

    mode: str = "development"  # "production" | "development" | "test"
    allow_fallback: bool = True  # development/test 默认可降级；生产强制 false

    def __post_init__(self) -> None:
        if self.mode not in _RUNTIME_MODES:
            raise ValueError(
                f"runtime.mode must be one of {_RUNTIME_MODES}, got {self.mode!r}"
            )
        if type(self.allow_fallback) is not bool:
            raise ValueError("runtime.allow_fallback must be a boolean")

    @property
    def is_production(self) -> bool:
        return self.mode == "production"


@dataclass
class RetrievalConfig:
    """检索相关配置"""

    default_top_k: int = 5
    candidate_multiplier: int = 4
    max_query_chars: int = 512
    target_p95_ms: int = 350
    target_p99_ms: int = 500
    vector_weight: float = 0.6
    keyword_weight: float = 0.3
    metadata_weight: float = 0.1
    rerank_enabled: bool = True
    cache_ttl_seconds: int = 300


@dataclass
class LLMConfig:
    """Cloud OpenAI-compatible LLM configuration."""

    api_base: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.1
    max_tokens: int = 2048
    # Fact extraction is an optional enrichment step.  Keep this small so an
    # unavailable local/external LLM never delays durable event processing.
    fact_extraction_timeout_seconds: float = 1.0


@dataclass
class EmbeddingConfig:
    """Embedding 配置"""

    provider: str = "mock"  # "kylin" | "kylin_mock" | "mock" | "auto"
    dimension: int = 1024
    model_name: str = ""
    so_path: str = ""  # 动态库显式路径（kylin/kylin_mock 模式，空则按默认路径探测）
    query_timeout_ms: int = 250


@dataclass
class VectorEngineConfig:
    """向量引擎配置"""

    provider: str = "faiss"  # "faiss" | "milvus" | "milvus_mock"
    app_id: str = ""  # 部署平台提供的应用标识（milvus/milvus_mock 必填）
    so_path: str = ""  # Milvus C API 动态库显式路径（空则按默认路径探测）
    host: str = "127.0.0.1"
    port: int = 19530
    collection: str = "memoryhub"
    dimension: int = 768
    search_timeout_ms: int = 120

    def __post_init__(self) -> None:
        """校验向量引擎配置，确保 Milvus 在加载动态库前已有 app_id。"""
        if not isinstance(self.app_id, str):
            raise ValueError("vector_engine.app_id must be a string")
        self.app_id = self.app_id.strip()
        if self.provider in {"milvus", "milvus_mock"} and not self.app_id:
            raise ValueError(
                "vector_engine.app_id must be a non-empty string for Milvus providers"
            )


@dataclass
class ExtractionRetryConfig:
    """Durable extraction retry worker settings."""

    enabled: bool = True
    interval_seconds: float = 30.0
    batch_size: int = 20


@dataclass
class KnowledgeMergeConfig:
    """Internal knowledge equivalence and conflict thresholds."""

    name_weight: float = 0.35
    content_weight: float = 0.35
    steps_weight: float = 0.30
    equivalent_threshold: float = 0.72
    conflict_threshold: float = 0.58

    def __post_init__(self) -> None:
        weights = (self.name_weight, self.content_weight, self.steps_weight)
        if any(weight < 0 for weight in weights) or sum(weights) <= 0:
            raise ValueError("knowledge merge weights must be non-negative and non-zero")
        if not 0.0 <= self.conflict_threshold <= 1.0:
            raise ValueError("knowledge conflict threshold must be within [0, 1]")
        if not 0.0 <= self.equivalent_threshold <= 1.0:
            raise ValueError("knowledge equivalent threshold must be within [0, 1]")

@dataclass(frozen=True)
class SafetyKeyStoreConfig:
    """端侧安全密钥持久化配置；密钥值本身不进入业务配置。"""

    # 空路径表示使用 ``<storage.db_path 父目录>/security/safety-keys.json``。
    # 相对路径同样以 storage.db_path 的父目录为基准，避免依赖启动 cwd。
    path: str = ""
    auto_generate: bool = True
    persist_external: bool = True
    import_legacy_env: bool = True
    legacy_env_file: str = "~/.config/memoryhub/safety.env"
    strict_permissions: bool = True

    def __post_init__(self) -> None:
        for field_name in ("path", "legacy_env_file"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or "\x00" in value:
                raise ValueError(
                    f"key_store {field_name} must be a string without NUL bytes"
                )
        for field_name in (
            "auto_generate",
            "persist_external",
            "import_legacy_env",
            "strict_permissions",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise ValueError(f"key_store {field_name} must be a boolean")
        if not self.strict_permissions:
            raise ValueError("key_store strict_permissions cannot be disabled")


@dataclass(frozen=True)
class SafetyAuditConfig:
    """安全处置审计日志配置。"""

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


@dataclass(frozen=True)
class UserRuleConfig:
    """用户自定义敏感规则配置。"""

    enabled: bool = True
    encryption_key_env: str = "MEMORYHUB_USER_RULE_KEY"
    key_id: str = "device-local-v1"
    max_rules_per_user: int = 100
    max_matcher_chars: int = 2_048
    allow_advanced_regex: bool = False
    detector_cache_size: int = 256

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("user_rules enabled must be a boolean")
        if (
            not isinstance(self.encryption_key_env, str)
            or _ENV_NAME_RE.fullmatch(self.encryption_key_env) is None
        ):
            raise ValueError(
                "user_rules encryption_key_env must be an environment variable name"
            )
        if (
            not isinstance(self.key_id, str)
            or _KEY_ID_RE.fullmatch(self.key_id) is None
        ):
            raise ValueError("user_rules key_id must be a stable identifier")
        for field_name in (
            "max_rules_per_user",
            "max_matcher_chars",
            "detector_cache_size",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"user_rules {field_name} must be a positive integer")
        if type(self.allow_advanced_regex) is not bool:
            raise ValueError("user_rules allow_advanced_regex must be a boolean")


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
    key_store: SafetyKeyStoreConfig = field(default_factory=SafetyKeyStoreConfig)
    audit: SafetyAuditConfig = field(default_factory=SafetyAuditConfig)
    quarantine: ReviewQuarantineConfig = field(default_factory=ReviewQuarantineConfig)
    user_rules: UserRuleConfig = field(default_factory=UserRuleConfig)
    max_depth: int = 32
    max_field_chars: int = 65_536
    max_scan_bytes: int = 2 * 1024 * 1024
    max_scanned_fields: int = 10_000
    max_candidates: int = 2_048
    max_findings: int = 1_024
    max_path_chars: int = 4_096

    def __post_init__(self) -> None:
        """把 YAML 风格映射归一化为强类型契约，并校验规则名唯一。"""
        if isinstance(self.key_store, Mapping):
            self.key_store = SafetyKeyStoreConfig(**dict(self.key_store))
        elif not isinstance(self.key_store, SafetyKeyStoreConfig):
            raise ValueError("key_store must be a SafetyKeyStoreConfig or mapping")
        if isinstance(self.audit, Mapping):
            self.audit = SafetyAuditConfig(**dict(self.audit))
        elif not isinstance(self.audit, SafetyAuditConfig):
            raise ValueError("audit must be a SafetyAuditConfig or mapping")
        if isinstance(self.quarantine, Mapping):
            self.quarantine = ReviewQuarantineConfig(**dict(self.quarantine))
        elif not isinstance(self.quarantine, ReviewQuarantineConfig):
            raise ValueError("quarantine must be a ReviewQuarantineConfig or mapping")
        if isinstance(self.user_rules, Mapping):
            self.user_rules = UserRuleConfig(**dict(self.user_rules))
        elif not isinstance(self.user_rules, UserRuleConfig):
            raise ValueError("user_rules must be a UserRuleConfig or mapping")
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


def validate_production_gate(config: AppConfig) -> None:
    """生产模式静态配置门禁：校验 provider、维度与降级策略。

    动态库加载与会话初始化等运行时检查由 ``validate_production_runtime``
    在客户端/引擎构造完成后执行。
    """
    if not config.runtime.is_production:
        return

    errors: list[str] = []

    # 生产模式下禁止显式允许降级
    if config.runtime.allow_fallback:
        errors.append("runtime.allow_fallback must be false in production mode")

    # Embedding 必须是真实麒麟 SDK
    if config.embedding.provider != _PRODUCTION_EMBEDDING_PROVIDER:
        errors.append(
            f"production requires embedding.provider='{_PRODUCTION_EMBEDDING_PROVIDER}', "
            f"got {config.embedding.provider!r}"
        )

    # 向量引擎必须是真实 Milvus
    if config.vector_engine.provider != _PRODUCTION_VECTOR_ENGINE_PROVIDER:
        errors.append(
            f"production requires vector_engine.provider='{_PRODUCTION_VECTOR_ENGINE_PROVIDER}', "
            f"got {config.vector_engine.provider!r}"
        )

    # 维度固定 768
    if config.embedding.dimension != _PRODUCTION_DIMENSION:
        errors.append(
            f"production requires embedding.dimension={_PRODUCTION_DIMENSION}, "
            f"got {config.embedding.dimension}"
        )
    if config.vector_engine.dimension != _PRODUCTION_DIMENSION:
        errors.append(
            f"production requires vector_engine.dimension={_PRODUCTION_DIMENSION}, "
            f"got {config.vector_engine.dimension}"
        )

    # 禁止 mock / kylin_mock / faiss 进入生产配置
    forbidden = {"mock", "kylin_mock", "faiss", "milvus_mock"}
    if config.embedding.provider in forbidden:
        errors.append(
            f"embedding provider {config.embedding.provider!r} is not allowed in production"
        )
    if config.vector_engine.provider in forbidden:
        errors.append(
            f"vector_engine provider {config.vector_engine.provider!r} is not allowed in production"
        )

    if errors:
        raise ProductionGateError("; ".join(errors))


def validate_production_runtime(
    config: AppConfig,
    embedding_client: object,
    vector_engine: object,
) -> None:
    """生产模式运行时门禁：校验 SDK/引擎可用性与实际输出维度。"""
    if not config.runtime.is_production:
        return

    errors: list[str] = []

    # Embedding SDK 可加载且会话可初始化
    available = getattr(embedding_client, "is_available", None)
    if available is None or not available():
        errors.append("embedding client is not available (SO load or session init failed)")

    # 实际输出维度为 768
    get_dim = getattr(embedding_client, "get_dimension", None)
    if callable(get_dim):
        actual_dim = get_dim()
        if actual_dim != _PRODUCTION_DIMENSION:
            errors.append(
                f"embedding actual dimension is {actual_dim}, expected {_PRODUCTION_DIMENSION}"
            )

    # 向量引擎 C API 可加载且已连接 Milvus
    connected = getattr(vector_engine, "_connected", None)
    closed = getattr(vector_engine, "_closed", None)
    if connected is None or not connected:
        errors.append("vector engine is not connected to Milvus")
    if closed is True:
        errors.append("vector engine is closed")

    if errors:
        raise ProductionGateError("; ".join(errors))


@dataclass
class AppConfig:
    """应用总配置"""

    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    vector_engine: VectorEngineConfig = field(default_factory=VectorEngineConfig)
    extraction_retry: ExtractionRetryConfig = field(default_factory=ExtractionRetryConfig)
    knowledge_merge: KnowledgeMergeConfig = field(default_factory=KnowledgeMergeConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    debug: bool = False
    # Populated by load_config so management APIs can persist selected settings.
    config_path: str = field(default="", repr=False)


def load_config(config_path: str | None = None) -> AppConfig:
    """加载配置，优先从 YAML 配置文件读取，其次从环境变量覆盖"""
    import os
    from pathlib import Path

    config = AppConfig()

    # 尝试从 YAML 配置文件加载
    search_paths = [
        config_path,
        os.environ.get("MEMORYHUB_CONFIG", ""),
        "config.yaml",
    ]
    yaml_path = None
    for p in search_paths:
        if p and Path(p).exists():
            yaml_path = str(p)
            break

    if yaml_path:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("PyYAML is required to load configuration files") from exc

        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"invalid configuration file {yaml_path}: {exc}") from exc

        if not isinstance(data, Mapping):
            raise ValueError(f"configuration root in {yaml_path} must be a mapping")

        def section(name: str) -> Mapping:
            value = data.get(name, {})
            if not isinstance(value, Mapping):
                raise ValueError(f"configuration section {name!r} must be a mapping")
            return value

        try:
            config.runtime = RuntimeConfig(
                **{**config.runtime.__dict__, **section("runtime")}
            )
            config.storage = StorageConfig(
                **{**config.storage.__dict__, **section("storage")}
            )
            config.retrieval = RetrievalConfig(
                **{**config.retrieval.__dict__, **section("retrieval")}
            )
            llm_data = dict(section("llm"))
            # The service uses a cloud OpenAI-compatible API exclusively.
            # Ignore the retired provider selector while migrating existing YAML files.
            llm_data.pop("provider", None)
            config.llm = LLMConfig(**{**config.llm.__dict__, **llm_data})
            config.embedding = EmbeddingConfig(
                **{**config.embedding.__dict__, **section("embedding")}
            )
            config.vector_engine = VectorEngineConfig(
                **{**config.vector_engine.__dict__, **section("vector_engine")}
            )
            config.extraction_retry = ExtractionRetryConfig(
                **{**config.extraction_retry.__dict__, **section("extraction_retry")}
            )
            config.knowledge_merge = KnowledgeMergeConfig(
                **{**config.knowledge_merge.__dict__, **section("knowledge_merge")}
            )
            if section("safety"):
                config.safety = SafetyConfig(**dict(section("safety")))
        except TypeError as exc:
            raise ValueError(f"invalid configuration in {yaml_path}: {exc}") from exc
        if "debug" in data:
            config.debug = bool(data["debug"])
        config.config_path = str(Path(yaml_path).resolve())

    # 环境变量覆盖
    if os.environ.get("MEMORYHUB_RUNTIME_MODE"):
        config.runtime.mode = os.environ["MEMORYHUB_RUNTIME_MODE"]
    if os.environ.get("MEMORYHUB_RUNTIME_ALLOW_FALLBACK"):
        config.runtime.allow_fallback = os.environ[
            "MEMORYHUB_RUNTIME_ALLOW_FALLBACK"
        ].lower() in ("1", "true", "yes")
    # 环境变量可能绕过 dataclass __post_init__，重新构造以校验 runtime.mode
    config.runtime = RuntimeConfig(
        mode=config.runtime.mode, allow_fallback=config.runtime.allow_fallback
    )
    if os.environ.get("MEMORYHUB_DB_PATH"):
        config.storage.db_path = os.environ["MEMORYHUB_DB_PATH"]
    if os.environ.get("MEMORYHUB_DEBUG"):
        config.debug = os.environ["MEMORYHUB_DEBUG"].lower() in ("1", "true", "yes")
    if os.environ.get("MEMORYHUB_EMBEDDING_PROVIDER"):
        config.embedding.provider = os.environ["MEMORYHUB_EMBEDDING_PROVIDER"]
    if os.environ.get("MEMORYHUB_VECTOR_ENGINE_PROVIDER"):
        config.vector_engine.provider = os.environ["MEMORYHUB_VECTOR_ENGINE_PROVIDER"]
    if "MEMORYHUB_VECTOR_ENGINE_APP_ID" in os.environ:
        config.vector_engine.app_id = os.environ["MEMORYHUB_VECTOR_ENGINE_APP_ID"]
    # Prefer the portable LLM_API_* names used by desktop configuration;
    # retain MEMORYHUB_* aliases for deployed service compatibility.
    if os.environ.get("LLM_API_BASE") or os.environ.get("MEMORYHUB_LLM_API_BASE"):
        config.llm.api_base = os.environ.get("LLM_API_BASE") or os.environ["MEMORYHUB_LLM_API_BASE"]
    if os.environ.get("LLM_API_KEY") or os.environ.get("MEMORYHUB_LLM_API_KEY"):
        config.llm.api_key = os.environ.get("LLM_API_KEY") or os.environ["MEMORYHUB_LLM_API_KEY"]
    if os.environ.get("LLM_MODEL") or os.environ.get("MEMORYHUB_LLM_MODEL"):
        config.llm.model = os.environ.get("LLM_MODEL") or os.environ["MEMORYHUB_LLM_MODEL"]

    # 环境变量覆盖后重新构造，以执行 provider/app_id 契约校验。
    config.vector_engine = VectorEngineConfig(**config.vector_engine.__dict__)

    # 生产模式静态门禁必须在环境变量覆盖后执行
    validate_production_gate(config)

    return config
