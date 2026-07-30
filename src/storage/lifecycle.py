"""
记忆生命周期管理器。

三级流转规则:
  SHORT → MID:  occur_count ≥ 2 且 confidence ≥ 0.4
  MID   → LONG: occur_count ≥ 5 且 confidence ≥ 0.7 且存在 ≥ 3 天
  LONG  → EXPIRED: 365 天无更新 → 归档

用法:
    lm = LifecycleManager(pref_repo, know_repo)
    promoted = lm.run_cycle()       # 执行一次检查，返回晋升/淘汰列表
"""

import time
from typing import List, Tuple
from .repositories import PreferenceRepository, KnowledgeRepository
from .models import PreferenceRow, KnowledgeRow


# 默认阈值（可配置）
PROMOTE_THRESHOLDS = {
    "short_to_mid": {"min_occurrences": 2, "min_confidence": 0.4},
    "mid_to_long": {"min_occurrences": 5, "min_confidence": 0.7, "min_days": 3},
    "expire_days": 365,  # 长期记忆无更新超过此天数 → 过期
}


class LifecycleManager:
    """
    生命周期管理。定期调用 run_cycle() 推进记忆流转。

    典型用法：每天定时或每次写入后触发。
    """

    def __init__(
        self,
        pref_repo: PreferenceRepository,
        know_repo: KnowledgeRepository = None,
        thresholds: dict = None,
    ):
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.thresholds = thresholds or PROMOTE_THRESHOLDS

    # ---- 主入口 ----

    def run_cycle(self) -> dict:
        """执行一次完整生命周期检查。返回变更统计。"""
        result = {
            "short_to_mid": self._promote_short_to_mid(),
            "mid_to_long": self._promote_mid_to_long(),
            "expired": self._expire_long(),
        }
        return result

    # ---- SHORT → MID ----

    def _promote_short_to_mid(self) -> int:
        """
        短期 → 中期：
          条件: occur_count ≥ min_occurrences AND confidence ≥ min_confidence
        """
        t = self.thresholds["short_to_mid"]
        rows = self._fetch_prefs("level = 'short' AND status = 'active'")
        count = 0
        for row in rows:
            if row.occur_count >= t["min_occurrences"] and row.confidence >= t["min_confidence"]:
                self.pref_repo.db.execute(
                    "UPDATE preferences SET level = 'mid', updated_at = ? WHERE memory_id = ?",
                    (time.time(), row.memory_id),
                )
                count += 1
        if count:
            self.pref_repo.db.commit()
        return count

    # ---- MID → LONG ----

    def _promote_mid_to_long(self) -> int:
        """
        中期 → 长期：
          条件: occur_count ≥ min_occurrences AND confidence ≥ min_confidence
               AND 存在天数 ≥ min_days
        """
        t = self.thresholds["mid_to_long"]
        rows = self._fetch_prefs("level = 'mid' AND status = 'active'")
        count = 0
        now = time.time()
        for row in rows:
            days_existed = (now - row.created_at) / 86400.0
            if (
                row.occur_count >= t["min_occurrences"]
                and row.confidence >= t["min_confidence"]
                and days_existed >= t["min_days"]
            ):
                self.pref_repo.db.execute(
                    "UPDATE preferences SET level = 'long', updated_at = ? WHERE memory_id = ?",
                    (now, row.memory_id),
                )
                count += 1
        if count:
            self.pref_repo.db.commit()
        return count

    # ---- LONG → EXPIRED ----

    def _expire_long(self) -> int:
        """
        长期 → 归档：
          条件: 距上次更新 ≥ expire_days
        """
        expire_days = self.thresholds["expire_days"]
        rows = self._fetch_prefs("level = 'long' AND status = 'active'")
        count = 0
        now = time.time()
        for row in rows:
            days_stale = (now - row.updated_at) / 86400.0
            if days_stale >= expire_days:
                self.pref_repo.db.execute(
                    "UPDATE preferences SET status = 'archived', updated_at = ? WHERE memory_id = ?",
                    (now, row.memory_id),
                )
                count += 1
        if count:
            self.pref_repo.db.commit()
        return count

    # ---- 工具方法 ----

    def _fetch_prefs(self, where: str) -> List[PreferenceRow]:
        sql = f"SELECT * FROM preferences WHERE {where}"
        cur = self.pref_repo.db.execute(sql)
        return [PreferenceRow.from_row(tuple(r)) for r in cur.fetchall()]

    def get_stats(self) -> dict:
        """查看当前各级别记忆数量。"""
        stats = {}
        for level in ("short", "mid", "long"):
            cur = self.pref_repo.db.execute(
                "SELECT COUNT(*) FROM preferences WHERE level = ? AND status = 'active'",
                (level,),
            )
            stats[level] = cur.fetchone()[0]
        cur = self.pref_repo.db.execute(
            "SELECT COUNT(*) FROM preferences WHERE status = 'archived'"
        )
        stats["archived"] = cur.fetchone()[0]
        return stats
