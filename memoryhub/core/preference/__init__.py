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
    "PreferenceManager"
]


class PreferenceManager:
    """偏好记忆集成管理器"""

    def __init__(self, llm_client=None):
        self.extractor = PreferenceExtractor(llm_client=llm_client)
        self.calculator = ConfidenceCalculator()
        self.updater = PreferenceUpdater(llm_client=llm_client)

    def evolve_preference(self, event: MemoryEvent) -> list[str]:
        """
        偏好演化入口：
        1. 抽取候选偏好与 tags
        2. 更新置信度
        3. 经过 ConflictDetector 与 ConflictResolver 校验并提交 updater 版本控制
        """
        processed_ids = []
        candidates = self.extractor.extract(event)
        
        for candidate in candidates:
            self.calculator.update_confidence(candidate, event)
            res_id = self.updater.add(candidate)
            if res_id:
                processed_ids.append(res_id)
                
        return processed_ids