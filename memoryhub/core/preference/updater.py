"""
偏好更新与持久化/中长期版本管理器

包含冲突检测 (ConflictDetector)、冲突解决策略 (ConflictResolver) 及版本管理链。
"""

import json
from datetime import datetime, timezone
from memoryhub.adapter.schemas import (
    ConflictDecision,
    ConflictRecord,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
)


class ConflictDetector:
    """冲突检测器"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def check_preference(self, old_pref: PreferenceMemory, new_pref: PreferenceMemory) -> bool:
        """
        判断两条偏好是否构成冲突：
        1. scope 重叠
        2. preference_type 相同
        3. 内容语义矛盾
        """
        scope_overlap = (
            old_pref.is_global
            or new_pref.is_global
            or (
                (old_pref.scope.scene in ["*", new_pref.scope.scene] or new_pref.scope.scene in ["*", old_pref.scope.scene])
                and (old_pref.scope.task_type in ["*", new_pref.scope.task_type] or new_pref.scope.task_type in ["*", old_pref.scope.task_type])
            )
        )
        if not scope_overlap:
            return False

        if old_pref.preference_type != new_pref.preference_type:
            return False

        return self._is_semantic_conflict(old_pref, new_pref)

    def _is_semantic_conflict(self, old_pref: PreferenceMemory, new_pref: PreferenceMemory) -> bool:
        """检测语义冲突"""
        if old_pref.payload.get("target") == new_pref.payload.get("target"):
            if old_pref.payload.get("value") != new_pref.payload.get("value"):
                return True

        if self.llm_client:
            prompt = (
                f"Compare these two user preferences and return true if they logically contradict each other:\n"
                f"Preference A: {old_pref.text}\n"
                f"Preference B: {new_pref.text}\n"
                f"Respond with JSON: {{\"conflict\": true/false}}"
            )
            try:
                res = self.llm_client.generate(
                    prompt, system_prompt="You are a semantic evaluator."
                )
                content = res.content if hasattr(res, "content") else str(res)
                return json.loads(content).get("conflict", False)
            except Exception:
                pass

        negation_words = {"不要", "禁止", "不", "no", "never", "avoid"}
        has_neg_a = any(w in old_pref.text for w in negation_words)
        has_neg_b = any(w in new_pref.text for w in negation_words)
        return has_neg_a != has_neg_b


class ConflictResolver:
    """冲突解决策略执行器"""

    def auto_resolve(
        self, old_pref: PreferenceMemory, new_pref: PreferenceMemory, detector: ConflictDetector
    ) -> tuple[ConflictDecision, str]:
        """
        执行决策矩阵：
        1. scope 不同 -> COEXIST
        2. 新记忆来源 = explicit_feedback -> OVERRIDE
        3. 新旧内容互补/不冲突 -> MERGE
        4. 隐式推理冲突且置信度较低 -> PENDING
        """
        same_scope = (
            old_pref.scope.scene == new_pref.scope.scene
            and old_pref.scope.task_type == new_pref.scope.task_type
        )
        if not same_scope and not old_pref.is_global and not new_pref.is_global:
            return ConflictDecision.COEXIST, "Scopes differ; both preferences can coexist."

        if new_pref.extract_source == "explicit_feedback":
            return ConflictDecision.OVERRIDE, "Explicit user feedback overrides implicit preference."

        if not detector.check_preference(old_pref, new_pref):
            return ConflictDecision.MERGE, "Preferences are compatible and can be merged."

        if new_pref.extract_source == "implicit_inference" and new_pref.confidence < 0.8:
            return ConflictDecision.PENDING, "Implicit preference contradiction requires user confirmation."

        return ConflictDecision.OVERRIDE, "Newer implicit preference overrides older record."


class PreferenceUpdater:
    """偏好更新与持久化/中长期版本管理器"""

    def __init__(
        self,
        llm_client=None,
        db_client=None,
        pref_repo=None,
        conflict_repo=None,
        write_service=None,
    ):
        self.detector = ConflictDetector(llm_client=llm_client)
        self.resolver = ConflictResolver()
        self.db_client = db_client
        self.pref_repo = pref_repo
        self.conflict_repo = conflict_repo
        self.write_service = write_service
        self._mock_db: dict[str, PreferenceMemory] = {}

    def add(self, preference: PreferenceMemory) -> str:
        """新增或更新偏好"""
        # 查找当前活跃的候选旧偏好
        existing_pref = self._find_existing(preference)

        if not existing_pref:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self._save(preference)
            return preference.memory_id

        # 触发冲突检测与解决
        decision, reason = self.resolver.auto_resolve(existing_pref, preference, self.detector)

        for e in preference.evidences:
            if e.decision is None:
                e.decision = decision

        conflict_rec = ConflictRecord(
            user_id=preference.user_id,
            old_memory_id=existing_pref.memory_id,
            new_memory_id=preference.memory_id,
            memory_type="preference",
            old_content=existing_pref.text,
            new_content=preference.text,
            decision=decision,
            reason=reason,
        )

        if decision == ConflictDecision.OVERRIDE:
            return self.update(existing_pref.memory_id, preference, conflict_rec)

        elif decision == ConflictDecision.MERGE:
            merged = self.merge(existing_pref, preference)
            self._save(existing_pref, new_status=MemoryStatus.ARCHIVED)
            self._save(merged)
            self._record_conflict(conflict_rec, merged.memory_id)
            return merged.memory_id

        elif decision == ConflictDecision.COEXIST:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self._save(preference)
            self._record_conflict(conflict_rec, preference.memory_id)
            return preference.memory_id

        else:
            # PENDING: 保存待确认
            preference.status = MemoryStatus.PENDING
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self._save(preference)
            self._record_conflict(conflict_rec, preference.memory_id)
            return preference.memory_id

    def update(self, memory_id: str, new_pref: PreferenceMemory, conflict_rec=None) -> str:
        """更新已有偏好"""
        old_pref = self._get(memory_id)
        if old_pref is None:
            # 找不到旧偏好，作为新记录保存
            new_pref.status = MemoryStatus.ACTIVE
            new_pref.created_at = datetime.now(timezone.utc)
            new_pref.updated_at = datetime.now(timezone.utc)
            self._save(new_pref)
            return new_pref.memory_id

        # 旧偏好归档，新偏好设为活跃
        old_pref.status = MemoryStatus.ARCHIVED
        old_pref.updated_at = datetime.now(timezone.utc)
        self._save(old_pref)
        new_pref.status = MemoryStatus.ACTIVE
        new_pref.parent_id = old_pref.memory_id
        new_pref.root_id = old_pref.root_id or old_pref.memory_id
        new_pref.version = old_pref.version + 1
        new_pref.updated_at = datetime.now(timezone.utc)
        self._save(new_pref)
        if conflict_rec is not None:
            self._record_conflict(conflict_rec, new_pref.memory_id)

        return new_pref.memory_id

    def merge(self, pref_a: PreferenceMemory, pref_b: PreferenceMemory) -> PreferenceMemory:
        """Create a new active version without mutating the archived parent."""
        merged = pref_b.model_copy(deep=True)
        merged.parent_id = pref_a.memory_id
        merged.root_id = pref_a.root_id or pref_a.memory_id
        merged.version = pref_a.version + 1
        merged.status = MemoryStatus.ACTIVE
        merged.confidence = max(pref_a.confidence, pref_b.confidence)
        merged.evidences = [*pref_a.evidences, *pref_b.evidences]
        merged.created_at = datetime.now(timezone.utc)
        merged.updated_at = datetime.now(timezone.utc)
        return merged

    def archive(self, memory_id: str):
        """归档偏好"""
        pref = self._get(memory_id)
        if pref is not None:
            pref.status = MemoryStatus.ARCHIVED
            pref.updated_at = datetime.now(timezone.utc)
            self._save(pref)

    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """获取版本链"""
        if self.pref_repo is not None:
            return self.pref_repo.get_version_chain(memory_id)
        current = self._mock_db.get(memory_id)
        chain: list[PreferenceMemory] = []
        visited: set[str] = set()
        while current is not None and current.memory_id not in visited:
            chain.append(current)
            visited.add(current.memory_id)
            current = self._mock_db.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        return chain

    def _find_existing(self, preference: PreferenceMemory):
        """查找当前活跃的候选旧偏好"""
        if self.pref_repo is not None:
            candidates = self.pref_repo.get_active(preference.user_id)
        else:
            candidates = [
                pref for pref in self._mock_db.values()
                if pref.user_id == preference.user_id
                and pref.status == MemoryStatus.ACTIVE
            ]
        for pref in candidates:
            same_type = pref.preference_type == preference.preference_type
            scope_overlap = (
                pref.is_global
                or preference.is_global
                or (
                    pref.scope.scene in ("*", preference.scope.scene)
                    or preference.scope.scene in ("*", pref.scope.scene)
                )
                and (
                    pref.scope.task_type in ("*", preference.scope.task_type)
                    or preference.scope.task_type in ("*", pref.scope.task_type)
                )
            )
            if same_type and scope_overlap:
                return pref
        return None

    def _get(self, memory_id: str):
        """获取偏好"""
        if self.pref_repo is not None:
            return self.pref_repo.get_by_id(memory_id)
        return self._mock_db.get(memory_id)

    def _record_conflict(self, conflict: ConflictRecord, result_id: str) -> None:
        conflict.result_memory_id = result_id
        if conflict.decision != ConflictDecision.PENDING:
            conflict.resolved_at = datetime.now(timezone.utc)
        if self.conflict_repo is not None:
            self.conflict_repo.save(conflict)

    def _save(self, preference: PreferenceMemory, new_status=None):
        """Persist and synchronize one preference version."""
        if new_status is not None:
            preference.status = new_status
        if self.write_service is not None:
            self.write_service.upsert_memory(preference)
        elif self.pref_repo is not None:
            self.pref_repo.save(preference)
        else:
            self._mock_db[preference.memory_id] = preference
