"""SessionConsolidator：短期（工作记忆）→ 中期（情景）聚合（REFACTOR_PLAN_V2 §4.4.2）。"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class SessionConsolidator:
    """把短期事件缓冲按 (user, session, task) 聚合成中期情景。"""

    def __init__(self, *, short_term_repo, mid_term_repo, event_repo):
        self.short_term_repo = short_term_repo
        self.mid_term_repo = mid_term_repo
        self.event_repo = event_repo

    def consolidate_sessions(self, user_id: str = "", now: datetime | None = None) -> list[str]:
        """聚合过期会话 → 中期情景；清理对应短期记录。返回新建 episode_id 列表。"""
        records = self.short_term_repo.list_all(user_id=user_id)
        groups: dict[tuple, list[dict]] = {}
        for rec in records:
            key = (rec["user_id"], rec["session_id"] or "", rec["task_type"] or "")
            groups.setdefault(key, []).append(rec)

        created: list[str] = []
        for (uid, sid, task), recs in groups.items():
            if not sid:
                continue  # 无会话 id 的事件不聚合为情景
            episode_id = f"epi_{hashlib.sha256(f'{uid}:{sid}:{task}'.encode()).hexdigest()[:24]}"
            event_ids = sorted({r["event_id"] for r in recs if r.get("event_id")})
            events = [
                ev
                for eid in event_ids
                if (ev := self.event_repo.get_by_id(eid)) is not None
            ]
            summary = "；".join(e.text for e in events if getattr(e, "text", ""))[:2000]
            tools = sorted(
                {
                    c.tool_name
                    for e in events
                    for c in list(getattr(e, "tool_calls", []) or [])
                    if getattr(c, "tool_name", "")
                }
            )
            occurred_at = None
            for e in events:
                parsed = _parse_dt(getattr(e, "occurred_at", "") or "")
                if parsed is not None and (occurred_at is None or parsed < occurred_at):
                    occurred_at = parsed
            self.mid_term_repo.add(
                episode_id=episode_id,
                user_id=uid,
                session_ids=[sid],
                scene=recs[0].get("scene", "") or "",
                task_type=task,
                event_ids=event_ids,
                trajectory_summary=summary,
                tools=tools,
                occurred_at=occurred_at or datetime.now(timezone.utc),
            )
            self.short_term_repo.delete_for_session(uid, sid, task)
            created.append(episode_id)
            logger.info("session consolidated: %s user=%s session=%s events=%d", episode_id, uid, sid, len(event_ids))
        return created
