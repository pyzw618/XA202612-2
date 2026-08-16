"""
数据模型定义 — 三元组 / 实体 / 谓词 / 事实 / 冲突结果
参考 types.h 和 事实记忆模块设计.md
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid
from datetime import datetime, timezone


# ─── 固定实体类型（9 类）───────────────────────────────────────────────

class EntityType(str, Enum):
    PERSON = "Person"               # 人物
    ORGANIZATION = "Organization"   # 组织/公司
    LOCATION = "Location"           # 地点
    DEVICE = "Device"               # 设备
    SOFTWARE = "Software"           # 软件
    FILE = "File"                   # 文件
    ACCOUNT = "Account"             # 账户
    DATE = "Date"                   # 日期
    OTHER = "Other"                 # 兜底

    @classmethod
    def choices(cls) -> list[str]:
        return [e.value for e in cls]


# ─── 冲突裁决动作 ──────────────────────────────────────────────────────

class Resolution(str, Enum):
    REPLACE = "replace"             # 新事实取代旧事实
    KEEP_OLD = "keep_old"           # 保留旧事实
    MERGE = "merge"                 # 合并两者信息
    COEXIST = "coexist"             # 不同上下文下分别成立，都保留
    ESCALATE = "escalate"           # 无法自动判定，标记冲突等人工


class MemoryScope(str, Enum):
    """事实的生效范围。"""
    GLOBAL = "global"                # 跨项目长期事实
    PROJECT = "project"              # 仅在指定项目内生效

    @classmethod
    def choices(cls) -> list[str]:
        return [e.value for e in cls]


class FactDecisionMode(str, Enum):
    """How an extracted fact candidate reaches durable fact storage."""

    USER_REVIEW = "user_review"
    AGENT_AUTONOMOUS = "agent_autonomous"

    @classmethod
    def choices(cls) -> list[str]:
        return [e.value for e in cls]


class FactProposalStatus(str, Enum):
    PROPOSED = "proposed"
    COMMITTED = "committed"
    REJECTED = "rejected"
    AWAITING_DECISION = "awaiting_decision"


# ─── 实体 ──────────────────────────────────────────────────────────────

@dataclass
class Entity:
    """Normalized entity; aliases are isolated by user."""
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    user_id: str = "default"

    @staticmethod
    def make_id(entity_type: str, name: str, user_id: str = "") -> str:
        """Build a deterministic, user-scoped entity id."""
        import hashlib
        slug = name.lower().replace(" ", "_").replace("/", "_")
        digest = hashlib.sha256(
            f"{user_id}:{entity_type}:{name}".encode()
        ).hexdigest()[:8]
        return f"entity:{entity_type.lower()}:{slug}_{digest}"


# ─── 谓词定义 ──────────────────────────────────────────────────────────

@dataclass
class PredicateDef:
    """受控谓词本体中的一条定义"""
    predicate_id: str                       # "headquarters_location"
    canonical_name: str                     # "总部所在地"
    aliases: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)   # 适用于哪些 EntityType
    range: list[str] = field(default_factory=list)     # 客体类型
    single_value: bool = True               # True = 单值互斥

    @staticmethod
    def make_id(name: str) -> str:
        import hashlib
        slug = name.lower().replace(" ", "_")
        digest = hashlib.sha256(name.encode()).hexdigest()[:6]
        return f"pred:{slug}_{digest}"


# ─── 原始三元组（LLM 提取，未归一化）──────────────────────────────────

@dataclass
class RawTriple:
    """LLM 从文本中提取的候选三元组（别名由归一化管道自然积累，不由 LLM 生成）"""
    subject_text: str
    subject_type: str
    predicate_text: str
    object_text: str
    object_type: str
    evidence: str                           # 原文证据片段
    confidence: float                       # 0-1


# ─── 归一化事实 ───────────────────────────────────────────────────────

@dataclass
class Fact:
    """归一化后的完整事实断言，对应 facts 表一行"""
    fact_id: str
    subject_id: str                         # → Entity.entity_id
    predicate_id: str                       # → PredicateDef.predicate_id
    object_id: str                          # → Entity.entity_id 或原值
    object_value: str                       # 原始文本值
    source_text: str                        # 来源原文
    source_id: str                          # 来源文档/工具调用 ID
    observed_at: str                        # 信息接收时间 ISO 8601
    confidence: float                       # 0-1
    status: str = "active"                  # active | superseded | disputed
    version: int = 1
    memory_type: str = "fact"               # 当前模块只接受事实记忆
    scope: str = MemoryScope.GLOBAL.value
    project_id: Optional[str] = None
    user_id: str = "default"
    last_accessed_at: Optional[str] = None
    access_count_30d: int = 0
    pending_index: bool = True
    index_version: int = 0

    def __post_init__(self):
        if not self.user_id:
            raise ValueError("fact requires user_id")
        if self.memory_type != "fact":
            raise ValueError("fact_memory 只接受 memory_type='fact'")
        if self.scope not in MemoryScope.choices():
            raise ValueError(f"不支持的事实作用域: {self.scope}")
        if self.scope == MemoryScope.PROJECT.value and not self.project_id:
            raise ValueError("项目事实必须提供 project_id")
        if self.scope == MemoryScope.GLOBAL.value and self.project_id is not None:
            raise ValueError("全局事实不能绑定 project_id")

    @property
    def memory_id(self) -> str:
        """Compatibility alias used by the shared retrieval layer."""
        return self.fact_id

    @property
    def content(self) -> str:
        """Fallback searchable text when entity display names are unavailable."""
        return " ".join(
            part for part in (
                self.subject_id, self.predicate_id, self.object_value,
                self.source_text,
            ) if part
        )

    @staticmethod
    def make_id() -> str:
        return f"fact_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


# ─── 冲突检测结果 ─────────────────────────────────────────────────────

@dataclass
class ConflictResult:
    """一次冲突检测的输出"""
    relation: str                           # NEW | DUPLICATE | CONFLICT | COEXIST
    new_fact: Fact
    existing_fact: Optional[Fact] = None    # 冲突/重复时指向已有事实
    reason: str = ""
    resolution: Optional[str] = None        # Resolution 枚举值，LLM 裁决后填入


@dataclass
class FactAdmissionDecision:
    """事实准入判断：只判断是否为适合本模块保存的事实。"""
    is_fact: bool
    should_remember: bool
    suggested_scope: Optional[str] = None
    category: str = "uncertain"
    confidence: float = 0.0
    reason: str = ""


@dataclass
class FactCandidate:
    """纯分析得到的事实候选；不包含归一化 ID 或数据库状态。"""
    candidate_id: str
    raw_triple: RawTriple
    admission: FactAdmissionDecision
    source_id: str = ""
    project_id_hint: Optional[str] = None
    scope_hint: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def make_id() -> str:
        return f"candidate_{uuid.uuid4().hex[:12]}"

    @property
    def proposal_id(self) -> str:
        """兼容旧调用方使用的 proposal_id 名称。"""
        return self.candidate_id


# 兼容旧名称；新代码优先使用 FactCandidate。
FactProposal = FactCandidate
