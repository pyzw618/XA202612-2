# -*- coding: utf-8 -*-
"""I-4 检索级联 level 过滤测试：/search?level=short|mid|long 按层返回。"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig
from memoryhub.storage.database import Database, MidTermMemoryRepository, ShortTermMemoryRepository


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "level.db"),
            vector_index_path=str(tmp_path / "v"),
            evidence_path=str(tmp_path / "e"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as c:
        yield c


def _event(text: str, event_id: str) -> dict:
    return {
        "event_id": event_id, "source_type": "user_behavior", "event_type": "user_message",
        "user_id": "u-lvl", "session_id": "sess-lvl", "scene": "office",
        "task_type": "office.weekly_report", "occurred_at": "2026-08-08T08:00:00Z",
        "text": text, "payload": {"action": "message"}, "tool_calls": [],
        "schema_version": "1.1", "source_hash": hashlib.sha256(event_id.encode()).hexdigest(),
        "redactions": [],
        "quality": {"score": 1.0, "status": "accepted", "completeness": 1.0,
                    "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": []},
    }


def test_level_long_only_returns_long_results(client: TestClient):
    from memoryhub.adapter.schemas import PreferenceMemory, PreferenceType, SceneScope

    with client:
        state = client.app.state
        pref = PreferenceMemory(
            memory_id="pref-lvl-long",
            user_id="u-lvl",
            preference_type=PreferenceType.FORMAT_PREF,
            text="用户偏好使用 Markdown 格式",
            scene=SceneScope(scene="office", task_type="office.weekly_report"),
            confidence=0.9,
        )
        state.memory_write_service.upsert_memory(pref)
        long_resp = client.post("/api/memory/search", json={
            "user_id": "u-lvl", "session_id": "sess-lvl", "query": "Markdown 格式", "top_k": 10, "level": "long",
        })
        assert long_resp.status_code == 200, long_resp.text
        results = long_resp.json()["results"]
        assert results, long_resp.text
        levels = {res["memory_level"] for res in results}
        assert levels == {"long"}, long_resp.text


def test_level_short_returns_only_short_term(client: TestClient):
    with client:
        state = client.app.state
        st = ShortTermMemoryRepository(state.db)
        from datetime import datetime, timedelta
        st.add(
            user_id="u-lvl", session_id="sess-lvl", event_id="e-short", text="本会话刚发生的上下文",
            scene="office", task_type="office.weekly_report",
            ttl_until=datetime.now() + timedelta(hours=24),
        )
        resp = client.post("/api/memory/search", json={
            "user_id": "u-lvl", "session_id": "sess-lvl", "query": "上下文", "top_k": 10, "level": "short",
        })
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert results, resp.text
        assert all(res["memory_level"] == "short" for res in results)


def test_level_mid_returns_only_mid_term(client: TestClient):
    with client:
        state = client.app.state
        mt = MidTermMemoryRepository(state.db)
        from datetime import datetime
        mt.add(
            episode_id="ep-lvl-1", user_id="u-lvl", session_ids=["sess-lvl"],
            scene="office", task_type="office.weekly_report",
            trajectory_summary="近期完成过周报生成任务", occurred_at=datetime.now(),
        )
        resp = client.post("/api/memory/search", json={
            "user_id": "u-lvl", "query": "周报生成", "top_k": 10, "level": "mid",
        })
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert results, resp.text
        assert all(res["memory_level"] == "mid" for res in results)
