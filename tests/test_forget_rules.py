# -*- coding: utf-8 -*-
"""I-13 遗忘收尾测试：用户遗忘规则 + 按 level（short/mid）精准遗忘。"""

from __future__ import annotations

from datetime import datetime, timedelta

from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.core.forget.rules import ForgetRuleService
from memoryhub.storage.database import (
    Database,
    MidTermMemoryRepository,
    ShortTermMemoryRepository,
)
from memoryhub.adapter.schemas import ForgetRequest


def _short_repo(db: Database) -> ShortTermMemoryRepository:
    repo = ShortTermMemoryRepository(db)
    repo.add(
        user_id="u1", session_id="s1", event_id="e1", text="正在编辑周报 Markdown",
        scene="office", task_type="office.weekly_report",
        ttl_until=datetime.now() + timedelta(hours=24),
    )
    return repo


def _mid_repo(db: Database) -> MidTermMemoryRepository:
    repo = MidTermMemoryRepository(db)
    repo.add(
        episode_id="ep1", user_id="u1", session_ids=["s1"], scene="office",
        task_type="office.weekly_report", trajectory_summary="完成周报生成",
        occurred_at=datetime.now(),
    )
    return repo


def test_forget_short_term_by_session():
    db = Database(":memory:")
    db.init_schema()
    st = _short_repo(db)
    forgetter = MemoryForgetter(short_term_repo=st)
    result = forgetter.execute(
        ForgetRequest(user_id="u1", level="short", session_id="s1")
    )
    assert result.deleted_count == 1
    assert st.list_by_session("u1", "s1") == []


def test_forget_mid_term():
    db = Database(":memory:")
    db.init_schema()
    mt = _mid_repo(db)
    forgetter = MemoryForgetter(mid_term_repo=mt)
    result = forgetter.execute(ForgetRequest(user_id="u1", level="mid"))
    assert result.deleted_count == 1
    assert mt.list_active(user_id="u1") == []


def test_forget_rule_expands_keywords():
    rules = ForgetRuleService(":memory:")
    rules.create(user_id="u1", topic="周报", keywords=["周报", "weekly_report"])
    forgetter = MemoryForgetter(forget_rule_service=rules)
    intent = forgetter.parse_intent(
        ForgetRequest(user_id="u1", instruction="忘掉所有关于周报的记忆")
    )
    assert "weekly_report" in intent["target_keywords"]


def test_forget_rule_service_crud():
    rules = ForgetRuleService(":memory:")
    created = rules.create(user_id="u1", topic="会议纪要", keywords=["纪要", "meeting"])
    assert created["topic"] == "会议纪要"
    assert len(rules.list("u1")) == 1
    assert "纪要" in rules.active_keywords("u1")["会议纪要"]
    assert rules.delete("u1", created["rule_id"])
    assert rules.list("u1") == []
