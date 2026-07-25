"""
偏好更新与版本管理模块

包含冲突检测 (ConflictDetector)、冲突解决策略 (ConflictResolver) 及版本管理链。
"""

import json
from datetime import datetime, timezone
from memoryhub.adapter.schemas import (
    PreferenceMemory, MemoryStatus, MemoryLevel, 
    ConflictDecision, ConflictRecord
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
            old_pref.is_global or new_pref.is_global or
            (old_pref.scope.scene in ["*", new_pref.scope.scene] or new_pref.scope.scene in ["*", old_pref.scope.scene]) and
            (old_pref.scope.task_type in ["*", new_pref.scope.task_type] or new_pref.scope.task_type in ["*", old_pref.scope.task_type])
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

    def auto_resolve(self, old_pref: PreferenceMemory, new_pref: PreferenceMemory, detector: ConflictDetector) -> tuple[ConflictDecision, str]:
        """
        执行决策矩阵：
        1. 新记忆来源 = explicit_feedback -> OVERRIDE
        2. 新旧内容互补 -> MERGE
        3. scope 不同 -> COEXIST
        4. 无法自动判断 -> PENDING
        """
        # 检查 Scope 是否存在完全不重叠的情况
        same_scope = (
            old_pref.scope.scene == new_pref.scope.scene and 
            old_pref.scope.task_type == new_pref.scope.task_type
        )
        if not same_scope and not old_pref.is_global and not new_pref.is_global:
            return ConflictDecision.COEXIST, "Scopes differ; both preferences can coexist."

        # 显式反馈直接覆写
        if new_pref.extract_source == "explicit_feedback":
            return ConflictDecision.OVERRIDE, "New preference originated from explicit user feedback."

        # 冲突判断
        is_conflict = detector.check_preference(old_pref, new_pref)
        if not is_conflict:
            # 不冲突则判定为互补
            return ConflictDecision.MERGE, "Preferences complement each other."

        # 如果来自隐式推断且置信度差异小，标记待用户确认
        if new_pref.extract_source == "implicit_inference" and new_pref.confidence < 0.8:
            return ConflictDecision.PENDING, "Implicit preference contradiction requires user confirmation."

        return ConflictDecision.OVERRIDE, "Newer implicit preference overrides older record."


class PreferenceUpdater:
    """偏好更新与持久化/中长期版本管理器"""

    _mock_db: dict[str, PreferenceMemory] = {}

    def __init__(self, llm_client=None):
        self.detector = ConflictDetector(llm_client=llm_client)
        self.resolver = ConflictResolver()

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
            return preference.memory_id

        # 触发冲突检测与解决决策矩阵
        decision, reason = self.resolver.auto_resolve(existing_pref, preference, self.detector)
        
        # 记录冲突日志
        ConflictRecord(
            old_memory_id=existing_pref.memory_id,
            new_memory_id=preference.memory_id,
            memory_type="preference",
            old_content=existing_pref.text,
            new_content=preference.text,
            decision=decision,
            reason=reason
        )

        if decision == ConflictDecision.OVERRIDE:
            return self.update(existing_pref.memory_id, preference)
        elif decision == ConflictDecision.MERGE:
            merged = self.merge(existing_pref, preference)
            self._mock_db[merged.memory_id] = merged
            existing_pref.status = MemoryStatus.ARCHIVED
            return merged.memory_id
        elif decision == ConflictDecision.COEXIST:
            preference.status = MemoryStatus.ACTIVE
            preference.root_id = preference.memory_id
            self._mock_db[preference.memory_id] = preference
            return preference.memory_id
        else: # PENDING
            preference.status = MemoryStatus.PENDING
            self._mock_db[preference.memory_id] = preference
            return preference.memory_id

    def update(self, old_id: str, new_preference: PreferenceMemory) -> str:
        """更新版本链条并维护中长期记忆状态"""
        old_pref = self._mock_db.get(old_id)
        if not old_pref:
            new_preference.status = MemoryStatus.ACTIVE
            new_preference.root_id = new_preference.memory_id
            self._mock_db[new_preference.memory_id] = new_preference
            return new_preference.memory_id

        # 检查崩溃回滚
        now = datetime.now(timezone.utc)
        recent_evidences = [
            e for e in old_pref.evidences 
            if (now - (e.timestamp.replace(tzinfo=timezone.utc) if not e.timestamp.tzinfo else e.timestamp)).days <= 7
        ]
        overrides_count = sum(1 for e in recent_evidences if "OVERRIDE" in e.content)

        if len(recent_evidences) >= 3 and (overrides_count / len(recent_evidences)) >= 0.7:
            if old_pref.parent_id and old_pref.parent_id in self._mock_db:
                self._mock_db[old_pref.parent_id].status = MemoryStatus.ACTIVE
                self._mock_db[old_pref.parent_id].updated_at = datetime.now(timezone.utc)
                old_pref.status = MemoryStatus.ARCHIVED
                return old_pref.parent_id
            else:
                old_pref.status = MemoryStatus.DELETED
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
            updated_at=datetime.now(timezone.utc)
        )