"""
记忆生命周期管理模块

管理短期、中期、长期记忆之间的流转。
"""

import logging
from datetime import datetime, timezone

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryDecision,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
)
from memoryhub.core.forget.health import HealthCalculator

logger = logging.getLogger(__name__)


class LifecycleManager:
    """记忆生命周期管理器"""

    PROMOTE_THRESHOLDS = {
        "short_to_mid": {"min_occurrences": 2, "min_quality_score": 0.4},
        "mid_to_long": {"min_occurrences": 5, "min_confidence": 0.7, "min_days": 3},
    }
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
        """检查记忆是否满足提升条件（短→中、中→长两档阈值）"""
        level = self._level(memory)
        if level is MemoryLevel.LONG:
            return False
        if level is MemoryLevel.SHORT:
            thresholds = self.PROMOTE_THRESHOLDS["short_to_mid"]
            if access_count < thresholds["min_occurrences"]:
                return False
            if getattr(memory, "quality_score", 0.0) < thresholds["min_quality_score"]:
                return False
            return True
        thresholds = self.PROMOTE_THRESHOLDS["mid_to_long"]
        if access_count < thresholds["min_occurrences"]:
            return False
        if getattr(memory, "confidence", 0.0) < thresholds["min_confidence"]:
            return False
        if self._age_days(memory) < thresholds["min_days"]:
            return False
        return True

    def promote(self, memory):
        """将记忆提升到更高级别"""
        promotion_map = {
            MemoryLevel.SHORT: MemoryLevel.MID,
            MemoryLevel.MID: MemoryLevel.LONG,
        }
        target = promotion_map.get(self._level(memory))
        if target:
            memory.level = target
            self._save(memory, action=MemoryDecision.REVISE)
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
        self._save(memory, action=MemoryDecision.SUPERSEDE)

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
            elif self.should_promote(
                memory, access_count=getattr(memory, "access_count_30d", 0) or 0
            ):
                self.promote(memory)
                stats["promoted"] += 1
            else:
                stats["kept"] += 1

        logger.info(f"生命周期检查完成: {stats}")
        return stats

    def _save(self, memory, *, action: MemoryDecision | str | None = None):
        if isinstance(memory, PreferenceMemory):
            repo = self.pref_repo
        elif isinstance(memory, KnowledgeMemory):
            repo = self.know_repo
        else:
            repo = None
        if repo:
            try:
                write_service = getattr(repo, "write_service", None)
                if write_service is not None:
                    write_service.upsert_memory(memory, action=action)
                else:
                    repo.save(memory)
            except Exception as e:
                logger.warning("生命周期保存记忆 %s 失败: %s", getattr(memory, "memory_id", "?"), e)

    def _level(self, memory) -> MemoryLevel:
        level = getattr(memory, "level", None)
        if isinstance(level, MemoryLevel):
            return level
        value = str(level or "").lower()
        for candidate in MemoryLevel:
            if candidate.value == value:
                return candidate
        return MemoryLevel.SHORT

    def _age_days(self, memory) -> float:
        created = getattr(memory, "created_at", None)
        if not created:
            return 0.0
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                return 0.0
        if created.tzinfo is not None:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()
        return max(0.0, (now - created).total_seconds() / 86400.0)
