# -*- coding: utf-8 -*-
"""I-15 双轨合一契约测试：同一事件经 REST 与 /api/agent/replay 产出记忆一致。

R1 双轨合一验收（REFACTOR_PLAN_V2 §4.9 / PHASE_A）：
- Track A（REST）：POST /api/memory/events → EventIngestionService.ingest
- Track B（Agent）：POST /api/agent/replay → EventProcessingCoordinator.process
两者对同一事件应沉淀一致的偏好/知识记忆集合（忽略各自生成的 memory_id 差异，
按规范化内容比较）。同时覆盖：跨用户隔离、两次消费幂等。
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "dual.db"),
            vector_index_path=str(tmp_path / "v"),
            evidence_path=str(tmp_path / "e"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as c:
        yield c


def _event_payload(event_id: str, user_id: str, text: str) -> dict:
    return {
        "event_id": event_id,
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": user_id,
        "session_id": f"sess_{user_id}",
        "turn_id": "turn-1",
        "scene": "office",
        "task_type": "office.weekly_report",
        "occurred_at": "2026-08-08T08:00:00Z",
        "text": text,
        "payload": {"action": "message"},
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": hashlib.sha256(
            f"{event_id}:{user_id}:{text}".encode()
        ).hexdigest(),
        "redactions": [],
        "quality": {
            "score": 1.0,
            "status": "accepted",
            "completeness": 1.0,
            "validity": 1.0,
            "consistency": 1.0,
            "freshness": 1.0,
            "issues": [],
        },
    }


def _snapshot(client: TestClient, user_id: str) -> set[tuple]:
    """规范化记忆集合：按 (type, text, pref_type/name, scope) 忽略 memory_id 比较。"""
    state = client.app.state
    snap: set[tuple] = set()
    for pref in state.pref_repo.list_all(status="active", user_id=user_id) or []:
        snap.add(
            (
                "preference",
                str(getattr(pref, "text", "") or "").strip(),
                str(getattr(pref, "preference_type", "") or ""),
            )
        )
    for know in state.know_repo.list_all(status="active", user_id=user_id) or []:
        snap.add(
            (
                "knowledge",
                str(getattr(know, "content", "") or str(getattr(know, "name", "")) or "").strip(),
                str(getattr(know, "knowledge_type", "") or ""),
            )
        )
    return snap


def test_rest_and_replay_produce_identical_memories(client: TestClient) -> None:
    """同一事件分别经 REST /events 与 /api/agent/replay 进入，产出记忆集合一致。"""
    text = "以后写项目材料时请使用 Markdown 格式"
    rest_payload = _event_payload("evt-dual-rest", "u-rest", text)
    replay_payload = _event_payload("evt-dual-replay", "u-replay", text)

    # Track A：REST /events
    r = client.post("/api/memory/events", json={"events": [rest_payload]})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1

    # Track B：/api/agent/replay（execute）
    rb = client.post(
        "/api/agent/replay",
        json={
            "schema_version": "conversation-replay/1.0",
            "session_id": "sess_u-replay",
            "events": [replay_payload],
            "execute": True,
        },
    )
    assert rb.status_code == 200, rb.text
    body = rb.json()
    assert body["written_event_ids"] == ["evt-dual-replay"]

    rest_snap = _snapshot(client, "u-rest")
    replay_snap = _snapshot(client, "u-replay")

    # 双轨都对同一文本沉淀至少一条偏好，且规范化集合一致
    assert rest_snap, "REST 路径未沉淀偏好"
    assert replay_snap, "Replay 路径未沉淀偏好"
    assert rest_snap == replay_snap, (
        f"双轨记忆不一致\nREST: {rest_snap}\nReplay: {replay_snap}"
    )


def test_replay_is_idempotent_and_user_isolated(client: TestClient) -> None:
    """同一事件重复 replay 不重复写入；不同用户记忆互不串扰。"""
    payload = _event_payload("evt-dual-idem", "u-a", "以后请使用中文")
    req = {
        "schema_version": "conversation-replay/1.0",
        "session_id": "sess_u-a",
        "events": [payload],
        "execute": True,
    }
    first = client.post("/api/agent/replay", json=req)
    second = client.post("/api/agent/replay", json=req)
    assert first.json()["written_event_ids"] == ["evt-dual-idem"]
    assert second.json()["written_event_ids"] == []  # 幂等

    a_snap = _snapshot(client, "u-a")
    b_snap = _snapshot(client, "u-b")
    assert a_snap and not b_snap  # 跨用户隔离：u-b 无记忆
