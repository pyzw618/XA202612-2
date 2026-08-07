from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import KnowledgeMemory, KnowledgeType, SceneScope
from memoryhub.app import create_app
from memoryhub.config import load_config


@pytest.fixture()
def client(tmp_path: Path):
    config = load_config()
    config.storage.db_path = str(tmp_path / "memoryhub.db")
    config.storage.vector_index_path = str(tmp_path / "vector")
    config.storage.evidence_path = str(tmp_path / "evidence")
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client, app


def _event() -> dict:
    return {
        "event_id": "evt_demo_001",
        "source_type": "tool_result",
        "event_type": "agent_response",
        "user_id": "default",
        "session_id": "sess_demo",
        "turn_id": "turn_001",
        "scene": "office",
        "task_type": "weekly_report",
        "occurred_at": "2026-08-05T10:00:00Z",
        "text": "report generated",
        "payload": {"used_memory_ids": ["know_1"]},
        "tool_calls": [
            {
                "call_id": "call_1",
                "tool_name": "file_search",
                "arguments": {"query": "report"},
                "result": {"files": ["report.md"], "email": "demo@example.com"},
                "status": "success",
                "sequence": 1,
                "error": "",
            }
        ],
        "schema_version": "1.1",
        "source_hash": "a" * 64,
        "redactions": [],
        "quality": {
            "score": 1,
            "status": "accepted",
            "completeness": 1,
            "validity": 1,
            "consistency": 1,
            "freshness": 1,
            "issues": [],
        },
    }


def test_health_endpoint_is_minimal_and_ready(client):
    test_client, _ = client
    response = test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Kylin-MemoryHub",
        "version": "0.1.0",
    }


def _propose(client: TestClient, object_text: str) -> str:
    response = client.post(
        "/api/memory/facts/propose",
        json={
            "source_id": "demo",
            "scope_hint": "global",
            "triples": [
                {
                    "subject_text": "project-a",
                    "predicate_text": "owner",
                    "object_text": object_text,
                    "evidence": f"project-a owner is {object_text}",
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 200
    return response.json()[0]["proposal_id"]


def test_replay_is_read_only_until_execute_and_masks_tool_results(client):
    test_client, app = client
    payload = {
        "schema_version": "conversation-replay/1.0",
        "session_id": "sess_demo",
        "events": [_event()],
    }
    preview = test_client.post("/api/agent/replay", json=payload)
    assert preview.status_code == 200
    assert preview.json()["read_only"] is True
    assert preview.json()["events"][0]["tool_calls"][0]["result"]["email"] == "[REDACTED_EMAIL]"
    assert test_client.get("/api/memory/events/session/sess_demo").json() == []

    first = test_client.post("/api/agent/replay", json={**payload, "execute": True})
    second = test_client.post("/api/agent/replay", json={**payload, "execute": True})
    assert first.json()["written_event_ids"] == ["evt_demo_001"]
    assert second.json()["written_event_ids"] == []
    assert len(test_client.get("/api/memory/events/session/sess_demo").json()) == 1


def test_fact_propose_commit_is_idempotent_and_conflict_waits_for_decision(client):
    test_client, _ = client
    first_id = _propose(test_client, "alice")
    first = test_client.post(
        f"/api/agent/actions/{first_id}/decision",
        json={"action_type": "fact_commit", "payload": {"scope": "global"}},
    )
    assert first.json()["status"] == "committed"
    again = test_client.post(
        f"/api/agent/actions/{first_id}/decision",
        json={"action_type": "fact_commit", "payload": {"scope": "global"}},
    )
    assert again.json()["fact"]["fact_id"] == first.json()["fact"]["fact_id"]

    second_id = _propose(test_client, "bob")
    pending = test_client.post(
        f"/api/agent/actions/{second_id}/decision",
        json={"action_type": "fact_commit", "payload": {"scope": "global"}},
    )
    assert pending.json()["requires_decision"] is True
    assert len(test_client.get("/api/memory/facts").json()) == 1

    resolved = test_client.post(
        f"/api/agent/actions/{second_id}/decision",
        json={
            "action_type": "fact_commit",
            "payload": {"scope": "global", "resolution": "replace"},
        },
    )
    assert resolved.json()["status"] == "committed"
    facts = test_client.get("/api/memory/facts").json()
    assert len(facts) == 1
    assert facts[0]["object_value"] == "bob"


def test_knowledge_filter_and_forget_preview_do_not_mutate(client):
    test_client, app = client
    workflow = KnowledgeMemory(
        user_id="default",
        knowledge_type=KnowledgeType.WORKFLOW,
        name="weekly workflow",
        content="generate weekly report",
        steps=["search", "write"],
        tools=["file_search", "report_writer"],
        scope=SceneScope(scene="office", task_type="weekly_report"),
        confidence=0.9,
    )
    template = KnowledgeMemory(
        user_id="default",
        knowledge_type=KnowledgeType.TEMPLATE,
        name="weekly template",
        content="weekly report template",
        template_body="# Summary",
        scope=SceneScope(scene="office", task_type="weekly_report"),
        confidence=0.8,
    )
    app.state.know_repo.save(workflow)
    app.state.know_repo.save(template)

    workflows = test_client.get(
        "/api/memory/knowledge", params={"knowledge_type": "workflow"}
    ).json()
    templates = test_client.get(
        "/api/memory/knowledge", params={"knowledge_type": "template"}
    ).json()
    assert [item["knowledge_type"] for item in workflows] == ["workflow"]
    assert [item["knowledge_type"] for item in templates] == ["template"]

    preview = test_client.post(
        "/api/memory/forget/preview",
        json={"instruction": "forget weekly template", "user_id": "default"},
    )
    assert preview.status_code == 200
    assert template.memory_id in preview.json()["candidate_ids"]
    assert app.state.know_repo.get_by_id(template.memory_id).status.value == "active"


def test_agent_step_extracts_memory_from_raw_dialogue_and_retrieves_it(client):
    test_client, _ = client
    event = _event()
    event["event_id"] = "evt_structured_preference"
    event["user_id"] = "demo_user"
    event["source_type"] = "user_behavior"
    event["event_type"] = "user_message"
    event["scene"] = "chat"
    event["task_type"] = "memory_demo"
    event["tool_calls"] = []
    event["text"] = "以后给我写项目材料时，请使用中文，内容尽量简洁，先给结论，再列要点。"
    event["payload"] = {"raw_role": "user"}
    payload = {
        "session_id": "sess_demo",
        "turn_id": "turn_001",
        "user_message": "请记住使用中文",
        "retrieval_query": "中文 项目材料",
        "events": [event],
    }
    first = test_client.post("/api/agent/step", json=payload)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["written_event_ids"] == ["evt_structured_preference"]
    assert len(body["processing"]["preferences_written"]) == 3, body["processing"]["warnings"]
    second = test_client.post("/api/agent/step", json=payload)
    assert second.status_code == 200
    assert second.json()["written_event_ids"] == []
    summaries = [item["summary"] for item in second.json()["candidate_memories"]]
    assert "项目材料默认使用中文。" in summaries
    assert second.json()["used_memory_ids"]


def test_long_demo_builds_memory_across_one_multi_turn_session(client):
    test_client, _ = client
    replay_path = Path(__file__).parents[1] / "frontend" / "public" / "examples" / "memory-system-long-replay.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    events_by_turn = {event["turn_id"]: [event] for event in replay["events"]}

    responses = []
    for turn in replay["turns"][:9]:
        event = events_by_turn[turn["turn_id"]][0]
        response = test_client.post(
            "/api/agent/step",
            json={
                "session_id": replay["session_id"],
                "turn_id": turn["turn_id"],
                "user_message": turn["user_message"],
                "retrieval_query": turn.get("retrieval_query", turn["user_message"]),
                "scene": event.get("scene", "chat"),
                "task_type": event.get("task_type", "memory_demo"),
                "events": [event],
            },
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())

    assert len(responses[0]["processing"]["preferences_written"]) == 3
    assert any(item["memory_type"] == "preference" for item in responses[1]["candidate_memories"])
    assert any(responses[4]["processing"]["knowledge_written"])
    assert any(item.get("knowledge_type") == "workflow" for item in responses[5]["candidate_memories"])
    assert any(item.get("knowledge_type") == "template" for item in responses[7]["candidate_memories"])
    assert len(responses[8]["fact_proposals"]) == 1
