"""自动遗忘引擎 — 基于健康度的被动遗忘"""

import logging

from memoryhub.adapter.schemas import MemoryLevel, MemoryStatus
from memoryhub.core.forget.health import HealthCalculator

logger = logging.getLogger(__name__)


class AutoForgetEngine:
    """
    自动遗忘引擎：定期扫描所有活跃记忆，基于健康度决定归档/降级/审查。

    使用方式:
        engine = AutoForgetEngine(pref_repo=pref_repo, know_repo=know_repo, db=db)
        stats = engine.run()
    """

    ARCHIVE_THRESHOLD = 0.2   # 健康度 < 0.2 → 归档
    DEMOTE_THRESHOLD = 0.4    # 健康度 < 0.4 → 降级
    REVIEW_THRESHOLD = 0.6    # 健康度 < 0.6 → 待审查

    def __init__(self, pref_repo=None, know_repo=None, db=None, calculator=None):
        """
        参数:
            pref_repo: PreferenceRepository 实例
            know_repo: KnowledgeRepository 实例
            db: Database 实例（向后兼容）
            calculator: HealthCalculator 实例
        """
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.db = db
        self.calculator = calculator or HealthCalculator()

    def run(self) -> dict:
        """
        执行一次自动遗忘扫描。

        返回:
            {"archived": int, "demoted": int, "reviewed": int, "kept": int}
        """
        stats = {"archived": 0, "demoted": 0, "reviewed": 0, "kept": 0}

        active_memories = self._load_active_memories()

        for memory in active_memories:
            health = self.calculator.calculate(memory)

            if health < self.ARCHIVE_THRESHOLD:
                self._update_status(memory, MemoryStatus.ARCHIVED, health)
                stats["archived"] += 1
            elif health < self.DEMOTE_THRESHOLD:
                new_level = self._demote_level(memory)
                self._update_level(memory, new_level, health)
                stats["demoted"] += 1
            elif health < self.REVIEW_THRESHOLD:
                self._update_status(memory, MemoryStatus.PENDING, health)
                stats["reviewed"] += 1
            else:
                stats["kept"] += 1

        logger.info(f"自动遗忘扫描完成: {stats}")
        return stats

    def _load_active_memories(self) -> list:
        """从数据库加载所有活跃记忆"""
        memories = []
        if self.pref_repo is not None:
            memories.extend(self.pref_repo.list_all(status="active"))
        if self.know_repo is not None:
            memories.extend(self.know_repo.list_all(status="active"))
        return memories

    def _update_status(self, memory, status: MemoryStatus, health: float):
        """更新记忆状态"""
        repo = self._repo_for(memory)
        if repo is not None:
            try:
                repo.update_status(memory.memory_id, status.value if hasattr(status, "value") else str(status))
            except Exception as e:
                logger.warning(f"更新记忆状态失败 {memory.memory_id}: {e}")

    def _update_level(self, memory, level: MemoryLevel, health: float):
        """更新记忆级别"""
        repo = self._repo_for(memory)
        if repo is not None:
            try:
                level_str = level.value if hasattr(level, "value") else str(level)
                repo.update_status(memory.memory_id, memory.status.value if hasattr(memory.status, "value") else str(memory.status))
            except Exception as e:
                logger.warning(f"更新记忆级别失败 {memory.memory_id}: {e}")

    def _demote_level(self, memory) -> MemoryLevel:
        """根据当前级别确定降级目标"""
        current = memory.level
        if hasattr(current, "value"):
            current = current.value
        demotion_map = {
            "long": MemoryLevel.MID,
            "mid": MemoryLevel.SHORT,
        }
        return demotion_map.get(str(current).lower(), MemoryLevel.SHORT)

    def _repo_for(self, memory):
        """根据记忆类型返回对应的 Repository"""
        memory_type = getattr(memory, "memory_type", "")
        if memory_type == "preference":
            return self.pref_repo
        elif memory_type == "knowledge":
            return self.know_repo
        # fallback: try both
        return self.pref_repo or self.know_repo
