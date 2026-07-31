"""
偏好生命周期管理器入口
"""

from memoryhub.adapter.schemas import MemoryEvent
from memoryhub.core.preference.confidence import ConfidenceCalculator
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.updater import PreferenceUpdater

__all__ = [
    "ConfidenceCalculator",
    "PreferenceExtractor",
    "PreferenceUpdater",
    "PreferenceManager",
]


class PreferenceManager:
    """偏好记忆集成管理器"""

    def __init__(self, llm_client=None, db_client=None, pref_repo=None):
        self.extractor = PreferenceExtractor(llm_client=llm_client)
        self.calculator = ConfidenceCalculator()
        self.updater = PreferenceUpdater(llm_client=llm_client, db_client=db_client, pref_repo=pref_repo)
        self.pref_repo = pref_repo

    def evolve_preference(self, event: MemoryEvent) -> list[str]:
        """
        偏好演化入口：
        1. 抽取候选偏好与 tags
        2. 经过冲突检测与解决，提交 updater 版本控制
        3. 重新计算置信度并同步落盘
        """
        processed_ids = []
        candidates = self.extractor.extract(event)

        for candidate in candidates:
            res_id = self.updater.add(candidate)
            if res_id:
                # 获取更新后的偏好实体并重算置信度
                saved_pref = self.updater._get(res_id)
                if saved_pref:
                    self.calculator.calculate(saved_pref)
                    # 落盘：置信度重算后保存
                    if self.pref_repo:
                        self.pref_repo.save(saved_pref)
                processed_ids.append(res_id)

        return processed_ids