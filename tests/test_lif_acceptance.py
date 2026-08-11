# -*- coding: utf-8 -*-
"""LIF-01 ~ LIF-03 生命周期模块专项验收测试。

对应 docs/TEST_PLAN.md 6.9 生命周期(LIF-01~03)，
阈值以 PROJECT_ANALYSIS.md 生命周期设计与实现为准：
  short→mid: 出现次数≥2 且 quality_score≥0.4
  mid→long:  出现次数≥5 且 confidence≥0.7 且 存在≥3 天
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memoryhub.adapter.schemas import (
    EventQuality,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    SourceType,
)
from memoryhub.core.lifecycle.manager import LifecycleManager
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)


def _quality(score: float) -> EventQuality:
    return EventQuality(
        score=score,
        status=QualityStatus.ACCEPTED,
        completeness=1.0,
        validity=1.0,
        consistency=1.0,
        freshness=1.0,
    )


def _event(event_id: str, score: float) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        source_type=SourceType.USER_BEHAVIOR,
        event_type="preference_feedback",
        user_id="u1",
        occurred_at="2026-08-01T00:00:00Z",
        payload={"action": "set_format", "target": "weekly_report", "value": "markdown"},
        source_hash=hashlib.sha256(event_id.encode()).hexdigest(),
        quality=_quality(score),
    )


def _pref(
    memory_id: str,
    level: MemoryLevel = MemoryLevel.SHORT,
    quality_score: float = 1.0,
    confidence: float = 0.9,
    created_at: datetime | None = None,
    text: str = "记忆内容",
) -> PreferenceMemory:
    return PreferenceMemory(
        memory_id=memory_id,
        user_id="u1",
        text=text,
        level=level,
        quality_score=quality_score,
        confidence=confidence,
        created_at=created_at or datetime.now(),
    )


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _make_repos(tmp_path: Path):
    db = Database(str(tmp_path / "lif.db"))
    db.init_schema()
    return db, PreferenceRepository(db), KnowledgeRepository(db)


def test_lif_01_classify_levels_by_event_quality() -> None:
    """LIF-01: 按事件质量分数分类 SHORT/MID/LONG"""
    manager = LifecycleManager()
    assert manager.classify(_event("e-long", 0.9)) is MemoryLevel.LONG
    assert manager.classify(_event("e-mid", 0.5)) is MemoryLevel.MID
    assert manager.classify(_event("e-short", 0.49)) is MemoryLevel.SHORT
    assert manager.classify(_event("e-max", 1.0)) is MemoryLevel.LONG
    assert manager.classify(_event("e-zero", 0.0)) is MemoryLevel.SHORT


def test_lif_02_short_to_mid_thresholds() -> None:
    """LIF-02a: 短→中 需要 出现≥2 次 且 quality≥0.4"""
    manager = LifecycleManager()
    memory = _pref("p", MemoryLevel.SHORT, quality_score=0.9)

    assert manager.should_promote(memory, access_count=1) is False  # 次数不足
    assert manager.should_promote(memory, access_count=2) is True  # 次数达标
    low_quality = _pref("p2", MemoryLevel.SHORT, quality_score=0.39)
    assert manager.should_promote(low_quality, access_count=5) is False  # 质量不足
    boundary = _pref("p3", MemoryLevel.SHORT, quality_score=0.4)
    assert manager.should_promote(boundary, access_count=2) is True  # 边界


def test_lif_02_mid_to_long_thresholds() -> None:
    """LIF-02b: 中→长 需要 出现≥5 次 且 confidence≥0.7 且 存在≥3 天"""
    manager = LifecycleManager()

    ok = _pref("m1", MemoryLevel.MID, confidence=0.9, created_at=_days_ago(5))
    assert manager.should_promote(ok, access_count=5) is True

    few_hits = _pref("m2", MemoryLevel.MID, confidence=0.9, created_at=_days_ago(5))
    assert manager.should_promote(few_hits, access_count=4) is False

    low_conf = _pref("m3", MemoryLevel.MID, confidence=0.69, created_at=_days_ago(5))
    assert manager.should_promote(low_conf, access_count=5) is False

    too_young = _pref("m4", MemoryLevel.MID, confidence=0.9, created_at=_days_ago(2))
    assert manager.should_promote(too_young, access_count=5) is False


def test_lif_02_promote_changes_level(tmp_path: Path) -> None:
    """LIF-02c: promote 按当前层级单级提升,并持久化"""
    db, pref_repo, know_repo = _make_repos(tmp_path)

    short = _pref("p_short", MemoryLevel.SHORT, quality_score=0.9)
    mid = _pref("p_mid", MemoryLevel.MID, confidence=0.9, created_at=_days_ago(5))
    long = _pref("p_long", MemoryLevel.LONG)

    pref_repo.save(short)
    pref_repo.save(mid)
    pref_repo.save(long)

    manager = LifecycleManager(pref_repo=pref_repo, know_repo=know_repo)
    assert manager.promote(short).level is MemoryLevel.MID
    assert manager.promote(mid).level is MemoryLevel.LONG
    assert manager.promote(long).level is MemoryLevel.LONG  # 长期不再提升

    assert pref_repo.get_by_id("p_short").level.value == "mid"
    assert pref_repo.get_by_id("p_mid").level.value == "long"
    db.close()


def test_lif_03_expire_archives_and_removes_from_active(tmp_path: Path) -> None:
    """LIF-03: 过期记忆归档为 archived,不再参与 active 检索"""
    db, pref_repo, know_repo = _make_repos(tmp_path)

    doomed = _pref("p_old", MemoryLevel.LONG, confidence=0.5, created_at=_days_ago(60))
    kept = _pref("p_fresh", MemoryLevel.MID, confidence=0.9)
    pref_repo.save(doomed)
    pref_repo.save(kept)

    class OldHealth:
        def calculate(self, memory):
            return 0.05 if memory.memory_id == "p_old" else 0.9

        def calculate_from_row(self, row):
            return 0.9

    manager = LifecycleManager(
        pref_repo=pref_repo,
        know_repo=know_repo,
        health_calculator=OldHealth(),
    )

    assert manager.should_expire(doomed) is True
    manager.expire(doomed)
    assert pref_repo.get_by_id("p_old").status is MemoryStatus.ARCHIVED
    active_ids = [m.memory_id for m in pref_repo.list_all(status="active")]
    assert "p_old" not in active_ids
    assert "p_fresh" in active_ids
    db.close()


def test_lif_03_run_lifecycle_check_promotes_and_archives(tmp_path: Path) -> None:
    """LIF-03: run_lifecycle_check 一次性完成归档与升级并返回统计"""
    db, pref_repo, know_repo = _make_repos(tmp_path)

    doomed = _pref("p_expire", MemoryLevel.MID, confidence=0.8, created_at=_days_ago(90))
    promoted = _pref("p_up", MemoryLevel.SHORT, quality_score=0.9)
    promoted.access_count_30d = 2
    pref_repo.save(doomed)
    pref_repo.save(promoted)

    class CheckHealth:
        def calculate(self, memory):
            if memory.memory_id == "p_expire":
                return 0.1
            return 1.0

        def calculate_from_row(self, row):
            return 1.0

    manager = LifecycleManager(
        pref_repo=pref_repo,
        know_repo=know_repo,
        health_calculator=CheckHealth(),
    )

    stats = manager.run_lifecycle_check()
    assert stats == {"promoted": 1, "expired": 1, "kept": 0}
    assert pref_repo.get_by_id("p_expire").status is MemoryStatus.ARCHIVED
    assert pref_repo.get_by_id("p_up").level.value == "mid"
    db.close()
