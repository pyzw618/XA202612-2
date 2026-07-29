"""
冲突解决模块

对检测到的冲突进行自动或手动解决。
"""

from memoryhub.adapter.schemas import (
    ConflictRecord,
    ConflictDecision,
    PreferenceMemory,
    KnowledgeMemory,
)


class ConflictResolver:
    """
    冲突解决器

    使用方式:
        resolver = ConflictResolver(llm_client=llm)
        result = resolver.resolve(conflict, old_memory, new_memory)
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def resolve(
        self, conflict: ConflictRecord, old_memory, new_memory
    ) -> ConflictRecord:
        """
        解决冲突

        数据流:
            ConflictRecord + 旧记忆 + 新记忆 → resolve
              → 判断解决策略
              → 执行对应操作
              → 更新 ConflictRecord.decision

        参数:
            conflict: 冲突记录
            old_memory: 旧记忆（PreferenceMemory 或 KnowledgeMemory）
            new_memory: 新记忆

        返回:
            更新后的 ConflictRecord（含 decision 和 reason）

        决策逻辑:
            1. 用户显式反馈 → override
            2. 新旧互补 → merge
            3. 不同场景 → coexist
            4. 无法自动判断 → pending（需用户确认）
        """
        raise NotImplementedError

    def auto_resolve(self, conflict: ConflictRecord) -> ConflictDecision:
        """
        自动判断冲突解决策略

        返回:
            建议的 ConflictDecision

        规则:
            - 新记忆来源为 explicit_feedback → OVERRIDE
            - 新旧内容互补（LLM 判断）→ MERGE
            - scope 不同 → COEXIST
            - 其他 → PENDING
        """
        raise NotImplementedError

    def apply_override(self, old_id: str, new_memory) -> str:
        """
        执行覆盖操作：新记忆替代旧记忆

        返回:
            新记忆的 ID
        """
        raise NotImplementedError

    def apply_merge(self, old_memory, new_memory):
        """
        执行合并操作：将新旧记忆合并

        返回:
            合并后的记忆
        """
        raise NotImplementedError

    def apply_coexist(self, old_memory, new_memory) -> tuple[str, str]:
        """
        执行并存操作：新旧记忆按不同 scope 同时保留

        返回:
            (old_id, new_id)
        """
        raise NotImplementedError

    def manual_resolve(self, conflict_id: str, decision: ConflictDecision, reason: str) -> ConflictRecord:
        """
        手动解决冲突（用户确认后调用）

        参数:
            conflict_id: 冲突 ID
            decision: 用户选择的决策
            reason: 原因说明

        返回:
            更新后的 ConflictRecord
        """
        raise NotImplementedError
