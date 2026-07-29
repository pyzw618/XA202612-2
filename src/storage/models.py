"""
ORM 数据模型 — 每张表对应一个 dataclass。

所有模型都支持:
  - 从 SQLite 行 tuple 反序列化 (from_row)
  - 转为 SQLite 插入参数 (to_dict)
"""

import json
import uuid
import time
from dataclasses import dataclass, field
from typing import Optional, List


def _uid(prefix: str = "") -> str:
    return (prefix + uuid.uuid4().hex)[:12]


def _now() -> float:
    return time.time()


# ============================================================
# 模型 1: EventRow — 原始事件
# ============================================================
@dataclass
class EventRow:
    id: str = field(default_factory=lambda: _uid("ev_"))
    user_id: str = ""
    session_id: str = ""
    task_id: str = ""
    event_type: str = "tool_call"
    source: str = "os_agent"
    content: dict = field(default_factory=dict)
    scene: str = ""
    task_type: str = ""
    quality_score: float = 0.0
    sensitive_level: str = "NONE"
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: tuple) -> "EventRow":
        return cls(
            id=row[0], user_id=row[1], session_id=row[2], task_id=row[3],
            event_type=row[4], source=row[5], content=json.loads(row[6]) if row[6] else {},
            scene=row[7], task_type=row[8], quality_score=row[9],
            sensitive_level=row[10], metadata=json.loads(row[11]) if row[11] else {},
            created_at=row[12],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "user_id": self.user_id, "session_id": self.session_id,
            "task_id": self.task_id, "event_type": self.event_type, "source": self.source,
            "content": json.dumps(self.content, ensure_ascii=False),
            "scene": self.scene, "task_type": self.task_type, "quality_score": self.quality_score,
            "sensitive_level": self.sensitive_level,
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
            "created_at": self.created_at,
        }


# ============================================================
# 模型 2: PreferenceRow — 偏好记忆
# ============================================================
@dataclass
class PreferenceRow:
    memory_id: str = field(default_factory=lambda: _uid("pref_"))
    user_id: str = ""
    preference_type: str = ""
    content: str = ""
    embedding: Optional[bytes] = None
    scope_scene: str = ""
    scope_task_type: str = ""
    scope_app: str = ""
    confidence: float = 0.0
    status: str = "active"
    level: str = "short"
    occur_count: int = 1
    version: int = 1
    parent_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: tuple) -> "PreferenceRow":
        return cls(
            memory_id=row[0], user_id=row[1], preference_type=row[2],
            content=row[3], embedding=row[4], scope_scene=row[5],
            scope_task_type=row[6], scope_app=row[7], confidence=row[8],
            status=row[9], level=row[10], occur_count=row[11],
            version=row[12], parent_id=row[13],
            evidence_ids=json.loads(row[14]) if row[14] else [],
            metadata=json.loads(row[15]) if row[15] else {},
            created_at=row[16], updated_at=row[17],
        )

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id, "user_id": self.user_id,
            "preference_type": self.preference_type, "content": self.content,
            "embedding": self.embedding,
            "scope_scene": self.scope_scene, "scope_task_type": self.scope_task_type,
            "scope_app": self.scope_app, "confidence": self.confidence,
            "status": self.status, "level": self.level,
            "occur_count": self.occur_count,
            "version": self.version, "parent_id": self.parent_id,
            "evidence_ids": json.dumps(self.evidence_ids, ensure_ascii=False),
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ============================================================
# 模型 3: KnowledgeRow — 知识记忆
# ============================================================
@dataclass
class KnowledgeRow:
    memory_id: str = field(default_factory=lambda: _uid("know_"))
    user_id: str = ""
    knowledge_type: str = ""
    name: str = ""
    content: str = ""
    embedding: Optional[bytes] = None
    steps: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    template_body: Optional[str] = None
    scope_scene: str = ""
    scope_task_type: str = ""
    confidence: float = 0.0
    success_count: int = 0
    total_count: int = 0
    status: str = "active"
    evidence_ids: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: tuple) -> "KnowledgeRow":
        return cls(
            memory_id=row[0], user_id=row[1], knowledge_type=row[2],
            name=row[3], content=row[4], embedding=row[5],
            steps=json.loads(row[6]) if row[6] else [],
            tools=json.loads(row[7]) if row[7] else [],
            template_body=row[8], scope_scene=row[9], scope_task_type=row[10],
            confidence=row[11], success_count=row[12], total_count=row[13],
            status=row[14],
            evidence_ids=json.loads(row[15]) if row[15] else [],
            metadata=json.loads(row[16]) if row[16] else {},
            created_at=row[17], updated_at=row[18],
        )

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id, "user_id": self.user_id,
            "knowledge_type": self.knowledge_type, "name": self.name,
            "content": self.content, "embedding": self.embedding,
            "steps": json.dumps(self.steps, ensure_ascii=False),
            "tools": json.dumps(self.tools, ensure_ascii=False),
            "template_body": self.template_body,
            "scope_scene": self.scope_scene, "scope_task_type": self.scope_task_type,
            "confidence": self.confidence, "success_count": self.success_count,
            "total_count": self.total_count, "status": self.status,
            "evidence_ids": json.dumps(self.evidence_ids, ensure_ascii=False),
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ============================================================
# 模型 4: ConflictRow — 冲突记录
# ============================================================
@dataclass
class ConflictRow:
    conflict_id: str = field(default_factory=lambda: _uid("conf_"))
    user_id: str = ""
    memory_type: str = ""
    old_memory_id: str = ""
    new_memory_id: str = ""
    old_content: str = ""
    new_content: str = ""
    decision: str = "pending"
    reason: str = ""
    resolved_by: str = "auto"
    created_at: float = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: tuple) -> "ConflictRow":
        return cls(
            conflict_id=row[0], user_id=row[1], memory_type=row[2],
            old_memory_id=row[3], new_memory_id=row[4],
            old_content=row[5], new_content=row[6],
            decision=row[7], reason=row[8], resolved_by=row[9],
            created_at=row[10],
        )

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id, "user_id": self.user_id,
            "memory_type": self.memory_type,
            "old_memory_id": self.old_memory_id, "new_memory_id": self.new_memory_id,
            "old_content": self.old_content, "new_content": self.new_content,
            "decision": self.decision, "reason": self.reason,
            "resolved_by": self.resolved_by, "created_at": self.created_at,
        }


# ============================================================
# 模型 5: ForgetRow — 遗忘审计日志
# ============================================================
@dataclass
class ForgetRow:
    forget_id: str = field(default_factory=lambda: _uid("forg_"))
    user_id: str = ""
    instruction: str = ""
    deleted_type: str = ""
    deleted_count: int = 0
    deleted_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=_now)

    @classmethod
    def from_row(cls, row: tuple) -> "ForgetRow":
        return cls(
            forget_id=row[0], user_id=row[1], instruction=row[2],
            deleted_type=row[3], deleted_count=row[4],
            deleted_ids=json.loads(row[5]) if row[5] else [],
            created_at=row[6],
        )

    def to_dict(self) -> dict:
        return {
            "forget_id": self.forget_id, "user_id": self.user_id,
            "instruction": self.instruction, "deleted_type": self.deleted_type,
            "deleted_count": self.deleted_count,
            "deleted_ids": json.dumps(self.deleted_ids, ensure_ascii=False),
            "created_at": self.created_at,
        }
