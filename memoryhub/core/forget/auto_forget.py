"""Automatic forgetting based on memory health."""

import logging

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
)
from memoryhub.core.forget.health import HealthCalculator

logger = logging.getLogger(__name__)


class AutoForgetEngine:
    """Scan active preference, knowledge, and fact memories for lifecycle actions."""

    ARCHIVE_THRESHOLD = 0.2
    DEMOTE_THRESHOLD = 0.4
    REVIEW_THRESHOLD = 0.6

    def __init__(
        self,
        pref_repo=None,
        know_repo=None,
        db=None,
        calculator=None,
        fact_store=None,
        fact_index_service=None,
        memory_write_service=None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.db = db
        self.fact_store = fact_store
        self.fact_index_service = fact_index_service
        self.memory_write_service = memory_write_service
        self.calculator = calculator or HealthCalculator()

    def run(self) -> dict:
        stats = {"archived": 0, "demoted": 0, "reviewed": 0, "kept": 0}
        for memory in self._load_active_memories():
            is_fact = getattr(memory, "memory_type", "") == "fact"
            health = (
                self.calculator.calculate_from_row(memory)
                if is_fact
                else self.calculator.calculate(memory)
            )
            if health < self.ARCHIVE_THRESHOLD:
                self._update_status(memory, MemoryStatus.ARCHIVED, health)
                stats["archived"] += 1
            elif health < self.DEMOTE_THRESHOLD:
                if is_fact:
                    self._update_status(memory, MemoryStatus.PENDING, health)
                    stats["reviewed"] += 1
                else:
                    self._update_level(memory, self._demote_level(memory), health)
                    stats["demoted"] += 1
            elif health < self.REVIEW_THRESHOLD:
                self._update_status(memory, MemoryStatus.PENDING, health)
                stats["reviewed"] += 1
            else:
                stats["kept"] += 1
        logger.info("自动遗忘扫描完成: %s", stats)
        return stats

    def _load_active_memories(self) -> list:
        memories = []
        if self.pref_repo is not None:
            memories.extend(self.pref_repo.list_all(status="active"))
        if self.know_repo is not None:
            memories.extend(self.know_repo.list_all(status="active"))
        if self.fact_store is not None:
            memories.extend(self.fact_store.list_facts(status="active", limit=100000))
        return memories

    def _update_status(self, memory, status: MemoryStatus, health: float):
        status_value = status.value if hasattr(status, "value") else str(status)
        if getattr(memory, "memory_type", "") == "fact":
            if self.fact_store is None:
                return
            try:
                changed = self.fact_store.update_fact_status(
                    memory.fact_id, status_value, user_id=memory.user_id
                )
                if changed and self.fact_index_service is not None:
                    current = self.fact_store.get_fact(
                        memory.fact_id, user_id=memory.user_id
                    )
                    if current is not None:
                        self.fact_index_service.sync_fact(current)
            except Exception as exc:
                logger.warning("事实状态更新失败 %s: %s", memory.fact_id, exc)
            return

        repo = self._repo_for(memory)
        if repo is not None:
            try:
                memory.status = status
                memory.health_score = health
                write_service = self.memory_write_service or getattr(
                    repo, "write_service", None
                )
                if write_service is not None:
                    write_service.upsert_memory(memory)
                else:
                    repo.update_status(
                        memory.memory_id, status_value, user_id=memory.user_id
                    )
            except Exception as exc:
                logger.warning("记忆状态更新失败 %s: %s", memory.memory_id, exc)

    def _update_level(self, memory, level: MemoryLevel, health: float):
        repo = self._repo_for(memory)
        if repo is not None:
            try:
                memory.level = level
                memory.health_score = health
                write_service = self.memory_write_service or getattr(
                    repo, "write_service", None
                )
                if write_service is not None:
                    write_service.upsert_memory(memory)
                else:
                    repo.save(memory)
            except Exception as exc:
                logger.warning("等级更新失败 %s: %s", memory.memory_id, exc)

    @staticmethod
    def _demote_level(memory) -> MemoryLevel:
        current = memory.level.value if hasattr(memory.level, "value") else memory.level
        return {
            "long": MemoryLevel.MID,
            "mid": MemoryLevel.SHORT,
        }.get(str(current).lower(), MemoryLevel.SHORT)

    def _repo_for(self, memory):
        if isinstance(memory, PreferenceMemory):
            return self.pref_repo
        if isinstance(memory, KnowledgeMemory):
            return self.know_repo
        return None
