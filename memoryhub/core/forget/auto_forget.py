"""Automatic forgetting based on memory health."""

import logging

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryDecision,
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
        memory_write_service=None,
        mid_term_repo=None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.db = db
        self.memory_write_service = memory_write_service
        self.mid_term_repo = mid_term_repo
        self.calculator = calculator or HealthCalculator()

    def run(self) -> dict:
        stats = {"archived": 0, "demoted": 0, "reviewed": 0, "kept": 0}
        for memory in self._load_active_memories():
            health = self.calculator.calculate(memory)
            if health < self.ARCHIVE_THRESHOLD:
                self._update_status(memory, MemoryStatus.ARCHIVED, health)
                stats["archived"] += 1
            elif health < self.DEMOTE_THRESHOLD:
                # I-6：与 MemoryDegrader 合并为同一条"健康度→分层反哺"路径——
                # 先写一条真实中期情景快照，再降级/归档，而非仅改 level 字段。
                self._demote_with_episode(memory, health)
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
        return memories

    def _update_status(self, memory, status: MemoryStatus, health: float):
        status_value = status.value if hasattr(status, "value") else str(status)
        repo = self._repo_for(memory)
        if repo is not None:
            try:
                memory.status = status
                memory.health_score = health
                write_service = self.memory_write_service or getattr(
                    repo, "write_service", None
                )
                if write_service is not None:
                    write_service.upsert_memory(memory, action=MemoryDecision.SUPERSEDE)
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
                    write_service.upsert_memory(memory, action=MemoryDecision.REVISE)
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

    def _demote_with_episode(self, memory, health: float) -> None:
        """I-6 深融合：健康度降级 → 先落一条中期情景快照，再更新等级/归档。

        与 MemoryDegrader._write_episode 同一"健康度→分层反哺"语义：长期记忆
        低健康度时保留为可检索的中期情景，而非仅做字段级 level 变更。缺少
        mid_term_repo 时退回旧的字段级降级（不破坏既有调用方）。
        """
        demo_level = self._demote_level(memory)
        if self.mid_term_repo is not None:
            self._write_episode(memory)
        self._update_level(memory, demo_level, health)

    def _write_episode(self, memory) -> None:
        """长期记忆 → 中期情景快照（与 MemoryDegrader._write_episode 对齐）。"""
        import hashlib
        from datetime import datetime, timezone

        text = (
            getattr(memory, "text", "")
            or getattr(memory, "content", "")
            or getattr(memory, "name", "")
        )
        episode_id = f"epi_dg_{hashlib.sha256(str(memory.memory_id).encode()).hexdigest()[:24]}"
        self.mid_term_repo.add(
            episode_id=episode_id,
            user_id=memory.user_id,
            session_ids=[],
            scene=getattr(memory.scope, "scene", "") or "",
            task_type=getattr(memory.scope, "task_type", "") or "",
            event_ids=[],
            trajectory_summary=str(text or "")[:2000],
            tools=[],
            occurred_at=getattr(memory, "updated_at", None) or datetime.now(timezone.utc),
            status="active",
        )

    def _repo_for(self, memory):
        if isinstance(memory, PreferenceMemory):
            return self.pref_repo
        if isinstance(memory, KnowledgeMemory):
            return self.know_repo
        return None
