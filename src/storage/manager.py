"""
MemoryManager — 统一存储管理器。

协调 SQLite + FAISS + Evidence 三层操作：
  - add:   写入 SQLite → FAISS 索引 → 证据链
  - delete: 移除 SQLite → 排除 FAISS → 清理证据链
  - archive: 软删除，同上 + status='archived'

这是数据库管理的统一入口，精准遗忘在此实现。
"""

import time
import numpy as np
from typing import List, Optional, Dict

from .database import DatabaseManager
from .repositories import PreferenceRepository, KnowledgeRepository, ConflictRepository, ForgetRepository
from .models import PreferenceRow, KnowledgeRow, ConflictRow, ForgetRow
from .evidence_store import EvidenceStore


class MemoryManager:
    """
    统一存储管理器 — 一次操作，三层同步。

    用法:
        db = DatabaseManager()
        mm = MemoryManager(db)

        # 添加偏好（自动写入 SQLite + FAISS + 证据）
        mm.add_preference(content="周报用 Markdown", embedding=vec,
                          preference_type="FORMAT_PREF", scope_scene="office")

        # 精准删除（SQLite + FAISS + 证据 同步删除）
        mm.delete_preference("pref_xxx")

        # 软删除（归档）
        mm.archive_preference("pref_xxx")
    """

    def __init__(self, db: DatabaseManager, search_engine=None, index_dir: str = ""):
        self.db = db
        self.pref_repo = PreferenceRepository(db)
        self.know_repo = KnowledgeRepository(db)
        self.conflict_repo = ConflictRepository(db)
        self.forget_repo = ForgetRepository(db)
        self.evidence = EvidenceStore()

        # FAISS 管理器（外部注入或后续绑定）
        self._faiss = search_engine.faiss if search_engine else None

    def bind_faiss(self, faiss):
        """绑定多集合 FAISS 管理器。"""
        self._faiss = faiss

    # ============================================================
    # 偏好操作
    # ============================================================

    def add_preference(
        self,
        content: str,
        embedding: List[float],
        user_id: str = "",
        preference_type: str = "",
        scope_scene: str = "",
        scope_task_type: str = "",
        confidence: float = 0.5,
        level: str = "short",
        source_event_id: str = "",
        source_type: str = "",
        evidence_desc: str = "",
        metadata: Dict = None,
    ) -> PreferenceRow:
        """
        添加偏好 — SQLite + FAISS + 证据 三层同步。
        返回创建的 PreferenceRow。
        """
        emb_blob = np.array(embedding, dtype=np.float32).tobytes()

        row = PreferenceRow(
            user_id=user_id,
            preference_type=preference_type,
            content=content,
            embedding=emb_blob,
            scope_scene=scope_scene,
            scope_task_type=scope_task_type,
            confidence=confidence,
            level=level,
            status="active",
            metadata=metadata or {},
        )
        self.pref_repo.insert(row)

        # FAISS
        if self._faiss and self._faiss.has("preferences"):
            self._faiss.get("preferences").index_from_arrays(
                [row.memory_id], [embedding]
            )

        # 证据
        if source_event_id:
            row.evidence_ids = [
                self.evidence.append(
                    memory_id=row.memory_id,
                    source_event_id=source_event_id,
                    source_type=source_type or "manual",
                    description=evidence_desc or f"添加偏好: {content[:50]}",
                )
            ]

        return row

    def delete_preference(self, memory_id: str, instruction: str = "") -> bool:
        """
        精准删除偏好 — SQLite + FAISS + 证据 同步清除。
        同时记录遗忘审计日志。
        """
        row = self.pref_repo.get_by_id(memory_id)
        if not row:
            return False

        # SQLite
        self.pref_repo.delete_by_id(memory_id)

        # FAISS
        if self._faiss:
            self._faiss.remove("preferences", memory_id)

        # 证据
        self.evidence.delete_chain(memory_id)

        # 审计
        forget = ForgetRow(
            user_id=row.user_id,
            instruction=instruction or f"删除偏好: {row.content[:50]}",
            deleted_type="preference",
            deleted_count=1,
            deleted_ids=[memory_id],
        )
        self.forget_repo.insert(forget)

        return True

    def archive_preference(self, memory_id: str, reason: str = "") -> bool:
        """
        归档偏好（软删除）— status → 'archived'，同时从 FAISS 排除。
        """
        row = self.pref_repo.get_by_id(memory_id)
        if not row:
            return False

        # SQLite 软删除
        self.pref_repo.archive(memory_id)

        # FAISS
        if self._faiss:
            self._faiss.remove("preferences", memory_id)

        # 审计
        forget = ForgetRow(
            user_id=row.user_id,
            instruction=reason or f"归档偏好: {row.content[:50]}",
            deleted_type="preference",
            deleted_count=1,
            deleted_ids=[memory_id],
        )
        self.forget_repo.insert(forget)

        return True

    def delete_preferences_batch(self, memory_ids: List[str], instruction: str = "") -> int:
        """批量删除偏好。返回成功删除数。"""
        count = 0
        for mid in memory_ids:
            if self.delete_preference(mid):
                count += 1
        # 汇总审计
        if count:
            forget = ForgetRow(
                instruction=instruction or f"批量删除 {count} 条偏好",
                deleted_type="preference",
                deleted_count=count,
                deleted_ids=memory_ids,
            )
            self.forget_repo.insert(forget)
        return count

    # ============================================================
    # 知识操作
    # ============================================================

    def add_knowledge(
        self,
        name: str,
        content: str,
        embedding: List[float],
        user_id: str = "",
        knowledge_type: str = "",
        steps: List[str] = None,
        tools: List[str] = None,
        scope_scene: str = "",
        confidence: float = 0.5,
        source_event_id: str = "",
        evidence_desc: str = "",
    ) -> KnowledgeRow:
        """添加知识 — 三层同步。"""
        emb_blob = np.array(embedding, dtype=np.float32).tobytes()

        row = KnowledgeRow(
            user_id=user_id,
            knowledge_type=knowledge_type,
            name=name,
            content=content,
            embedding=emb_blob,
            steps=steps or [],
            tools=tools or [],
            scope_scene=scope_scene,
            confidence=confidence,
            status="active",
        )
        self.know_repo.insert(row)

        # FAISS
        if self._faiss and self._faiss.has("knowledge"):
            self._faiss.get("knowledge").index_from_arrays(
                [row.memory_id], [embedding]
            )

        # 证据
        if source_event_id:
            row.evidence_ids = [
                self.evidence.append(
                    memory_id=row.memory_id,
                    source_event_id=source_event_id,
                    source_type="task_trajectory",
                    description=evidence_desc or f"添加知识: {name}",
                )
            ]

        return row

    def delete_knowledge(self, memory_id: str, instruction: str = "") -> bool:
        """精准删除知识 — 三层同步。"""
        row = self.know_repo.get_by_id(memory_id)
        if not row:
            return False

        self.know_repo.delete_by_id(memory_id)
        if self._faiss:
            self._faiss.remove("knowledge", memory_id)
        self.evidence.delete_chain(memory_id)

        forget = ForgetRow(
            user_id=row.user_id,
            instruction=instruction or f"删除知识: {row.name}",
            deleted_type="knowledge",
            deleted_count=1,
            deleted_ids=[memory_id],
        )
        self.forget_repo.insert(forget)
        return True

    # ============================================================
    # 冲突操作
    # ============================================================

    def record_conflict(
        self,
        old_memory_id: str,
        new_memory_id: str,
        old_content: str,
        new_content: str,
        memory_type: str = "preference",
        decision: str = "pending",
        resolved_by: str = "auto",
        reason: str = "",
    ) -> ConflictRow:
        """记录一次冲突。"""
        row = ConflictRow(
            memory_type=memory_type,
            old_memory_id=old_memory_id,
            new_memory_id=new_memory_id,
            old_content=old_content,
            new_content=new_content,
            decision=decision,
            resolved_by=resolved_by,
            reason=reason,
        )
        self.conflict_repo.insert(row)
        return row

    def resolve_conflict(self, conflict_id: str, decision: str) -> bool:
        """裁决冲突。decision: 'override' | 'merge' | 'coexist'"""
        return self.conflict_repo.resolve(conflict_id, decision)

    # ============================================================
    # 生命周期
    # ============================================================

    def run_lifecycle(self) -> dict:
        """执行一次生命周期流转。"""
        from .lifecycle import LifecycleManager
        lm = LifecycleManager(self.pref_repo, self.know_repo)
        return lm.run_cycle()

    # ============================================================
    # 完整性检查
    # ============================================================

    def verify_integrity(self) -> dict:
        """
        校验数据完整性：
          - FAISS 中的每个 ID 都能在 SQLite 中找到
          - SQLite 中有 embedding 的记录都在 FAISS 中
        """
        issues = []

        # 检查 FAISS → SQLite
        if self._faiss:
            for col_name in self._faiss.list_collections():
                retriever = self._faiss.get(col_name)
                repo = self.pref_repo if col_name == "preferences" else self.know_repo
                for rid in retriever._id_to_idx:
                    if rid in retriever._removed_ids:
                        continue
                    if not repo.get_by_id(rid):
                        issues.append(f"幽灵向量: FAISS[{col_name}] 有 id={rid}，SQLite 中不存在")

        # 检查 SQLite → FAISS
        if self._faiss:
            for col_name, repo in [("preferences", self.pref_repo), ("knowledge", self.know_repo)]:
                if self._faiss.has(col_name):
                    retriever = self._faiss.get(col_name)
                    for row in repo.find_active():
                        if row.embedding and row.memory_id not in retriever._id_to_idx:
                            issues.append(f"缺失向量: SQLite[{col_name}] id={row.memory_id} 不在 FAISS 中")

        return {
            "status": "ok" if not issues else "issues_found",
            "issues": issues,
        }
