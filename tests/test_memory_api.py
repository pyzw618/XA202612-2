from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, StorageConfig


def event_payload(text: str, event_id: str = "evt-preference-001") -> dict:
    payload = {
        "action": "message",
        "role": "user",
        "app": "qwen_langgraph_agent",
    }
    source_hash = hashlib.sha256(
        json.dumps({"text": text, "payload": payload}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "event_id": event_id,
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": "u-001",
        "session_id": "session-001",
        "turn_id": "turn-001",
        "scene": "office",
        "task_type": "office.weekly_report",
        "occurred_at": "2026-08-08T08:00:00Z",
        "text": text,
        "payload": payload,
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": source_hash,
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


def make_client(tmp_path) -> TestClient:
    config = AppConfig(storage=StorageConfig(db_path=str(tmp_path / "memoryhub.db")))
    return TestClient(create_app(config))


def test_event_to_search_and_context_round_trip(tmp_path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/memory/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        write = client.post(
            "/api/memory/events",
            json={"events": [event_payload("以后项目周报都使用 Markdown 三段式")]},
        )
        assert write.status_code == 200
        assert write.json() == {
            "accepted": 1,
            "rejected": 0,
            "event_ids": ["evt-preference-001"],
        }

        request = {
            "user_id": "u-001",
            "query": "按上次方式生成项目周报",
            "context": {
                "scene": "office",
                "task_type": "office.weekly_report",
                "app": "qwen_langgraph_agent",
            },
            "top_k": 5,
            "memory_types": ["preference", "knowledge"],
            "min_confidence": 0.5,
        }
        search = client.post("/api/memory/search", json=request)
        assert search.status_code == 200
        assert search.json()["total_count"] == 1
        assert "Markdown 三段式" in search.json()["preferences"][0]["content"]

        context = client.post("/api/memory/context", json=request)
        assert context.status_code == 200
        assert "用户偏好" in context.json()["context"]
        assert "Markdown 三段式" in context.json()["context"]


def test_duplicate_event_is_rejected(tmp_path) -> None:
    event = event_payload("以后项目周报都使用 Markdown")
    with make_client(tmp_path) as client:
        assert (
            client.post("/api/memory/events", json={"events": [event]}).json()[
                "accepted"
            ]
            == 1
        )
        duplicate = client.post("/api/memory/events", json={"events": [event]})
        assert duplicate.json()["accepted"] == 0
        assert duplicate.json()["rejected"] == 1


def test_new_preference_archives_previous_version(tmp_path) -> None:
    first = event_payload("以后项目周报都使用 Markdown", "evt-preference-001")
    second = event_payload("以后项目周报都使用 Word", "evt-preference-002")
    second["source_hash"] = "b" * 64

    with make_client(tmp_path) as client:
        client.post("/api/memory/events", json={"events": [first]})
        client.post("/api/memory/events", json={"events": [second]})
        active = client.get(
            "/api/memory/preferences",
            params={"user_id": "u-001", "scene": "office"},
        )
        assert active.status_code == 200
        assert len(active.json()) == 1
        assert active.json()[0]["content"].endswith("Word")
        assert active.json()[0]["version"] == 2
