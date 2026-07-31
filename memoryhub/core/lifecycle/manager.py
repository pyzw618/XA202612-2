"""
记忆生命周期管理模块

管理短期、中期、长期记忆之间的流转。
"""

import logging
from memoryhub.adapter.schemas import MemoryEvent, MemoryLevel, MemoryStatus
from memoryhub.core.forget.health import HealthCalculator

logger = logging.getLogger(__name__)


class LifecycleManager:
    """记忆生命周期管理器"""

    PROMOTE_THRESHOLDS = {"access_count": 5, "min_confidence": 0.5, "min_stability": 0.6}
    DEMOTE_THRESHOLDS = {"max_stability": 0.2, "max_health": 0.4}
    HEALTH_ARCHIVE_THRESHOLD = 0.2

    def __init__(self, pref_repo=None, know_repo=None, health_calculator=None):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.health_calculator = health_calculator or HealthCalculator()

    def classify(self, event: MemoryEvent) -> MemoryLevel:
        """根据事件质量分配初始记忆级别"""
        quality = getattr(event, "quality", None)
        if quality is not None and hasattr(quality, "score"):
            score = quality.score
        else:
            score = 0.5
        if score >= 0.8:
            return MemoryLevel.LONG
        elif score >= 0.5:
            return MemoryLevel.MID
        return MemoryLevel.SHORT

    def should_promote(self, memory, access_count: int = 0) -> bool:
        """检查记忆是否满足提升条件"""
        thresholds = self.PROMOTE_THRESHOLDS
        if access_count < thresholds["access_count"]:
            return False
        if getattr(memory, "confidence", 0.0) < thresholds["min_confidence"]:
            return False
        if getattr(memory, "stability", 0.0) < thresholds["min_stability"]:
            return False
        return True

    def promote(self, memory):
        """将记忆提升到更高级别"""
        current = memory.level
        promotion_map = {"short": MemoryLevel.MID, "mid": MemoryLevel.LONG}
        target = promotion_map.get(current.value if hasattr(current, "value") else str(current).lower())
        if target:
            memory.level = target
            self._save(memory)
        return memory

    def should_expire(self, memory) -> bool:
        """检查记忆是否应被归档"""
        try:
            health = self.health_calculator.calculate(memory)
            return health < self.HEALTH_ARCHIVE_THRESHOLD
        except Exception:
            return False

    def expire(self, memory):
        """归档记忆"""
        memory.status = MemoryStatus.ARCHIVED
        self._save(memory)

    def run_lifecycle_check(self) -> dict:
        """执行一次完整的生命周期检查"""
        stats = {"promoted": 0, "expired": 0, "kept": 0}
        memories = []
        if self.pref_repo:
            memories.extend(self.pref_repo.list_all(status="active"))
        if self.know_repo:
            memories.extend(self.know_repo.list_all(status="active"))

        for memory in memories:
            if self.should_expire(memory):
                self.expire(memory)
                stats["expired"] += 1
            elif self.should_promote(memory):
                self.promote(memory)
                stats["promoted"] += 1
            else:
                stats["kept"] += 1

        logger.info(f"生命周期检查完成: {stats}")
        return stats

    def _save(self, memory):
        repo = self.pref_repo or self.know_repo
        if repo:
            try:
                repo.save(memory)
            except Exception as e:
                logger.warning(f"生命周期保存失败: {e}")
