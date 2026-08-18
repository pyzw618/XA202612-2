"""MemoryDegrader：低健康度长期记忆 → 中期情景降级（REFACTOR_PLAN_V2 §4.4.2 反哺流，轻量）。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from memoryhub.adapter.schemas import MemoryDecision, MemoryStatus
from memoryhub.core.forget.health import HealthCalculator

logger = logging.getLogger(__name__)


class MemoryDegrader:
    """长期记忆健康度过低时：写一条中期情景快照，并归档该长期记忆（真实降级）。"""

    def __init__(
        self,
        *,
        pref_repo,
        know_repo,
        mid_term_repo,
        write_service,
        threshold: float = 0.3,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.mid_term_repo = mid_term_repo
        self.write_service = write_service
        self.threshold = float(threshold)
        self.health = HealthCalculator()

    def _long_term_active(self, user_id: str = ""):
        memories = []
        if self.pref_repo is not None:
            memories.extend(self.pref_repo.list_all(status="active"))
        if self.know_repo is not None:
            memories.extend(self.know_repo.list_all(status="active"))
        if user_id:
            memories = [m for m in memories if m.user_id == user_id]
        return memories

    def degrade_low_health(self, user_id: str = "") -> dict:
        degraded = 0
        for memory in self._long_term_active(user_id):
            try:
                if self.health.calculate(memory) >= self.threshold:
                    continue
            except Exception:
                continue
            self._write_episode(memory)
            memory.status = MemoryStatus.ARCHIVED
            self.write_service.upsert_memory(memory, action=MemoryDecision.SUPERSEDE)
            degraded += 1
            logger.info("long-term degraded -> mid episode: %s", memory.memory_id)
        return {"degraded": degraded}

    def _write_episode(self, memory) -> None:
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
            occurred_at=memory.updated_at or datetime.now(timezone.utc),
            status="archived",  # 降级快照，不再回收到长期
        )
