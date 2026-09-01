from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from memoryhub.adapter.agent_api import (
    AgentStepRequest,
    ReplayRequest,
    execute_agent_step,
    replay_conversation,
)
from memoryhub.adapter.schemas import KnowledgeMemory, KnowledgeType, SceneScope, SearchResponse
from memoryhub.app import create_app
from memoryhub.config import load_config
from memoryhub.domain.contracts import MemoryScope


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


def test_agent_step_propagates_project_task_session_and_scene():
    captured = []
    canonical_events = []
    legacy_requests = []

    class CapturingCanonical:
        def write(self, event):
            canonical_events.append(event)
            return SimpleNamespace(status="COMMITTED")

    def legacy_search(request):
        legacy_requests.append(request)
        return SearchResponse()

    class CapturingRollout:
        def read(self, request, *, legacy_reader, vnext_reader):
            captured.append(request)
            legacy_reader(request)
            return SimpleNamespace(response=SearchResponse(results=[], latency_ms=0))

    app = SimpleNamespace(
        state=SimpleNamespace(
            event_processor=None,
            canonical_write_service=CapturingCanonical(),
            retriever=SimpleNamespace(memory_lookup={}, search=legacy_search),
            retrieval_service=SimpleNamespace(search=lambda _request: None),
            rollout_read_service=CapturingRollout(),
        )
    )
    body = AgentStepRequest.model_validate(
        {
            "session_id": "session-b",
            "turn_id": "turn-b",
            "user_message": "where am I",
            "project_id": "project-b",
            "task_id": "task-b",
            "scene": "coding",
            "task_type": "debugging",
            "events": [_event()],
        }
    )
    result = asyncio.run(execute_agent_step(body, SimpleNamespace(app=app, headers={})))

    assert result["session_id"] == "session-b"
    assert len(captured) == 1
    request = captured[0]
    assert request.task_id == "task-b"
    assert request.session_id == "session-b"
    assert request.scope_level is MemoryScope.PROJECT
    assert request.scope == "PROJECT:project-b"
    assert len(canonical_events) == 1
    assert canonical_events[0].task_id == "task-b"
    assert canonical_events[0].session_id == "session-b"
    assert canonical_events[0].payload["project_id"] == "project-b"
    assert len(legacy_requests) == 1
    assert legacy_requests[0].project_id == "project-b"
    assert legacy_requests[0].session_id == "session-b"
    assert legacy_requests[0].context.scene == "coding"
    assert legacy_requests[0].context.task_type == "debugging"


def _propose(client: TestClient, object_text: str) -> str:
    response = client.post(
        "/api/memory/facts/propose",
        json={
            "source_id": "demo",
            "scope_hint": "global",
            "user_id": "default",
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
    return response.json()[0]["fact_id"]


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


def test_fact_propose_is_idempotent_via_knowledge_fact(client):
    """/facts/propose 直接写入 knowledge(FACT)；同一三元组幂等，不同客体共存。"""
    test_client, _ = client
    first_id = _propose(test_client, "alice")
    assert first_id

    # 幂等：重复提交同一三元组，仍只有 1 条事实（knowledge 冲突 matcher 去重）
    again_id = _propose(test_client, "alice")
    assert again_id == first_id
    facts = test_client.get("/api/memory/facts").json()
    assert len(facts) == 1
    assert facts[0]["fact_id"] == first_id
    assert facts[0]["object_value"] == "alice"

    # 不同客体：single_value 未标记 → 共存，新增一条事实
    second_id = _propose(test_client, "bob")
    assert second_id != first_id
    facts = test_client.get("/api/memory/facts").json()
    assert {f["object_value"] for f in facts} == {"alice", "bob"}


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
    assert second.json()["used_memory_ids"] == []


def test_long_demo_builds_memory_across_one_multi_turn_session(client):
    test_client, _ = client
    replay_path = Path(__file__).parents[1] / "frontend" / "public" / "examples" / "memory-system-long-replay.json"
    if not replay_path.exists():
        pytest.skip("missing long-demo replay fixture: frontend/public/examples/memory-system-long-replay.json")
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
    assert len(responses[8]["fact_proposals"]) == 2


def test_agent_step_propagates_tenant_from_header_to_canonical_and_retrieval():
    """Agent /step must use the same resolved tenant for canonical write and vNext retrieval."""
    captured_retrieval = []
    captured_canonical = []

    class CapturingCanonical:
        def write(self, event):
            captured_canonical.append(event)
            return SimpleNamespace(status="COMMITTED")

    def legacy_search(request):
        return SearchResponse()

    class CapturingRollout:
        def read(self, request, *, legacy_reader, vnext_reader):
            captured_retrieval.append(request)
            legacy_reader(request)
            return SimpleNamespace(response=SearchResponse(results=[], latency_ms=0))

    app = SimpleNamespace(
        state=SimpleNamespace(
            event_processor=None,
            canonical_write_service=CapturingCanonical(),
            retriever=SimpleNamespace(memory_lookup={}, search=legacy_search),
            retrieval_service=SimpleNamespace(search=lambda _request: None),
            rollout_read_service=CapturingRollout(),
        )
    )
    body = AgentStepRequest.model_validate(
        {
            "session_id": "session-t",
            "turn_id": "turn-t",
            "user_message": "hello",
            "project_id": "project-t",
            "task_id": "task-t",
            "scene": "coding",
            "task_type": "debugging",
            "events": [_event()],
        }
    )
    request = SimpleNamespace(
        app=app,
        headers={"X-MemoryHub-Tenant": "tenant-a"},
    )
    result = asyncio.run(execute_agent_step(body, request))

    assert result["session_id"] == "session-t"
    assert len(captured_canonical) == 1
    assert captured_canonical[0].tenant_id == "tenant-a"
    assert len(captured_retrieval) == 1
    assert captured_retrieval[0].tenant_id == "tenant-a"


def test_agent_step_without_tenant_header_uses_default_tenant():
    """Without X-MemoryHub-Tenant both write and read paths keep the existing default tenant."""
    captured_retrieval = []
    captured_canonical = []

    class CapturingCanonical:
        def write(self, event):
            captured_canonical.append(event)
            return SimpleNamespace(status="COMMITTED")

    def legacy_search(request):
        return SearchResponse()

    class CapturingRollout:
        def read(self, request, *, legacy_reader, vnext_reader):
            captured_retrieval.append(request)
            legacy_reader(request)
            return SimpleNamespace(response=SearchResponse(results=[], latency_ms=0))

    app = SimpleNamespace(
        state=SimpleNamespace(
            event_processor=None,
            canonical_write_service=CapturingCanonical(),
            retriever=SimpleNamespace(memory_lookup={}, search=legacy_search),
            retrieval_service=SimpleNamespace(search=lambda _request: None),
            rollout_read_service=CapturingRollout(),
        )
    )
    body = AgentStepRequest.model_validate(
        {
            "session_id": "session-default",
            "turn_id": "turn-default",
            "user_message": "hello",
            "events": [_event()],
        }
    )
    request = SimpleNamespace(app=app, headers={})
    asyncio.run(execute_agent_step(body, request))

    assert captured_canonical[0].tenant_id == "default"
    assert captured_retrieval[0].tenant_id == "default"


def test_agent_step_does_not_leak_tenant_across_users():
    """A retrieval made under tenant-b must not see a canonical write scoped to tenant-a."""
    captured_retrieval = []
    captured_canonical = []

    class CapturingCanonical:
        def write(self, event):
            captured_canonical.append(event)
            return SimpleNamespace(status="COMMITTED")

    def legacy_search(request):
        return SearchResponse()

    class CapturingRollout:
        def read(self, request, *, legacy_reader, vnext_reader):
            captured_retrieval.append(request)
            legacy_reader(request)
            return SimpleNamespace(response=SearchResponse(results=[], latency_ms=0))

    app = SimpleNamespace(
        state=SimpleNamespace(
            event_processor=None,
            canonical_write_service=CapturingCanonical(),
            retriever=SimpleNamespace(memory_lookup={}, search=legacy_search),
            retrieval_service=SimpleNamespace(search=lambda _request: None),
            rollout_read_service=CapturingRollout(),
        )
    )
    body = AgentStepRequest.model_validate(
        {
            "session_id": "session-isolation",
            "turn_id": "turn-isolation",
            "user_message": "hello",
            "events": [_event()],
        }
    )
    # First, write under tenant-a
    asyncio.run(
        execute_agent_step(
            body,
            SimpleNamespace(app=app, headers={"X-MemoryHub-Tenant": "tenant-a"}),
        )
    )
    # Then read under tenant-b
    asyncio.run(
        execute_agent_step(
            body,
            SimpleNamespace(app=app, headers={"X-MemoryHub-Tenant": "tenant-b"}),
        )
    )

    assert captured_canonical[0].tenant_id == "tenant-a"
    assert captured_retrieval[1].tenant_id == "tenant-b"
    assert captured_canonical[0].tenant_id != captured_retrieval[1].tenant_id


def test_replay_propagates_tenant_from_header_to_canonical():
    """Agent /replay must bind the resolved tenant to canonical events it writes."""
    captured = []

    class CapturingCanonical:
        def write(self, event):
            captured.append(event)
            return SimpleNamespace(status="COMMITTED")

    app = SimpleNamespace(
        state=SimpleNamespace(
            event_processor=None,
            canonical_write_service=CapturingCanonical(),
        )
    )
    body = ReplayRequest.model_validate(
        {
            "schema_version": "conversation-replay/1.0",
            "session_id": "sess_replay_tenant",
            "events": [_event()],
            "execute": True,
        }
    )
    request = SimpleNamespace(app=app, headers={"X-MemoryHub-Tenant": "tenant-replay"})
    response = asyncio.run(replay_conversation(body, request))

    assert response["written_event_ids"] == ["evt_demo_001"]
    assert len(captured) == 1
    assert captured[0].tenant_id == "tenant-replay"
