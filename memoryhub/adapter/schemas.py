"""
核心数据结构定义 — 全系统共享的 Pydantic 模型

所有模块间传递的数据都基于这里定义的模型，
修改任何字段必须同步更新 docs/INTERFACE.md。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    OUTPUT_STYLE = "output_style"           # 输出风格偏好
    TOOL_PREFERENCE = "tool_preference"     # 工具选择偏好
    WORKFLOW_PREF = "workflow_preference"   # 操作流程偏好
    SAFETY_PREF = "safety_preference"       # 安全策略偏好
    SCENE_PREF = "scene_preference"         # 场景偏好
    FORMAT_PREF = "format_preference"       # 格式偏好
    LANGUAGE_PREF = "language_preference"   # 语言偏好


class KnowledgeType(str, Enum):
    """知识类型"""
    WORKFLOW = "workflow"       # 工作流知识
    CASE = "case"              # 历史案例
    TEMPLATE = "template"      # 可复用模板


class MemoryLevel(str, Enum):
    """记忆层级"""
    SHORT = "short"    # 短期：当前任务内
    MID = "mid"        # 中期：几天到几周
    LONG = "long"      # 长期：持久保存


class ConflictDecision(str, Enum):
    """冲突处理决策"""
    OVERRIDE = "override"     # 覆盖旧记忆
    MERGE = "merge"           # 合并新旧
    COEXIST = "coexist"       # 按场景并存
    PENDING = "pending"       # 待用户确认


class MemoryStatus(str, Enum):
    """记忆状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    PENDING = "pending"


class SensitiveLevel(str, Enum):
    """敏感等级"""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ============================================================
# 2. 基础模型
# ============================================================

class SceneScope(BaseModel):
    """场景作用域 — 记忆在什么场景下生效"""
    scene: str = ""           # 大场景，如 "office", "code", "chat"
    task_type: str = ""       # 任务类型，如 "office.weekly_report"
    app: str = ""             # 来源应用，如 "os_agent"


class Evidence(BaseModel):
    """证据链 — 记忆的来源依据"""
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_id: str = ""                # 关联的事件 ID
    content: str = ""                 # 证据内容摘要
    source_type: SourceType = SourceType.TOOL_RESULT
    timestamp: datetime = Field(default_factory=datetime.now)
    weight: float = 1.0               # 该证据的权重


# ============================================================
# 3. 事件模型（接入层输出）
# ============================================================

class ToolCallResult(BaseModel):
    """一次工具调用及其结果；同一事件中的 sequence 表示调用顺序。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    status: ToolCallStatus
    sequence: int = Field(ge=1)
    error: str = ""


class EventQuality(BaseModel):
    """清洗、标准化后随事件输出的质量评分明细。"""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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
            raise ValueError("occurred_at must use YYYY-MM-DDTHH:MM:SSZ or be empty") from exc
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
            raise ValueError("schema 1.1 tool_result event requires at least one tool call result")
        if self.event_type == "agent_response":
            if not self.turn_id:
                raise ValueError("agent_response requires turn_id")
            if not self.text:
                raise ValueError("agent_response requires final answer in text")
            if not self.tool_calls:
                raise ValueError("agent_response requires at least one tool call result")
        if self.tool_calls:
            call_ids = [call.call_id for call in self.tool_calls]
            sequences = [call.sequence for call in self.tool_calls]
            if len(call_ids) != len(set(call_ids)):
                raise ValueError("tool_calls.call_id values must be unique within an event")
            if len(sequences) != len(set(sequences)):
                raise ValueError("tool_calls.sequence values must be unique within an event")
            if sequences != sorted(sequences):
                raise ValueError("tool_calls must be ordered by ascending sequence")
        return self


# ============================================================
# 4. 偏好记忆模型
# ============================================================

class PreferenceMemory(BaseModel):
    """
    偏好记忆 — 记录用户的个性化偏好

    数据流：MemoryEvent → PreferenceExtractor → PreferenceMemory → Storage
    """
    memory_id: str = Field(default_factory=lambda: f"pref_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    memory_type: str = "preference"
    preference_type: PreferenceType = PreferenceType.OUTPUT_STYLE

    # --- 偏好内容 ---
    content: str = ""                 # 偏好描述，如 "项目周报默认使用 Markdown"
    scope: SceneScope = Field(default_factory=SceneScope)

    # --- 置信度与状态 ---
    confidence: float = 0.0           # [0, 1] 置信度
    status: MemoryStatus = MemoryStatus.ACTIVE
    level: MemoryLevel = MemoryLevel.LONG

    # --- 版本管理 ---
    version: int = 1
    parent_id: str = ""               # 前一版本的 memory_id（用于版本链）

    # --- 证据链 ---
    evidences: list[Evidence] = Field(default_factory=list)

    # --- 时间戳 ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 5. 知识记忆模型
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
    name: str = ""                    # 知识名称，如 "项目周报生成流程"
    content: str = ""                 # 知识描述
    steps: list[str] = Field(default_factory=list)       # 工作流步骤
    tools: list[str] = Field(default_factory=list)        # 涉及的工具链
    template_body: str = ""           # 模板正文（仅 template 类型）
    scope: SceneScope = Field(default_factory=SceneScope)

    # --- 质量指标 ---
    confidence: float = 0.0
    success_count: int = 0            # 成功复用次数
    total_count: int = 0              # 总调用次数
    status: MemoryStatus = MemoryStatus.ACTIVE
    level: MemoryLevel = MemoryLevel.LONG

    # --- 版本管理 ---
    version: int = 1
    parent_id: str = ""

    # --- 证据链 ---
    evidences: list[Evidence] = Field(default_factory=list)

    # --- 时间戳 ---
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 6. 冲突记录模型
# ============================================================

class ConflictRecord(BaseModel):
    """
    冲突记录 — 记录新旧记忆之间的冲突及处理结果

    数据流：检测到冲突 → ConflictResolver → ConflictRecord → 更新记忆
    """
    conflict_id: str = Field(default_factory=lambda: f"conf_{uuid.uuid4().hex[:8]}")
    old_memory_id: str = ""
    new_memory_id: str = ""
    memory_type: str = ""             # "preference" | "knowledge"

    # --- 冲突内容 ---
    old_content: str = ""
    new_content: str = ""
    conflict_field: str = ""          # 冲突的具体字段

    # --- 处理结果 ---
    decision: ConflictDecision = ConflictDecision.PENDING
    reason: str = ""                  # 处理原因说明
    result_memory_id: str = ""        # 处理后产生的新记忆 ID

    created_at: datetime = Field(default_factory=datetime.now)
    resolved_at: datetime | None = None


# ============================================================
# 7. 遗忘记录模型
# ============================================================

class ForgetRecord(BaseModel):
    """
    遗忘记录 — 精准遗忘操作的审计日志

    数据流：用户指令 → 遗忘意图解析 → 删除记忆 → 生成 ForgetRecord
    """
    record_id: str = Field(default_factory=lambda: f"forg_{uuid.uuid4().hex[:8]}")
    user_id: str = "default"
    instruction: str = ""             # 用户原始指令
    target_memory_ids: list[str] = Field(default_factory=list)
    target_scope: SceneScope = Field(default_factory=SceneScope)
    deleted_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# 8. 检索相关模型
# ============================================================

class SearchRequest(BaseModel):
    """检索请求"""
    user_id: str = "default"
    query: str = ""
    context: SceneScope = Field(default_factory=SceneScope)
    top_k: int = 5
    memory_types: list[str] = Field(default_factory=list)  # 过滤记忆类型
    min_confidence: float = 0.0


class SearchResult(BaseModel):
    """单条检索结果"""
    memory_id: str = ""
    memory_type: str = ""             # "preference" | "knowledge"
    content: str = ""
    score: float = 0.0                # 综合得分
    source: str = ""                  # 来源标记："vector" | "keyword" | "metadata"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """检索响应"""
    results: list[SearchResult] = Field(default_factory=list)
    preferences: list[PreferenceMemory] = Field(default_factory=list)
    knowledge: list[KnowledgeMemory] = Field(default_factory=list)
    latency_ms: float = 0.0
    total_count: int = 0


# ============================================================
# 9. 写入/更新请求模型
# ============================================================

class WriteEventRequest(BaseModel):
    """写入事件请求"""
    events: list[MemoryEvent] = Field(default_factory=list)


class WriteEventResponse(BaseModel):
    """写入事件响应"""
    accepted: int = 0
    rejected: int = 0
    event_ids: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """用户反馈请求（触发偏好更新）"""
    user_id: str = "default"
    memory_id: str = ""               # 要更新的记忆 ID
    feedback_text: str = ""           # 反馈内容
    action: str = "update"            # "update" | "confirm" | "reject"


class ForgetRequest(BaseModel):
    """遗忘请求"""
    user_id: str = "default"
    instruction: str = ""             # 自然语言遗忘指令
    target_scope: SceneScope | None = None


class ForgetResponse(BaseModel):
    """遗忘响应"""
    record_id: str = ""
    deleted_count: int = 0
    deleted_ids: list[str] = Field(default_factory=list)
    audit_log: str = ""


# ============================================================
# 10. 评测相关模型
# ============================================================

class EvalSample(BaseModel):
    """评测样本"""
    sample_id: str = ""
    input_text: str = ""
    expected_output: str = ""
    expected_type: str = ""           # 期望的记忆类型
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
    task_name: str = ""               # "preference_extraction" | "retrieval" | "conflict"
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
