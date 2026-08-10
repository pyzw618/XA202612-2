"""
前端数据模型

与 memoryhub/adapter/schemas.py 对应，用于前端类型安全。
后端接口字段变动时，只需改此文件。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ============================================================
# 枚举
# ============================================================

class SourceType(str, Enum):
    TOOL_RESULT = "tool_result"
    USER_BEHAVIOR = "user_behavior"
    MANUAL_CONFIG = "manual_config"


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PARTIAL = "partial"


class PreferenceType(str, Enum):
    OUTPUT_STYLE = "output_style"
    TOOL_PREFERENCE = "tool_preference"
    WORKFLOW_PREF = "workflow_preference"
    SAFETY_PREF = "safety_preference"
    SCENE_PREF = "scene_preference"
    FORMAT_PREF = "format_preference"
    LANGUAGE_PREF = "language_preference"


class KnowledgeType(str, Enum):
    WORKFLOW = "workflow"
    CASE = "case"
    TEMPLATE = "template"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
    PENDING = "pending"


class MemoryLevel(str, Enum):
    SHORT = "short"
    MID = "mid"
    LONG = "long"


class ConflictDecision(str, Enum):
    OVERRIDE = "override"
    MERGE = "merge"
    COEXIST = "coexist"
    PENDING = "pending"


# ============================================================
# 数据模型
# ============================================================

@dataclass
class SceneScope:
    scene: str = ""
    task_type: str = ""
    app: str = ""


@dataclass
class Evidence:
    evidence_id: str = ""
    event_id: str = ""
    content: str = ""
    source_type: str = ""
    timestamp: Optional[datetime] = None
    weight: float = 1.0


@dataclass
class PreferenceMemory:
    memory_id: str = ""
    user_id: str = ""
    memory_type: str = "preference"
    preference_type: str = ""
    text: str = ""
    scope: SceneScope = field(default_factory=SceneScope)
    confidence: float = 0.0
    status: str = "active"
    level: str = "short"
    version: int = 1
    parent_id: str = ""
    evidences: list[Evidence] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class KnowledgeMemory:
    memory_id: str = ""
    user_id: str = ""
    memory_type: str = "knowledge"
    knowledge_type: str = ""
    name: str = ""
    content: str = ""
    steps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    template_body: str = ""
    scope: SceneScope = field(default_factory=SceneScope)
    confidence: float = 0.0
    success_count: int = 0
    total_count: int = 0
    status: str = "active"
    level: str = "short"
    version: int = 1
    parent_id: str = ""
    evidences: list[Evidence] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ConflictRecord:
    conflict_id: str = ""
    old_memory_id: str = ""
    new_memory_id: str = ""
    memory_type: str = ""
    old_content: str = ""
    new_content: str = ""
    conflict_field: str = ""
    decision: str = "pending"
    reason: str = ""
    result_memory_id: str = ""
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


@dataclass
class ForgetRecord:
    record_id: str = ""
    user_id: str = ""
    instruction: str = ""
    target_memory_ids: list[str] = field(default_factory=list)
    target_scope: Optional[SceneScope] = None
    deleted_count: int = 0
    created_at: Optional[datetime] = None


@dataclass
class SearchResult:
    memory_id: str = ""
    memory_type: str = ""
    content: str = ""
    score: float = 0.0
    source: str = ""
    metadata: dict = field(default_factory=dict)
