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

    def __init__(self, llm_client=None, db_client=None):
        self.extractor = PreferenceExtractor(llm_client=llm_client)
        self.calculator = ConfidenceCalculator()
        self.updater = PreferenceUpdater(llm_client=llm_client, db_client=db_client)
        self.db_client = db_client  # 可选注入真实的 DB 客户端

    def evolve_preference(self, event: MemoryEvent) -> list[str]:
        """
        偏好演化入口：
        1. 抽取候选偏好与 tags（自动构建基础 Evidence）
        2. 经过 ConflictDetector 与 ConflictResolver 校验，回写 decision 并提交 updater 版本控制
        3. 依据最终的 Evidence（包含 ConflictDecision）重新计算与更新置信度，并二次同步落盘
        """
        processed_ids = []
        candidates = self.extractor.extract(event)

        for candidate in candidates:
            # 步骤 1：提交至 updater（内部完成冲突检测、版本链演进及初步 DB 落盘）
            res_id = self.updater.add(candidate)

            if res_id:
                # 步骤 2：获取更新后的偏好实体
                saved_pref = self.updater._mock_db.get(res_id)
                if saved_pref:
                    # 步骤 3：根据完整的证据链（含 ConflictDecision）重新计算综合置信度
                    self.calculator.calculate(saved_pref)

                    # TODO: [DB 落盘] 置信度重算完成后，将最终的 confidence score 及更新后的 evidences 增量同步至数据库
                    # if self.db_client:
                    #     self.db_client.update_confidence_and_evidences(
                    #         memory_id=saved_pref.memory_id,
                    #         confidence=saved_pref.confidence,
                    #         evidences=saved_pref.evidences,
                    #         updated_at=saved_pref.updated_at
                    #     )

                processed_ids.append(res_id)

        return processed_ids