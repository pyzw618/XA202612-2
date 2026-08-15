"""
核心数据结构定义 — 全系统共享的 Pydantic 模型

所有模块间传递的数据都基于这里定义的模型，
修改任何字段必须同步更新 docs/INTERFACE.md。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializationInfo,
    SerializeAsAny,
    field_serializer,
    field_validator,
    model_validator,
)

# ============================================================
# 1. 枚举类型
# ============================================================


class SourceType(str, Enum):
    """接入来源大类；来源内的具体动作由 event_type 描述。"""

    TOOL_RESULT = "tool_result"
    USER_BEHAVIOR = "user_behavior"
    MANUAL_CONFIG = "manual_config"


class QualityStatus(str, Enum):
    """接入质量状态及其下游处理策略。"""

    ACCEPTED = "accepted"
    REVIEW = "review"
    REJECTED = "rejected"


class ToolCallStatus(str, Enum):
    """单次工具调用的执行状态。"""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class PreferenceType(str, Enum):
    """偏好类型"""

    OUTPUT_STYLE = "output_style"  # 输出风格偏好
    TOOL_PREFERENCE = "tool_preference"  # 工具选择偏好
    WORKFLOW_PREF = "workflow_preference"  # 操作流程偏好
    SAFETY_PREF = "safety_preference"  # 安全策略偏好
    SCENE_PREF = "scene_preference"  # 场景偏好
    FORMAT_PREF = "format_preference"  # 格式偏好
    LANGUAGE_PREF = "language_preference"  # 语言偏好


class KnowledgeType(str, Enum):
    """知识类型"""

    WORKFLOW = "workflow"  # 工作流知识
    CASE = "case"  # 历史案例
    TEMPLATE = "template"  # 可复用模板


class MemoryLevel(str, Enum):
    """记忆层级"""

    SHORT = "short"  # 短期：当前任务内
    MID = "mid"  # 中期：几天到几周
    LONG = "long"  # 长期：持久保存


class ConflictDecision(str, Enum):
    """冲突处理决策"""

    OVERRIDE = "override"  # 覆盖旧记忆
    MERGE = "merge"  # 合并新旧
    COEXIST = "coexist"  # 按场景并存
    PENDING = "pending"  # 待用户确认


class MemoryDecision(str, Enum):
    """统一 Domain Writer 使用的记忆状态迁移动作。"""

    NEW = "new"
    REINFORCE = "reinforce"
    REVISE = "revise"
    SUPERSEDE = "supersede"
    COEXIST = "coexist"
    DUPLICATE = "duplicate"
    REVIEW = "review"
    REJECT = "reject"


class MemoryStatus(str, Enum):
    """记忆状态"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    PENDING = "pending"


class SensitiveLevel(str, Enum):
    """敏感等级；只表达风险，不直接决定处理动作。"""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SafetyAction(str, Enum):
    """安全策略可输出的处理动作。"""

    ALLOW = "allow"
    MASK = "mask"
    REVIEW = "review"
    REJECT = "reject"


class SafetyFindingTarget(str, Enum):
    """Finding 的定位方式；整值命中不伪造不存在的字符串区间。"""

    TEXT_SPAN = "text_span"
    WHOLE_VALUE = "whole_value"


_NON_EXCEPTIONABLE_REPORT_PATHS = frozenset(
    {
        "/event_id",
        "/event_type",
        "/scene",
        "/task_type",
    }
)


# ============================================================
# 2. 基础模型
# ============================================================


class SceneScope(BaseModel):
    """场景作用域 — 记忆在什么场景下生效"""

    scene: str = ""  # 大场景，如 "office", "code", "chat"
    task_type: str = ""  # 任务类型，如 "office.weekly_report"
    app: str = ""  # 来源应用，如 "os_agent"


class Evidence(BaseModel):
    """证据链 — 记忆的来源依据"""

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_id: str = ""  # 关联的事件 ID
    content: str = ""  # 证据内容摘要
    source_type: SourceType = SourceType.TOOL_RESULT
    timestamp: datetime = Field(default_factory=datetime.now)
    weight: float = 1.0  # 该证据的权重
    decision: ConflictDecision | None = None  # 如 OVERRIDE, MERGE, COEXIST, PENDING 或 None


class MemoryProvenance(BaseModel):
    """一次获批写入的可审计来源信息，不保存隔离区原文。"""

    event_id: str = Field(min_length=1)
    source_hash: str = Field(min_length=1, max_length=64)
    source_type: SourceType
    safety_audit_id: str | None = None
    safety_review_id: str | None = None
    safety_action: SafetyAction | None = None


class MemoryWriteReceipt(BaseModel):
    """Domain Writer 对一次记忆状态迁移返回的统一回执。"""

    receipt_id: str = Field(default_factory=lambda: f"receipt_{uuid.uuid4().hex}")
    memory_id: str = Field(min_length=1)
    memory_type: str = Field(min_length=1, max_length=16)
    action: MemoryDecision
    lineage_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    outbox_id: str | None = None
    provenance: MemoryProvenance
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 3. 事件模型（接入层输出）
# ============================================================


class ToolCallResult(BaseModel):
    """一次工具调用及其结果；同一事件中的 sequence 表示调用顺序。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    status: ToolCallStatus
    sequence: int = Field(ge=1)
    error: str = ""


class EventQuality(BaseModel):
    """清洗、标准化后随事件输出的质量评分明细。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    score: float = Field(ge=0.0, le=1.0)
    status: QualityStatus
    completeness: float = Field(ge=0.0, le=1.0)
    validity: float = Field(ge=0.0, le=1.0)
    consistency: float = Field(ge=0.0, le=1.0)
    freshness: float = Field(ge=0.0, le=1.0)
    issues: list[str] = Field(default_factory=list)


class MemoryEvent(BaseModel):
    """
    统一事件模型 — 所有多源数据进入系统后的标准格式

    数据流：原始数据 → Ingestion 清洗/标准化/评分 → MemoryEvent → 存储/抽取

    顶层放跨来源共享字段和强类型工具轨迹；其余来源特有字段放入 payload。
    旧版 content/timestamp/source/quality_score 等字段不再属于本模型。
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    event_id: str = Field(min_length=1)
    source_type: SourceType
    event_type: str = Field(min_length=1)
    user_id: str = ""
    session_id: str = ""
    turn_id: str = ""  # 同一轮 Agent 调用链的关联 ID
    scene: str = ""
    task_type: str = ""
    occurred_at: str = ""
    text: str = ""  # 最终回答或摘要，不替代 tool_calls 中的原始结果
    payload: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    schema_version: Literal["1.0", "1.1"] = "1.1"
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    redactions: list[str] = Field(default_factory=list)
    quality: EventQuality

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        """非空事件时间必须是秒精度的 UTC ISO 8601 字符串。"""
        if not value:
            return value
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ValueError(
                "occurred_at must use YYYY-MM-DDTHH:MM:SSZ or be empty"
            ) from exc
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise ValueError("occurred_at must use YYYY-MM-DDTHH:MM:SSZ or be empty")
        return value

    @model_validator(mode="after")
    def validate_accepted_event(self) -> "MemoryEvent":
        """accepted 事件必须具备可进入记忆链路的身份、时间和 payload。"""
        if self.quality.status is QualityStatus.ACCEPTED:
            missing = []
            if not self.user_id:
                missing.append("user_id")
            if not self.occurred_at:
                missing.append("occurred_at")
            if not self.payload and not self.tool_calls:
                missing.append("payload or tool_calls")
            if missing:
                raise ValueError(
                    "accepted event is missing required fields: " + ", ".join(missing)
                )
        if self.source_type is not SourceType.TOOL_RESULT and self.tool_calls:
            raise ValueError("tool_calls are only valid for source_type=tool_result")
        if (
            self.schema_version == "1.1"
            and self.source_type is SourceType.TOOL_RESULT
            and not self.tool_calls
        ):
            raise ValueError(
                "schema 1.1 tool_result event requires at least one tool call result"
            )
        if self.event_type == "agent_response":
            if not self.turn_id:
                raise ValueError("agent_response requires turn_id")
            if not self.text:
                raise ValueError("agent_response requires final answer in text")
            if not self.tool_calls:
                raise ValueError(
                    "agent_response requires at least one tool call result"
                )
        if self.tool_calls:
            call_ids = [call.call_id for call in self.tool_calls]
            sequences = [call.sequence for call in self.tool_calls]
            if len(call_ids) != len(set(call_ids)):
                raise ValueError(
                    "tool_calls.call_id values must be unique within an event"
                )
            if len(sequences) != len(set(sequences)):
                raise ValueError(
                    "tool_calls.sequence values must be unique within an event"
                )
            if sequences != sorted(sequences):
                raise ValueError("tool_calls must be ordered by ascending sequence")
        return self


class _ImmutableMapping(Mapping[str, Any]):
    """不继承 dict，避免通过 ``dict.__setitem__`` 绕过只读边界。"""

    __slots__ = ("_data",)
    _data: Mapping[str, Any]

    def __init__(self, value: Mapping[str, Any]):
        object.__setattr__(self, "_data", MappingProxyType(dict(value)))

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("safe event mappings are immutable")


def _deep_freeze_json(value: Any) -> Any:
    """把已通过 MemoryEvent 校验的 JSON 兼容树递归冻结。"""

    if isinstance(value, Mapping):
        return _ImmutableMapping(
            {key: _deep_freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_json(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze_json(item) for item in value)
    return value


def _deep_thaw_json(value: Any) -> Any:
    """把内部只读树投影回普通 JSON 容器，供 Pydantic 稳定序列化。"""

    if isinstance(value, Mapping):
        return {key: _deep_thaw_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_deep_thaw_json(item) for item in value]
    return value


class _SafeToolCallResult(ToolCallResult):
    """SafetyResult 内部使用的深度只读工具调用副本。"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def freeze_containers(self) -> "_SafeToolCallResult":
        object.__setattr__(self, "arguments", _deep_freeze_json(self.arguments))
        object.__setattr__(self, "result", _deep_freeze_json(self.result))
        return self

    @field_serializer("arguments", "result")
    def serialize_containers(self, value: Any) -> Any:
        return _deep_thaw_json(value)


class _SafeEventQuality(EventQuality):
    """SafetyResult 内部使用的深度只读质量信息副本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def freeze_issues(self) -> "_SafeEventQuality":
        object.__setattr__(self, "issues", tuple(self.issues))
        return self

    @field_serializer("issues")
    def serialize_issues(self, value: Any) -> list[str]:
        return list(value)


class _SafeMemoryEvent(MemoryEvent):
    """只在安全结果边界暴露的深度只读 MemoryEvent 快照。"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    @model_validator(mode="after")
    def freeze_containers(self) -> "_SafeMemoryEvent":
        safe_calls = tuple(
            _SafeToolCallResult.model_validate(call.model_dump(mode="python"))
            for call in self.tool_calls
        )
        safe_quality = _SafeEventQuality.model_validate(
            self.quality.model_dump(mode="python")
        )
        object.__setattr__(self, "payload", _deep_freeze_json(self.payload))
        object.__setattr__(self, "tool_calls", safe_calls)
        object.__setattr__(self, "redactions", _deep_freeze_json(self.redactions))
        object.__setattr__(self, "quality", safe_quality)
        return self

    @field_serializer("payload")
    def serialize_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        return _deep_thaw_json(value)

    @field_serializer("tool_calls")
    def serialize_tool_calls(
        self,
        value: list[ToolCallResult],
        info: SerializationInfo,
    ) -> list[dict[str, Any]]:
        return [call.model_dump(mode=info.mode) for call in value]

    @field_serializer("redactions")
    def serialize_redactions(self, value: list[str]) -> list[str]:
        return list(value)

    @field_serializer("quality")
    def serialize_quality(
        self,
        value: EventQuality,
        info: SerializationInfo,
    ) -> dict[str, Any]:
        payload = {name: getattr(value, name) for name in EventQuality.model_fields}
        payload["issues"] = list(value.issues)
        return EventQuality.model_validate(payload).model_dump(mode=info.mode)


# ============================================================
# 4. 安全检测契约
# ============================================================


def _utc_now() -> datetime:
    """返回带 UTC 时区的时间，供安全报告和审计记录使用。"""
    return datetime.now(timezone.utc)


def canonical_sha256(value: Any) -> str:
    """按接口契约的 canonical JSON 规则计算小写 SHA-256。"""
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class SensitiveRule(BaseModel):
    """一条可版本化、可审计的敏感信息检测规则。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    version: str = Field(default="1.0", min_length=1)
    pattern: str = Field(min_length=1)
    level: SensitiveLevel
    action: SafetyAction
    reason_code: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_.-]*$")
    reason: str = Field(min_length=1)
    standard_source: str = Field(min_length=1)
    replacement: str = "[REDACTED]"
    match_group: int | str = 0
    path_pattern: str = ""
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        """规则不得无效或匹配空字符串，避免扫描器无法前进。"""
        try:
            compiled = re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid sensitive rule pattern: {exc}") from exc
        if compiled.search("") is not None:
            raise ValueError("sensitive rule pattern must not match an empty string")
        return value

    @field_validator("path_pattern")
    @classmethod
    def validate_path_pattern(cls, value: str) -> str:
        """可选路径约束使用正则表达式匹配 RFC 6901 JSON Pointer。"""
        if not value:
            return value
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid sensitive rule path_pattern: {exc}") from exc
        return value

    @field_validator("match_group", mode="before")
    @classmethod
    def validate_match_group_type(cls, value: Any) -> int | str:
        """拒绝 bool/float 等会被 Pydantic 隐式转换的捕获组类型。"""
        if type(value) not in (int, str):
            raise ValueError("match_group must be an int or str")
        return value

    @model_validator(mode="after")
    def validate_match_group_and_replacement(self) -> "SensitiveRule":
        """捕获组必须存在；MASK 规则必须提供非空替换文本。"""
        compiled = re.compile(self.pattern)
        if isinstance(self.match_group, int):
            if self.match_group < 0 or self.match_group > compiled.groups:
                raise ValueError("match_group index does not exist in pattern")
        elif self.match_group not in compiled.groupindex:
            raise ValueError("named match_group does not exist in pattern")
        if self.action is SafetyAction.MASK and not self.replacement:
            raise ValueError("MASK rule requires a non-empty replacement")
        if self.enabled and self.level is SensitiveLevel.NONE:
            raise ValueError("enabled sensitive rule cannot use level NONE")
        if self.enabled and self.action is SafetyAction.ALLOW:
            raise ValueError(
                "enabled sensitive rule cannot ALLOW; use a governed policy exception"
            )
        return self


class SafetyFinding(BaseModel):
    """
    单次规则命中。

    field_path 使用 RFC 6901 JSON Pointer。TEXT_SPAN 的 start/end 是原始
    叶子字符串中的 Unicode 字符半开区间 [start, end)；WHOLE_VALUE 用于
    路径规则命中的非字符串节点，并固定使用 [0, 0)。本模型不得保存命中原文。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(default_factory=lambda: f"finding_{uuid.uuid4().hex[:12]}")
    rule_name: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    level: SensitiveLevel
    suggested_action: SafetyAction
    field_path: str = Field(min_length=1)
    target: SafetyFindingTarget = SafetyFindingTarget.TEXT_SPAN
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    replacement: str = "[REDACTED]"
    maskable: bool = True
    reason_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    standard_source: str = Field(min_length=1)

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str) -> str:
        """只接受绝对 RFC 6901 JSON Pointer，并校验 ~ 转义。"""
        if re.fullmatch(r"(?:/(?:[^~/]|~[01])*)+", value) is None:
            raise ValueError("field_path must be an absolute RFC 6901 JSON Pointer")
        return value

    @model_validator(mode="after")
    def validate_span(self) -> "SafetyFinding":
        """文本区间必须非空；整值命中必须使用无歧义的零区间。"""
        if self.target is SafetyFindingTarget.TEXT_SPAN and self.end <= self.start:
            raise ValueError("text-span finding end must be greater than start")
        if self.target is SafetyFindingTarget.WHOLE_VALUE and (
            self.start != 0 or self.end != 0
        ):
            raise ValueError("whole-value finding must use start=end=0")
        if (
            self.suggested_action is SafetyAction.MASK
            and self.maskable
            and not self.replacement
        ):
            raise ValueError("maskable MASK finding requires a non-empty replacement")
        return self


class SafetyDecisionContext(BaseModel):
    """扫描时绑定的非正文策略上下文；供作用域化例外做确定性匹配。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: SourceType | None = None
    event_type: str = ""
    scene: str = ""
    task_type: str = ""


class SafetyReport(BaseModel):
    """一次规则快照对一条 MemoryEvent 的结构化扫描结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(default_factory=lambda: f"report_{uuid.uuid4().hex[:12]}")
    event_id: str = Field(min_length=1)
    event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scanned_at: datetime = Field(default_factory=_utc_now)
    rule_set_version: str = Field(min_length=1)
    rule_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    context: SafetyDecisionContext = Field(default_factory=SafetyDecisionContext)
    context_digest: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")
    attestation: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")
    findings: tuple[SafetyFinding, ...] = Field(default_factory=tuple)
    highest_level: SensitiveLevel = SensitiveLevel.NONE
    scanned_field_count: int = Field(default=0, ge=0)
    scan_complete: bool = True
    issues: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("scanned_at")
    @classmethod
    def validate_scanned_at(cls, value: datetime) -> datetime:
        """扫描时间必须带时区，避免本地时间产生歧义。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scanned_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_highest_level(self) -> "SafetyReport":
        """highest_level 必须与 findings 一致。"""
        expected_context_digest = canonical_sha256(
            {
                "event_digest": self.event_digest,
                "context": self.context.model_dump(mode="json"),
            }
        )
        if self.context_digest and self.context_digest != expected_context_digest:
            raise ValueError("context_digest does not match report context")
        object.__setattr__(self, "context_digest", expected_context_digest)

        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding_id values must be unique within a report")
        if self.scanned_field_count == 0:
            raise ValueError("report must have scanned_field_count >= 1")
        if self.scan_complete != (not self.issues):
            raise ValueError("scan_complete must equal the absence of issues")
        if len(self.issues) != len(set(self.issues)):
            raise ValueError("report issues must be unique")
        rank = {
            SensitiveLevel.NONE: 0,
            SensitiveLevel.LOW: 1,
            SensitiveLevel.MEDIUM: 2,
            SensitiveLevel.HIGH: 3,
        }
        expected = SensitiveLevel.NONE
        if self.findings:
            expected = max(
                (finding.level for finding in self.findings),
                key=lambda level: rank[level],
            )
        if self.highest_level is not expected:
            raise ValueError("highest_level does not match findings")
        return self


class SafetyRuleOverride(BaseModel):
    """对指定规则动作的不可变策略覆盖。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_name: str = Field(min_length=1)
    action: SafetyAction


class SafetyLevelOverride(BaseModel):
    """对指定敏感等级动作的不可变策略覆盖。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    level: SensitiveLevel
    action: SafetyAction


class SafetyExceptionScope(BaseModel):
    """
    有限期策略例外的作用域。

    rule_names 必填；其余维度至少填写一项。各维度之间按 AND 匹配，
    同一维度中的多个值按 OR 匹配。task_types 承载当前事件契约中的用途。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_names: tuple[str, ...] = Field(min_length=1)
    source_types: tuple[SourceType, ...] = Field(default_factory=tuple)
    event_types: tuple[str, ...] = Field(default_factory=tuple)
    scenes: tuple[str, ...] = Field(default_factory=tuple)
    task_types: tuple[str, ...] = Field(default_factory=tuple)
    field_paths: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator(
        "rule_names",
        "event_types",
        "scenes",
        "task_types",
    )
    @classmethod
    def validate_non_empty_unique_strings(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("exception scope values must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("exception scope values must be unique")
        return normalized

    @field_validator("source_types")
    @classmethod
    def validate_unique_source_types(
        cls,
        value: tuple[SourceType, ...],
    ) -> tuple[SourceType, ...]:
        if len(value) != len(set(value)):
            raise ValueError("exception source_types must be unique")
        return value

    @field_validator("field_paths")
    @classmethod
    def validate_field_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("exception field_paths must be unique")
        for path in value:
            if re.fullmatch(r"(?:/(?:[^~/]|~[01])*)+", path) is None:
                raise ValueError(
                    "exception field_paths must be absolute RFC 6901 JSON Pointers"
                )
        return value

    @model_validator(mode="after")
    def validate_contextual_scope(self) -> "SafetyExceptionScope":
        if not any(
            (
                self.source_types,
                self.event_types,
                self.scenes,
                self.task_types,
                self.field_paths,
            )
        ):
            raise ValueError(
                "exception scope requires at least one contextual selector"
            )
        return self


class SafetyPolicyException(BaseModel):
    """带治理元数据和失效时间的作用域化 ALLOW 例外。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exception_id: str = Field(
        min_length=1,
        pattern=r"^[a-z][a-z0-9_.-]*$",
    )
    version: str = Field(min_length=1)
    scope: SafetyExceptionScope
    reason: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    expires_at: datetime
    valid_from: datetime | None = None
    rule_set_digest: str = Field(
        default="",
        pattern=r"^(?:[0-9a-f]{64})?$",
    )
    action: Literal[SafetyAction.ALLOW] = SafetyAction.ALLOW
    enabled: bool = True

    @field_validator("version", "reason", "owner")
    @classmethod
    def validate_governance_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("exception governance text must not be blank")
        return normalized

    @field_validator("expires_at", "valid_from")
    @classmethod
    def validate_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("exception validity timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_validity_window(self) -> "SafetyPolicyException":
        if self.valid_from is not None and self.expires_at <= self.valid_from:
            raise ValueError("exception expires_at must be after valid_from")
        return self


class SafetyPolicy(BaseModel):
    """
    安全决策策略。

    规则级覆盖优先于等级覆盖；无覆盖时采用 Finding 的 suggested_action。
    多个 Finding 的聚合优先级固定为 REJECT > REVIEW > MASK > ALLOW。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(default="default", min_length=1)
    version: str = Field(default="1.0", min_length=1)
    rule_overrides: tuple[SafetyRuleOverride, ...] = Field(default_factory=tuple)
    level_overrides: tuple[SafetyLevelOverride, ...] = Field(default_factory=tuple)
    exceptions: tuple[SafetyPolicyException, ...] = Field(default_factory=tuple)
    fallback_action: SafetyAction = SafetyAction.REVIEW
    on_scan_error: SafetyAction = SafetyAction.REVIEW
    on_unmaskable: SafetyAction = SafetyAction.REVIEW
    auto_sanitize: bool = True
    fail_closed: bool = True

    @model_validator(mode="after")
    def validate_overrides_and_fail_closed_actions(self) -> "SafetyPolicy":
        """覆盖目标必须唯一，fail-closed 失败分支不得放行。"""
        rule_names = [override.rule_name for override in self.rule_overrides]
        if len(rule_names) != len(set(rule_names)):
            raise ValueError("rule_overrides must have unique rule_name values")
        levels = [override.level for override in self.level_overrides]
        if len(levels) != len(set(levels)):
            raise ValueError("level_overrides must have unique level values")
        has_allow_override = any(
            override.action is SafetyAction.ALLOW for override in self.rule_overrides
        ) or any(
            override.action is SafetyAction.ALLOW for override in self.level_overrides
        )
        if has_allow_override:
            raise ValueError(
                "ALLOW overrides require a governed scoped policy exception"
            )
        exception_ids = [exception.exception_id for exception in self.exceptions]
        if len(exception_ids) != len(set(exception_ids)):
            raise ValueError("policy exceptions must have unique exception_id values")
        if self.fail_closed:
            blocking_actions = (SafetyAction.REVIEW, SafetyAction.REJECT)
            if self.on_scan_error not in blocking_actions:
                raise ValueError("fail_closed scan errors must REVIEW or REJECT")
            if self.on_unmaskable not in blocking_actions:
                raise ValueError(
                    "fail_closed unmaskable findings must REVIEW or REJECT"
                )
        return self


class SafetyFindingDecision(BaseModel):
    """策略对单个 Finding 给出的有效动作。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1)
    action: SafetyAction
    reason_code: str = Field(min_length=1)


class SafetyDecision(BaseModel):
    """策略对 SafetyReport 的最终决策。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str = Field(min_length=1)
    action: SafetyAction
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    finding_decisions: tuple[SafetyFindingDecision, ...] = Field(default_factory=tuple)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    exception_ids: tuple[str, ...] = Field(default_factory=tuple)
    reason: str = ""
    decided_at: datetime = Field(default_factory=_utc_now)

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        """决策时间必须带时区。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("decided_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_finding_decisions(self) -> "SafetyDecision":
        """同一 Finding 在最终决策中只能出现一次。"""
        finding_ids = [finding.finding_id for finding in self.finding_decisions]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding decisions must have unique finding_id values")
        if len(self.exception_ids) != len(set(self.exception_ids)):
            raise ValueError("decision exception_ids must be unique")
        if self.finding_decisions:
            precedence = {
                SafetyAction.ALLOW: 0,
                SafetyAction.MASK: 1,
                SafetyAction.REVIEW: 2,
                SafetyAction.REJECT: 3,
            }
            expected = max(
                (finding.action for finding in self.finding_decisions),
                key=lambda action: precedence[action],
            )
            if self.action is not expected:
                raise ValueError(
                    "decision action must aggregate effective finding actions"
                )
        elif self.action is SafetyAction.MASK:
            raise ValueError("MASK decision requires at least one finding decision")
        if (
            self.finding_decisions
            and self.action is SafetyAction.ALLOW
            and not self.exception_ids
        ):
            raise ValueError(
                "ALLOW findings require at least one governed policy exception"
            )
        return self


class SafetyAuditFinding(BaseModel):
    """可持久化的命中摘要；有定位信息，但不含原始命中值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=1)
    rule_name: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    level: SensitiveLevel
    field_path: str = Field(min_length=1)
    target: SafetyFindingTarget = SafetyFindingTarget.TEXT_SPAN
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    reason_code: str = Field(min_length=1)
    standard_source: str = Field(min_length=1)

    @field_validator("field_path")
    @classmethod
    def validate_field_path(cls, value: str) -> str:
        """审计路径沿用 SafetyFinding 的 RFC 6901 约束。"""
        if re.fullmatch(r"(?:/(?:[^~/]|~[01])*)+", value) is None:
            raise ValueError("field_path must be an absolute RFC 6901 JSON Pointer")
        return value

    @model_validator(mode="after")
    def validate_span(self) -> "SafetyAuditFinding":
        """审计定位必须与文本片段或整值语义一致。"""
        if self.target is SafetyFindingTarget.TEXT_SPAN and self.end <= self.start:
            raise ValueError("text-span audit finding end must be greater than start")
        if self.target is SafetyFindingTarget.WHOLE_VALUE and (
            self.start != 0 or self.end != 0
        ):
            raise ValueError("whole-value audit finding must use start=end=0")
        return self


class SafetyAuditRecord(BaseModel):
    """安全处理审计记录，不包含 MemoryEvent 正文或命中原文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_id: str = Field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:12]}")
    report_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_set_version: str = Field(min_length=1)
    rule_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_action: SafetyAction
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    exception_ids: tuple[str, ...] = Field(default_factory=tuple)
    findings: tuple[SafetyAuditFinding, ...] = Field(default_factory=tuple)
    redaction_types: tuple[str, ...] = Field(default_factory=tuple)
    processing_time_ms: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    created_at: datetime = Field(default_factory=_utc_now)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """审计时间必须带时区。"""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_findings(self) -> "SafetyAuditRecord":
        """审计记录中每个 Finding 只能出现一次。"""
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("audit findings must have unique finding_id values")
        if len(self.exception_ids) != len(set(self.exception_ids)):
            raise ValueError("audit exception_ids must be unique")
        return self


class SafetyResult(BaseModel):
    """
    一次原子安全处理的完整结果。

    sanitized_event 仅表示已生成脱敏副本；是否允许进入普通存储、Embedding
    和日志链路仍以 decision.action 为准。
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    report: SafetyReport
    decision: SafetyDecision
    audit: SafetyAuditRecord
    sanitized_event: SerializeAsAny[MemoryEvent] | None = None
    verification_report: SafetyReport | None = None
    attestation: str = Field(default="", pattern=r"^(?:[0-9a-f]{64})?$")

    @field_validator("report", "verification_report", mode="before")
    @classmethod
    def revalidate_reports(
        cls,
        value: SafetyReport | dict[str, Any] | None,
    ) -> SafetyReport | None:
        """跨结果边界重建报告，避免 model_copy(update=...) 绕过不变量。"""
        if value is None:
            return None
        payload = (
            value.model_dump(mode="python") if isinstance(value, BaseModel) else value
        )
        return SafetyReport.model_validate(payload)

    @field_validator("decision", mode="before")
    @classmethod
    def revalidate_decision(
        cls,
        value: SafetyDecision | dict[str, Any],
    ) -> SafetyDecision:
        payload = (
            value.model_dump(mode="python") if isinstance(value, BaseModel) else value
        )
        return SafetyDecision.model_validate(payload)

    @field_validator("audit", mode="before")
    @classmethod
    def revalidate_audit(
        cls,
        value: SafetyAuditRecord | dict[str, Any],
    ) -> SafetyAuditRecord:
        payload = (
            value.model_dump(mode="python") if isinstance(value, BaseModel) else value
        )
        return SafetyAuditRecord.model_validate(payload)

    @field_validator("sanitized_event", mode="before")
    @classmethod
    def freeze_sanitized_event(
        cls,
        value: MemoryEvent | dict[str, Any] | None,
    ) -> MemoryEvent | None:
        """只向下游暴露一份递归不可变、重新校验过的安全事件。"""
        if value is None:
            return None
        payload = (
            value.model_dump(mode="python") if isinstance(value, BaseModel) else value
        )
        try:
            return _SafeMemoryEvent.model_validate(payload)
        except Exception:
            raise ValueError(
                "sanitized event failed safe snapshot validation"
            ) from None

    @model_validator(mode="after")
    def validate_linkage(self) -> "SafetyResult":
        """报告、决策、审计和复检必须属于同一请求快照。"""
        if self.decision.report_id != self.report.report_id:
            raise ValueError("decision does not belong to report")
        if self.audit.report_id != self.report.report_id:
            raise ValueError("audit does not belong to report")
        if self.audit.event_id != self.report.event_id:
            raise ValueError("audit does not belong to report event")
        if self.audit.source_hash != self.report.source_hash:
            raise ValueError("audit source_hash does not match report")
        if self.audit.rule_set_digest != self.report.rule_set_digest:
            raise ValueError("audit must use the report rule snapshot")
        if self.audit.rule_set_version != self.report.rule_set_version:
            raise ValueError("audit rule_set_version does not match report")
        if self.audit.decision_action is not self.decision.action:
            raise ValueError("audit action does not match decision")
        if self.audit.policy_id != self.decision.policy_id:
            raise ValueError("audit policy_id does not match decision")
        if self.audit.policy_version != self.decision.policy_version:
            raise ValueError("audit policy_version does not match decision")
        if self.audit.policy_digest != self.decision.policy_digest:
            raise ValueError("audit must use the decision policy snapshot")
        if self.audit.reason_codes != self.decision.reason_codes:
            raise ValueError("audit reason_codes do not match decision")
        if self.audit.exception_ids != self.decision.exception_ids:
            raise ValueError("audit exception_ids do not match decision")
        if self.decision.decided_at < self.report.scanned_at:
            raise ValueError("decision must not predate its scan report")
        if (
            not self.report.scan_complete
            or self.report.issues
            or self.report.scanned_field_count == 0
        ) and self.decision.action not in (SafetyAction.REVIEW, SafetyAction.REJECT):
            raise ValueError("incomplete scan result must REVIEW or REJECT")
        if (
            self.report.findings
            and self.decision.action is SafetyAction.ALLOW
            and not self.decision.exception_ids
        ):
            raise ValueError("ALLOW findings require governed policy exceptions")
        report_finding_ids = {finding.finding_id for finding in self.report.findings}
        decision_finding_ids = {
            finding.finding_id for finding in self.decision.finding_decisions
        }
        audit_finding_ids = {finding.finding_id for finding in self.audit.findings}
        if decision_finding_ids != report_finding_ids:
            raise ValueError("decision must cover every report finding exactly once")
        if audit_finding_ids != report_finding_ids:
            raise ValueError("audit must summarize every report finding exactly once")
        report_findings = {
            finding.finding_id: finding for finding in self.report.findings
        }
        decision_findings = {
            finding.finding_id: finding for finding in self.decision.finding_decisions
        }
        for audit_finding in self.audit.findings:
            report_finding = report_findings[audit_finding.finding_id]
            expected = (
                report_finding.rule_name,
                report_finding.rule_version,
                report_finding.level,
                report_finding.field_path,
                report_finding.target,
                report_finding.start,
                report_finding.end,
                report_finding.reason_code,
                report_finding.standard_source,
            )
            actual = (
                audit_finding.rule_name,
                audit_finding.rule_version,
                audit_finding.level,
                audit_finding.field_path,
                audit_finding.target,
                audit_finding.start,
                audit_finding.end,
                audit_finding.reason_code,
                audit_finding.standard_source,
            )
            if actual != expected:
                raise ValueError("audit finding does not match report finding")
        if self.sanitized_event is not None:
            if self.sanitized_event.event_id != self.report.event_id:
                raise ValueError("sanitized event does not belong to report")
            if self.sanitized_event.source_hash != self.report.source_hash:
                raise ValueError("sanitized event must preserve source_hash")
        if self.verification_report is not None:
            if self.verification_report.event_id != self.report.event_id:
                raise ValueError("verification report belongs to another event")
            if self.verification_report.source_hash != self.report.source_hash:
                raise ValueError("verification report must preserve source_hash")
            if self.verification_report.rule_set_digest != self.report.rule_set_digest:
                raise ValueError(
                    "verification report must reuse the same rule snapshot"
                )
            if (
                self.verification_report.rule_set_version
                != self.report.rule_set_version
            ):
                raise ValueError("verification report rule_set_version does not match")
            if self.sanitized_event is not None:
                sanitized_digest = canonical_sha256(
                    self.sanitized_event.model_dump(mode="json")
                )
                if self.verification_report.event_digest != sanitized_digest:
                    raise ValueError(
                        "verification report does not match sanitized event"
                    )
                verification_context = SafetyDecisionContext(
                    source_type=self.sanitized_event.source_type,
                    event_type=self.sanitized_event.event_type,
                    scene=self.sanitized_event.scene,
                    task_type=self.sanitized_event.task_type,
                )
                if self.verification_report.context != verification_context:
                    raise ValueError(
                        "verification context does not match sanitized event"
                    )
        if self.decision.action in (SafetyAction.ALLOW, SafetyAction.MASK):
            if self.sanitized_event is None:
                raise ValueError("ALLOW/MASK result requires a safe event")
        elif self.sanitized_event is not None:
            raise ValueError(
                "REVIEW/REJECT result must not expose an event for persistence"
            )
        if (
            self.decision.action is SafetyAction.ALLOW
            and self.sanitized_event is not None
        ):
            allowed_digest = canonical_sha256(
                self.sanitized_event.model_dump(mode="json")
            )
            if allowed_digest != self.report.event_digest:
                raise ValueError("ALLOW event does not match scanned event")
        for finding_id, report_finding in report_findings.items():
            if decision_findings[finding_id].action is not SafetyAction.ALLOW:
                continue
            if not self.decision.exception_ids:
                raise ValueError("ALLOW finding requires a governed policy exception")
            if report_finding.suggested_action is SafetyAction.REJECT:
                raise ValueError(
                    "REJECT finding cannot be downgraded by an ALLOW exception"
                )
            if report_finding.field_path in _NON_EXCEPTIONABLE_REPORT_PATHS:
                raise ValueError(
                    "report metadata finding cannot be downgraded by an ALLOW exception"
                )
            if report_finding.level is not SensitiveLevel.LOW:
                raise ValueError("governed ALLOW exception requires a low-risk finding")
        if (
            self.decision.action is SafetyAction.ALLOW
            and self.sanitized_event is not None
        ):
            safe_context = SafetyDecisionContext(
                source_type=self.sanitized_event.source_type,
                event_type=self.sanitized_event.event_type,
                scene=self.sanitized_event.scene,
                task_type=self.sanitized_event.task_type,
            )
            if safe_context != self.report.context:
                raise ValueError("ALLOW event context does not match scanned context")
        if self.decision.action is SafetyAction.MASK:
            if not self.report.findings:
                raise ValueError("MASK result requires at least one finding")
            if self.verification_report is None:
                raise ValueError("MASK result requires a verification report")
            if not self.verification_report.scan_complete:
                raise ValueError("MASK verification scan must be complete")
            if self.verification_report.scanned_field_count == 0:
                raise ValueError("MASK verification must scan at least one field")
            if self.verification_report.findings:
                raise ValueError("MASK verification must not contain residual findings")
        return self


DEFAULT_SENSITIVE_RULES: tuple[SensitiveRule, ...] = (
    SensitiveRule(
        name="credential_field",
        pattern=r"(?s)\A(?!\[REDACTED_[A-Z0-9_]+\]\Z).+\Z",
        path_pattern=r"(?i)/(?:api[_-]?key|secret|password|token)$",
        level=SensitiveLevel.HIGH,
        action=SafetyAction.REJECT,
        reason_code="secret.credential_field",
        reason="Values stored under credential field names must not enter memory.",
        standard_source="OWASP Secrets Management Cheat Sheet",
        replacement="[REDACTED_CREDENTIAL]",
    ),
    SensitiveRule(
        name="api_key",
        pattern=(
            r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]\s*"
            r"(?P<value>(?!\[REDACTED_[A-Z0-9_]+\](?:\s|$))\S+)"
        ),
        level=SensitiveLevel.HIGH,
        action=SafetyAction.REJECT,
        reason_code="secret.credential",
        reason="Credential material must not enter the memory pipeline.",
        standard_source="OWASP Secrets Management Cheat Sheet",
        replacement="[REDACTED_API_KEY]",
        match_group="value",
    ),
    SensitiveRule(
        name="id_card",
        pattern=r"\b\d{17}[\dXx]\b",
        level=SensitiveLevel.HIGH,
        action=SafetyAction.MASK,
        reason_code="personal.id_card",
        reason="Government identity numbers require redaction.",
        standard_source="GB/T 35273-2020",
        replacement="[REDACTED_ID_CARD]",
    ),
    SensitiveRule(
        name="phone",
        pattern=r"\b1[3-9]\d{9}\b",
        level=SensitiveLevel.MEDIUM,
        action=SafetyAction.MASK,
        reason_code="personal.phone",
        reason="Personal phone numbers require redaction.",
        standard_source="GB/T 35273-2020",
        replacement="[REDACTED_PHONE]",
    ),
    SensitiveRule(
        name="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        level=SensitiveLevel.MEDIUM,
        action=SafetyAction.MASK,
        reason_code="personal.email",
        reason="Personal email addresses require redaction.",
        standard_source="GB/T 35273-2020",
        replacement="[REDACTED_EMAIL]",
    ),
    SensitiveRule(
        name="ip_address",
        pattern=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        level=SensitiveLevel.LOW,
        action=SafetyAction.MASK,
        reason_code="device.ip_address",
        reason="Network identifiers require contextual redaction.",
        standard_source="GB/T 35273-2020",
        replacement="[REDACTED_IP_ADDRESS]",
    ),
)


def default_sensitive_rules() -> list[SensitiveRule]:
    """从 catalog 默认快照返回独立列表，避免配置实例共享可变容器。"""
    from memoryhub.safety_rules import load_builtin_rule_set

    return list(load_builtin_rule_set().compiled_rules)


# ============================================================
# 5. 偏好记忆模型
# ============================================================


class PreferenceMemory(BaseModel):
    """
    偏好记忆 — 记录用户的个性化偏好

    数据流：MemoryEvent (仅限制 source_type == 'user_behavior') 
            → PreferenceExtractor 
            → PreferenceMemory 
            → Storage
    """
    memory_id: str = Field(default_factory=lambda: f"pref_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    memory_type: str = "preference"
    preference_type: PreferenceType = PreferenceType.OUTPUT_STYLE

    # --- 偏好核心内容（与 MemoryEvent 对齐） ---
    text: str = ""                         # 自然语言描述，对齐 MemoryEvent.text
    payload: dict[str, Any] = Field(default_factory=dict) # 结构化表达，如 {"action": "set_format", "target": "weekly_report", "value": "markdown"}
    scope: SceneScope = Field(default_factory=SceneScope)
    is_global: bool = False                # 是否为全局通用偏好（用于跨场景兜底）

    # --- 置信度、质量与状态 ---
    confidence: float = 0.5                # [0, 1] 综合置信度
    quality_score: float = 1.0             # [0, 1] 来源 MemoryEvent 的质量评分
    extract_source: str = "implicit_inference" # 提取来源: explicit_feedback / implicit_inference
    status: MemoryStatus = MemoryStatus.ACTIVE
    level: MemoryLevel = MemoryLevel.MID

    # --- 版本管理链条 ---
    version: int = 1
    parent_id: str = ""                    # 前一版本的 memory_id（版本链指针）
    root_id: str = ""                      # 初代版本的 memory_id（版本树根节点）

    # --- 证据链与检索扩展 ---
    evidences: list[Evidence] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list) # 偏好标签/关键词，用于辅助检索
    extra_payload: dict[str, Any] = Field(default_factory=dict) # 偏好提取/交互过程中的元数据扩展

    # --- 健康度（遗忘模块使用）---
    health_score: float = 1.0  # [0, 1]，越低越容易被遗忘
    stability: float = 1.0  # 记忆稳定性，影响时间衰减半衰期
    last_accessed_at: datetime | None = Field(default=None)
    access_count_30d: int = 0  # 近 30 天被检索/使用次数

    # --- 时间戳 ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 6. 知识记忆模型
# ============================================================


class KnowledgeMemory(BaseModel):
    """
    知识记忆 — 记录可复用的工作流、案例、模板

    数据流：MemoryEvent(trajectory) → KnowledgeExtractor → KnowledgeMemory → Storage
    """

    memory_id: str = Field(default_factory=lambda: f"know_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    memory_type: str = "knowledge"
    knowledge_type: KnowledgeType = KnowledgeType.WORKFLOW

    # --- 知识内容 ---
    name: str = ""  # 知识名称，如 "项目周报生成流程"
    content: str = ""  # 知识描述
    steps: list[str] = Field(default_factory=list)  # 工作流步骤
    tools: list[str] = Field(default_factory=list)  # 涉及的工具链
    template_body: str = ""  # 模板正文（仅 template 类型）
    scope: SceneScope = Field(default_factory=SceneScope)

    # --- 质量指标 ---
    confidence: float = 0.0
    success_count: int = 0  # 成功复用次数
    total_count: int = 0  # 总调用次数
    status: MemoryStatus = MemoryStatus.ACTIVE
    level: MemoryLevel = MemoryLevel.LONG

    # --- 版本管理 ---
    version: int = 1
    parent_id: str = ""

    # --- 证据链 ---
    evidences: list[Evidence] = Field(default_factory=list)

    # --- 健康度（遗忘模块使用）---
    health_score: float = 1.0  # [0, 1]，越低越容易被遗忘
    stability: float = 1.0  # 记忆稳定性，影响时间衰减半衰期
    last_accessed_at: datetime | None = Field(default=None)
    access_count_30d: int = 0  # 近 30 天被检索/使用次数

    # --- 时间戳 ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 7. 冲突记录模型
# ============================================================


class ConflictRecord(BaseModel):
    """
    冲突记录 — 记录新旧记忆之间的冲突及处理结果

    数据流：检测到冲突 → ConflictResolver → ConflictRecord → 更新记忆
    """

    conflict_id: str = Field(default_factory=lambda: f"conf_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    old_memory_id: str = ""
    new_memory_id: str = ""
    memory_type: str = ""  # "preference" | "knowledge" | "fact"

    # --- 冲突内容 ---
    old_content: str = ""
    new_content: str = ""
    conflict_field: str = ""  # 冲突的具体字段

    # --- 处理结果 ---
    decision: ConflictDecision = ConflictDecision.PENDING
    reason: str = ""  # 处理原因说明
    result_memory_id: str = ""  # 处理后产生的新记忆 ID

    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: datetime | None = None


# ============================================================
# 8. 遗忘记录模型
# ============================================================


class ForgetRecord(BaseModel):
    """
    遗忘记录 — 精准遗忘操作的审计日志

    数据流：用户指令 → 遗忘意图解析 → 删除记忆 → 生成 ForgetRecord
    """

    record_id: str = Field(default_factory=lambda: f"forg_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    instruction: str = ""  # 用户原始指令
    target_memory_ids: list[str] = Field(default_factory=list)
    target_scope: SceneScope = Field(default_factory=SceneScope)
    deleted_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 9. 检索相关模型
# ============================================================


class FactMemory(BaseModel):
    """Fact view returned by the main retrieval API."""

    model_config = ConfigDict(from_attributes=True)

    fact_id: str = ""
    user_id: str = "default"
    memory_type: Literal["fact"] = "fact"
    subject_id: str = ""
    predicate_id: str = ""
    object_id: str = ""
    object_value: str = ""
    source_text: str = ""
    source_id: str = ""
    observed_at: str = ""
    confidence: float = 0.0
    status: str = "active"
    version: int = 1
    scope: Literal["global", "project"] = "global"
    project_id: str | None = None
    last_accessed_at: str | None = None
    access_count_30d: int = 0

    @property
    def memory_id(self) -> str:
        return self.fact_id


class SearchRequest(BaseModel):
    """检索请求"""

    user_id: str = "default"
    query: str = ""
    context: SceneScope = Field(default_factory=SceneScope)
    project_id: str = ""
    top_k: int = 5
    memory_types: list[str] = Field(default_factory=list)  # 过滤记忆类型
    min_confidence: float = 0.0


class SearchResult(BaseModel):
    """单条检索结果"""

    memory_id: str = ""
    memory_type: str = ""  # "preference" | "knowledge" | "fact"
    content: str = ""
    score: float = 0.0  # 综合得分
    source: str = ""  # 来源标记："vector" | "keyword" | "metadata"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """检索响应"""

    results: list[SearchResult] = Field(default_factory=list)
    preferences: list[PreferenceMemory] = Field(default_factory=list)
    knowledge: list[KnowledgeMemory] = Field(default_factory=list)
    facts: list[FactMemory] = Field(default_factory=list)
    latency_ms: float = 0.0
    total_count: int = 0


class MemoryContextResponse(BaseModel):
    """可直接注入 Agent system prompt 的记忆上下文。"""

    context: str = ""
    search: SearchResponse = Field(default_factory=SearchResponse)


# ============================================================
# 10. 写入/更新请求模型
# ============================================================


class ExtractionTaskStatus(str, Enum):
    """持久化抽取任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"


class ExtractionType(str, Enum):
    """支持重试的抽取子系统。"""

    PREFERENCE = "preference"
    KNOWLEDGE = "knowledge"
    FACT = "fact"


class ExtractionTask(BaseModel):
    """只保存安全事件引用和稳定错误码，不复制事件正文或异常文本。"""

    task_id: str
    event_id: str
    event_ids: list[str] = Field(default_factory=list)
    user_id: str
    extractor_type: ExtractionType
    status: ExtractionTaskStatus = ExtractionTaskStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    next_retry_at: datetime | None = None
    lease_expires_at: datetime | None = None
    last_error_code: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ExtractionTaskRunRequest(BaseModel):
    """执行当前用户到期抽取任务。"""

    user_id: str = "default"
    limit: int = Field(default=20, ge=1, le=200)


class ExtractionTaskRunResponse(BaseModel):
    """一次显式重试执行结果。"""

    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0


class WriteEventRequest(BaseModel):
    """写入事件请求"""

    events: list[MemoryEvent] = Field(default_factory=list)


class WriteEventResponse(BaseModel):
    """写入事件响应"""

    accepted: int = 0
    rejected: int = 0
    event_ids: list[str] = Field(default_factory=list)
    extraction_failures: int = 0
    retry_tasks_enqueued: int = 0
    retry_queue_failures: int = 0


class FeedbackRequest(BaseModel):
    """用户反馈请求（触发偏好更新）"""

    user_id: str = "default"
    memory_id: str = ""  # 要更新的记忆 ID
    feedback_text: str = ""  # 反馈内容
    action: Literal["update", "confirm", "reject"] = "update"


class ForgetRequest(BaseModel):
    """遗忘请求"""

    user_id: str = "default"
    instruction: str = ""  # 自然语言遗忘指令
    target_memory_ids: list[str] = Field(default_factory=list)  # 精确 ID 模式
    target_scope: SceneScope | None = None
    target_project_id: str = ""
    cascade: bool = True  # 是否级联删除关联数据


class ForgetResponse(BaseModel):
    """遗忘响应"""

    record_id: str = ""
    deleted_count: int = 0
    deleted_ids: list[str] = Field(default_factory=list)
    audit_log: str = ""


# ============================================================
# 11. 评测相关模型
# ============================================================


class EvalSample(BaseModel):
    """评测样本"""

    sample_id: str = ""
    input_text: str = ""
    expected_output: str = ""
    expected_type: str = ""  # 期望的记忆类型
    scene: str = ""


class EvalResult(BaseModel):
    """单条评测结果"""

    sample_id: str = ""
    predicted: str = ""
    expected: str = ""
    correct: bool = False
    latency_ms: float = 0.0


class EvalReport(BaseModel):
    """评测报告"""

    task_name: str = ""  # "preference_extraction" | "retrieval" | "conflict"
    total_samples: int = 0
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    details: list[EvalResult] = Field(default_factory=list)


class EventProcessingSummary(BaseModel):
    """事件写入后触发的记忆处理摘要（前端 agent 演示适配层使用）。"""

    preferences_written: list[str] = Field(default_factory=list)
    knowledge_written: list[str] = Field(default_factory=list)
    fact_proposal_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
