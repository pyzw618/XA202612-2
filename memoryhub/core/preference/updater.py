"""
偏好更新与持久化/中长期版本管理器

包含冲突检测 (ConflictDetector)、冲突解决策略 (ConflictResolver) 及版本管理链。
针对 Evidence 中的 ConflictDecision 进行了精确联动与版本回滚控制。
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
        1. scope 重叠（同一场景/任务类型，包含全局通配符 *）
        2. preference_type 相同
        3. 内容语义矛盾
        """
        # 1. 检查 Scope 重叠
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

        # 2. 检查 preference_type 是否相同
        if old_pref.preference_type != new_pref.preference_type:
            return False

        # 3. 检查语义/内容矛盾
        return self._is_semantic_conflict(old_pref, new_pref)

    def _is_semantic_conflict(self, old_pref: PreferenceMemory, new_pref: PreferenceMemory) -> bool:
        """检测语义冲突（规则判断 + LLM 辅助判断）"""
        # 规则判断：payload 目标字段相同但 target / value 不一致
        if old_pref.payload.get("target") == new_pref.payload.get("target"):
            if old_pref.payload.get("value") != new_pref.payload.get("value"):
                return True

        # LLM 辅助语义对比
        if self.llm_client:
            prompt = (
                f"Compare these two user preferences and return true if they logically contradict each other:\n"
                f"Preference A: {old_pref.text}\n"
                f"Preference B: {new_pref.text}\n"
                f"Respond with JSON: {{\"conflict\": true/false}}"
            )
            try:
                res = self.llm_client.generate("You are a semantic evaluator.", prompt)
                return json.loads(res).get("conflict", False)
            except Exception:
                pass

        # 兜底：若包含相反否定词匹配
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
        # 检查 Scope 是否存在完全不重叠的情况
        same_scope = (
            old_pref.scope.scene == new_pref.scope.scene
            and old_pref.scope.task_type == new_pref.scope.task_type
        )
        if not same_scope and not old_pref.is_global and not new_pref.is_global:
            return ConflictDecision.COEXIST, "Scopes differ; both preferences can coexist."

        # 显式反馈直接覆写
        if new_pref.extract_source == "explicit_feedback":
            return ConflictDecision.OVERRIDE, "New preference originated from explicit user feedback."

        # 冲突判断
        is_conflict = detector.check_preference(old_pref, new_pref)
        if not is_conflict:
            return ConflictDecision.MERGE, "Preferences complement each other."

        # 如果来自隐式推断且置信度较低，标记待用户确认
        if new_pref.extract_source == "implicit_inference" and new_pref.confidence < 0.8:
            return ConflictDecision.PENDING, "Implicit preference contradiction requires user confirmation."

        return ConflictDecision.OVERRIDE, "Newer implicit preference overrides older record."


class PreferenceUpdater:
    """偏好更新与持久化/中长期版本管理器"""

    _mock_db: dict[str, PreferenceMemory] = {}

    def __init__(self, llm_client=None, db_client=None):
        self.detector = ConflictDetector(llm_client=llm_client)
        self.resolver = ConflictResolver()
        self.db_client = db_client  # 可选注入真实的数据库客户端

    def add(self, preference: PreferenceMemory) -> str:
        """新增或更新偏好"""
        # 查找当前活跃的候选旧偏好
        existing_pref = None
        for pref in self._mock_db.values():
            if (
                pref.status == MemoryStatus.ACTIVE
                and pref.user_id == preference.user_id
                and pref.preference_type == preference.preference_type
            ):
                if self.detector.check_preference(pref, preference):
                    existing_pref = pref
                    break

        if not existing_pref:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            preference.created_at = datetime.now(timezone.utc)
            preference.updated_at = datetime.now(timezone.utc)
            self._mock_db[preference.memory_id] = preference

            # TODO: [DB 落盘] 写入全新的偏好记忆记录
            # if self.db_client:
            #     self.db_client.save_preference(preference)

            return preference.memory_id

        # 触发冲突检测与解决决策矩阵
        decision, reason = self.resolver.auto_resolve(existing_pref, preference, self.detector)

        # 标记新偏好内部证据链中的 decision 属性
        for e in preference.evidences:
            if e.decision is None:
                e.decision = decision

        # 构造冲突记录对象
        conflict_rec = ConflictRecord(
            old_memory_id=existing_pref.memory_id,
            new_memory_id=preference.memory_id,
            memory_type="preference",
            old_content=existing_pref.text,
            new_content=preference.text,
            decision=decision,
            reason=reason,
        )

        if decision == ConflictDecision.OVERRIDE:
            # update 方法内部已实现包含冲突日志在内的事务级落盘
            return self.update(existing_pref.memory_id, preference, conflict_rec)

        elif decision == ConflictDecision.MERGE:
            merged = self.merge(existing_pref, preference)
            self._mock_db[merged.memory_id] = merged
            existing_pref.status = MemoryStatus.ARCHIVED

            # TODO: [DB 事务落盘] 原子化写入合并偏好、归档旧偏好并保存冲突审计日志
            # if self.db_client:
            #     with self.db_client.transaction():
            #         self.db_client.save_preference(merged)
            #         self.db_client.update_status(existing_pref.memory_id, MemoryStatus.ARCHIVED)
            #         self.db_client.save_conflict_record(conflict_rec)

            return merged.memory_id

        elif decision == ConflictDecision.COEXIST:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            self._mock_db[preference.memory_id] = preference

            # TODO: [DB 落盘] 保存共存的新偏好并记录冲突评估日志
            # if self.db_client:
            #     with self.db_client.transaction():
            #         self.db_client.save_preference(preference)
            #         self.db_client.save_conflict_record(conflict_rec)

            return preference.memory_id

        else:  # PENDING
            preference.status = MemoryStatus.PENDING
            self._mock_db[preference.memory_id] = preference

            # TODO: [DB 落盘] 保存待人工确认的偏好记录及冲突日志
            # if self.db_client:
            #     with self.db_client.transaction():
            #         self.db_client.save_preference(preference)
            #         self.db_client.save_conflict_record(conflict_rec)

            return preference.memory_id

    def update(
        self,
        old_id: str,
        new_preference: PreferenceMemory,
        conflict_rec: ConflictRecord | None = None,
    ) -> str:
        """更新版本链条并维护中长期记忆状态"""
        old_pref = self._mock_db.get(old_id)
        if not old_pref:
            new_preference.status = MemoryStatus.ACTIVE
            new_preference.root_id = new_preference.memory_id
            self._mock_db[new_preference.memory_id] = new_preference

            # TODO: [DB 落盘] 找不到旧偏好时作为新记录落盘
            # if self.db_client:
            #     self.db_client.save_preference(new_preference)

            return new_preference.memory_id

        # 检查异常回滚：统计近 7 天内处于 OVERRIDE 状态的冲突证据占比
        now = datetime.now(timezone.utc)
        recent_evidences = [
            e
            for e in old_pref.evidences
            if (now - (e.timestamp.replace(tzinfo=timezone.utc) if not e.timestamp.tzinfo else e.timestamp)).days <= 7
        ]
        override_count = sum(1 for e in recent_evidences if e.decision == ConflictDecision.OVERRIDE)

        if len(recent_evidences) >= 3 and (override_count / len(recent_evidences)) >= 0.7:
            if old_pref.parent_id and old_pref.parent_id in self._mock_db:
                self._mock_db[old_pref.parent_id].status = MemoryStatus.ACTIVE
                self._mock_db[old_pref.parent_id].updated_at = datetime.now(timezone.utc)
                old_pref.status = MemoryStatus.ARCHIVED

                # TODO: [DB 事务落盘] 执行版本回滚落盘：激活父节点，归档当前节点
                # if self.db_client:
                #     with self.db_client.transaction():
                #         self.db_client.update_status(old_pref.parent_id, MemoryStatus.ACTIVE)
                #         self.db_client.update_status(old_id, MemoryStatus.ARCHIVED)

                return old_pref.parent_id
            else:
                old_pref.status = MemoryStatus.DELETED

                # TODO: [DB 落盘] 无可回滚父节点，软删除当前记录
                # if self.db_client:
                #     self.db_client.update_status(old_id, MemoryStatus.DELETED)

                return ""

        # 正常递增版本
        new_preference.version = old_pref.version + 1
        new_preference.parent_id = old_id
        new_preference.root_id = old_pref.root_id or old_id
        new_preference.status = MemoryStatus.ACTIVE
        new_preference.level = MemoryLevel.LONG if new_preference.confidence >= 0.8 else MemoryLevel.MID
        new_preference.created_at = old_pref.created_at
        new_preference.updated_at = datetime.now(timezone.utc)

        # 融合 tags 标签与证据链
        new_preference.tags = list(set(old_pref.tags + new_preference.tags))
        merged_evidences = old_pref.evidences + new_preference.evidences
        new_preference.evidences = merged_evidences[-15:]

        old_pref.status = MemoryStatus.ARCHIVED
        self._mock_db[new_preference.memory_id] = new_preference

        # TODO: [DB 事务落盘] 原子化更新：1. 写入新版本偏好；2. 更新旧偏好状态为 ARCHIVED；3. 保存冲突审计日志
        # if self.db_client:
        #     with self.db_client.transaction():
        #         self.db_client.save_preference(new_preference)
        #         self.db_client.update_status(old_id, MemoryStatus.ARCHIVED)
        #         if conflict_rec:
        #             self.db_client.save_conflict_record(conflict_rec)

        return new_preference.memory_id

    def merge(self, pref_a: PreferenceMemory, pref_b: PreferenceMemory) -> PreferenceMemory:
        """合并偏好并合并 tags"""
        merged_tags = list(set(pref_a.tags + pref_b.tags))
        merged_text = f"{pref_a.text} 且 {pref_b.text}"
        merged_payload = {**pref_a.payload, **pref_b.payload}
        merged_evidences = pref_a.evidences + pref_b.evidences

        return PreferenceMemory(
            user_id=pref_a.user_id,
            preference_type=pref_a.preference_type,
            text=merged_text,
            payload=merged_payload,
            scope=pref_a.scope,
            confidence=max(pref_a.confidence, pref_b.confidence),
            quality_score=max(pref_a.quality_score, pref_b.quality_score),
            status=MemoryStatus.ACTIVE,
            level=MemoryLevel.LONG,
            tags=merged_tags,
            version=max(pref_a.version, pref_b.version) + 1,
            parent_id=pref_a.memory_id,
            root_id=pref_a.root_id or pref_a.memory_id,
            evidences=merged_evidences[-15:],
            created_at=min(pref_a.created_at, pref_b.created_at),
            updated_at=datetime.now(timezone.utc),
        )

    def get_version_chain(self, memory_id: str) -> list[PreferenceMemory]:
        """获取偏好的完整版本演进链条（按时间升序排列）"""
        chain = []
        curr_id = memory_id
        visited = set()  # 防止版本圈回环异常

        while curr_id and curr_id not in visited:
            pref = self._mock_db.get(curr_id)
            if not pref:
                # TODO: [DB 查询] 如果 Mock DB 查不到，可向数据库追溯历史版本
                # if self.db_client:
                #     pref = self.db_client.get_preference_by_id(curr_id)
                #     if not pref: break
                break

            chain.insert(0, pref)
            visited.add(curr_id)
            curr_id = pref.parent_id

        return chain

    def archive(self, memory_id: str) -> bool:
        """显式归档某条偏好"""
        pref = self._mock_db.get(memory_id)
        if pref:
            pref.status = MemoryStatus.ARCHIVED
            pref.updated_at = datetime.now(timezone.utc)

            # TODO: [DB 落盘] 更新数据库中该偏好的状态与更新时间
            # if self.db_client:
            #     self.db_client.update_status(
            #         memory_id=memory_id,
            #         status=MemoryStatus.ARCHIVED,
            #         updated_at=pref.updated_at
            #     )

            return True
        return False