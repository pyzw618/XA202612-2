"""MemoryConsolidator：中期（情景）→ 长期（经统一抽取链）合并（REFACTOR_PLAN_V2 §4.4.2）。"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class MemoryConsolidator:
    """消费中期情景 → 重放事件到统一抽取链 → 长期记忆；情景标记 consolidated（幂等）。"""

    def __init__(self, *, mid_term_repo, event_repo, extraction_executor):
        self.mid_term_repo = mid_term_repo
        self.event_repo = event_repo
        self.extraction_executor = extraction_executor

    def consolidate_episodes(self, user_id: str = "") -> dict:
        stats = {"consolidated": 0, "skipped": 0, "errors": 0}
        episodes = self.mid_term_repo.list_active(user_id=user_id)
        for ep in episodes:
            events = []
            for eid in ep.get("event_ids") or []:
                ev = self.event_repo.get_by_id(eid)
                if ev is not None:
                    events.append(ev)
            if not events:
                self.mid_term_repo.mark_consolidated(ep["episode_id"])
                stats["skipped"] += 1
                continue
            try:
                for event in events:
                    self.extraction_executor.run_preference(event)
                    self.extraction_executor.run_fact(event)
                trajectories: dict[tuple, list] = defaultdict(list)
                for event in events:
                    trajectories[
                        (event.user_id, event.session_id, event.task_type)
                    ].append(event)
                for trajectory in trajectories.values():
                    self.extraction_executor.run_knowledge(trajectory)
                self.mid_term_repo.mark_consolidated(ep["episode_id"])
                stats["consolidated"] += 1
                logger.info("episode consolidated -> long-term: %s events=%d", ep["episode_id"], len(events))
            except Exception:
                logger.exception("episode consolidation failed: %s", ep["episode_id"])
                stats["errors"] += 1
        return stats
