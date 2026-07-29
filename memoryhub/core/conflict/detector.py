"""
冲突检测模块

检测新记忆与已有记忆之间的冲突。
"""

from memoryhub.adapter.schemas import (
    PreferenceMemory,
    KnowledgeMemory,
    ConflictRecord,
)


class ConflictDetector:
    """
    冲突检测器

    使用方式:
        detector = ConflictDetector(llm_client=llm)
        conflicts = detector.check_preference(new_pref, existing_prefs)
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def check_preference(
        self, new_pref: PreferenceMemory, existing: list[PreferenceMemory]
    ) -> ConflictRecord | None:
        """
        检测新偏好与已有偏好是否冲突

        数据流:
            新偏好 + 已有偏好列表 → check_preference
              → 同 scope 同 type 的偏好比对
              → 内容语义比对
              → 返回冲突记录或 None

        参数:
            new_pref: 新抽取的候选偏好
            existing: 同 scope 下的已有偏好列表

        返回:
            ConflictRecord（检测到冲突时）或 None（无冲突）

        冲突判定条件:
            1. scope 重叠（同一场景/任务类型）
            2. preference_type 相同
            3. 内容语义矛盾
        """
        raise NotImplementedError

    def check_knowledge(
        self, new_know: KnowledgeMemory, existing: list[KnowledgeMemory]
    ) -> ConflictRecord | None:
        """
        检测新知识与已有知识是否冲突

        数据流:
            新知识 + 已有知识列表 → check_knowledge
              → 同类型知识比对
              → 步骤/流程比对
              → 返回冲突记录或 None

        参数:
            new_know: 新抽取的知识
            existing: 同类型已有知识列表

        返回:
            ConflictRecord 或 None
        """
        raise NotImplementedError

    def _is_same_scope(self, scope_a, scope_b) -> bool:
        """判断两个 scope 是否重叠"""
        raise NotImplementedError

    def _semantic_contradiction(self, text_a: str, text_b: str) -> bool:
        """
        判断两段文本是否语义矛盾

        可使用 LLM 辅助判断。
        """
        raise NotImplementedError

    def _find_similar_preferences(
        self, pref: PreferenceMemory, candidates: list[PreferenceMemory]
    ) -> list[PreferenceMemory]:
        """在候选列表中找到相似偏好（同 scope + 同 type）"""
        raise NotImplementedError
