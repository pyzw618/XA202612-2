"""
Preference 模块 — 偏好记忆管理

对外暴露高度集成的偏好生命周期控制器，实现软硬双轨控制与物理回退防御。
"""

from memoryhub.adapter.schemas import MemoryEvent, PreferenceMemory, MemoryStatus
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

    def __init__(self, llm_client=None):
        """
        初始化偏好计算、抽取与版本更新组件
        """
        self.extractor = PreferenceExtractor(llm_client=llm_client)
        self.calculator = ConfidenceCalculator()
        self.updater = PreferenceUpdater()

    def evolve_preference(self, event: MemoryEvent) -> list[str]:
        """
        偏好自适应演化总线

        参数:
            event: 经过 Ingestion 校验后的高质量 MemoryEvent

        返回:
            受影响或全新生成的偏好 memory_id 列表
        """
        processed_ids = []
        
        # 1. 触发抽取器生成候选软/硬偏好
        candidates = self.extractor.extract(event)
        
        # 2. 演化并更新每一条候选偏好
        for candidate in candidates:
            # 更新/平滑置信度
            self.calculator.update_confidence(candidate, event)
            
            # 增量提交至版本管理器（内含崩溃回滚检测）
            res_id = self.updater.add(candidate)
            if res_id:
                processed_ids.append(res_id)
                
        return processed_ids