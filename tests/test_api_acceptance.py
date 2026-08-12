# -*- coding: utf-8 -*-
"""第 7 章 REST API 契约专项验收测试。

对应 docs/TEST_PLAN.md 7 REST API 契约测试（API）：
覆盖全部端点：正向(200)、参数校验(422)、不存在(404)、稳定错误码。
user-rules CRUD 由 SEC-15~17 / test_user_rule_api.py 覆盖，此处不重复。
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        # These API contract tests do not provide an authenticated identity
        # resolver. Disable only user-defined rules so the real built-in safety
        # gate is still provisioned and every explicit write remains gated.
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as test_client:
        yield test_client


def _event_payload(text: str, event_id: str = "evt-api-001") -> dict:
    source_hash = hashlib.sha256(json.dumps({"text": text}, sort_keys=True).encode()).hexdigest()
    return {
        "event_id": event_id,
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": "u-api",
        "session_id": "session-api",
        "turn_id": "turn-api",
        "scene": "office",
        "task_type": "office.weekly_report",
        "occurred_at": "2026-08-08T08:00:00Z",
        "text": text,
        "payload": {"action": "message"},
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


def _write_event(client: TestClient, text: str, event_id: str) -> None:
    resp = client.post("/api/memory/events", json={"events": [_event_payload(text, event_id)]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["accepted"] == 1


def test_api_01_health_returns_200(client: TestClient) -> None:
    """GET /health → 200,服务状态"""
    resp = client.get("/api/memory/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_api_02_events_write_round_trip(client: TestClient) -> None:
    """POST /events → 200,事件可被搜索/注入上下文"""
    _write_event(client, "以后项目周报都使用 Markdown 三段式", "evt-api-002")
    resp = client.post("/api/memory/search", json={"user_id": "u-api", "query": "周报", "top_k": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_count"] >= 1 or body["preferences"]

    ctx = client.post("/api/memory/context", json={"user_id": "u-api", "query": "周报", "top_k": 5})
    assert ctx.status_code == 200, ctx.text
    assert ctx.json()["context"]


def test_api_03_preferences_list_detail_versions(client: TestClient) -> None:
    """GET /preferences[/{id}[/versions]] → 200,支持 scene/status 过滤"""
    _write_event(client, "以后会议纪要都使用 Markdown 格式", "evt-api-003")
    pref = client.get("/api/memory/preferences", params={"user_id": "u-api"}).json()
    assert len(pref) >= 1
    memory_id = pref[0]["memory_id"]

    detail = client.get(f"/api/memory/preferences/{memory_id}", params={"user_id": "u-api"})
    assert detail.status_code == 200
    assert detail.json()["memory_id"] == memory_id

    versions = client.get(f"/api/memory/preferences/{memory_id}/versions")
    assert versions.status_code == 200

    scene_filtered = client.get(
        "/api/memory/preferences", params={"user_id": "u-api", "scene": "office"}
    ).json()
    assert len(scene_filtered) >= 1

    archived = client.get(
        "/api/memory/preferences", params={"user_id": "u-api", "status": "archived"}
    ).json()
    assert isinstance(archived, list)


def test_api_04_knowledge_list_detail_filter(client: TestClient) -> None:
    """GET /knowledge[/{id}] → 200,支持 type 过滤"""
    resp = client.post(
        "/api/memory/memories/knowledge",
        json={
            "user_id": "u-api",
            "name": "周报生成流程",
            "content": "收集→生成→填充",
            "knowledge_type": "workflow",
        },
    )
    assert resp.status_code == 200, resp.text
    memory_id = resp.json()["memory_id"]

    listing = client.get(
        "/api/memory/knowledge",
        params={"user_id": "u-api", "knowledge_type": "workflow"},
    ).json()
    assert any(k["memory_id"] == memory_id for k in listing)

    detail = client.get(f"/api/memory/knowledge/{memory_id}", params={"user_id": "u-api"})
    assert detail.status_code == 200
    assert detail.json()["name"] == "周报生成流程"


def test_api_05_conflicts_list_and_resolve(client: TestClient) -> None:
    """GET /conflicts + POST /{id}/resolve → 200;缺失冲突 → 404"""
    listing = client.get("/api/memory/conflicts", params={"user_id": "u-api"})
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)

    missing = client.post(
        "/api/memory/conflicts/conf_missing/resolve",
        json={"user_id": "u-api", "decision": "override"},
    )
    assert missing.status_code == 404


def test_api_06_feedback_confirm_update_reject(client: TestClient) -> None:
    """POST /feedback → 200,支持 confirm/update/reject 三种动作"""
    resp = client.post(
        "/api/memory/memories/knowledge",
        json={
            "user_id": "u-api",
            "name": "归档流程",
            "content": "初版内容",
            "knowledge_type": "workflow",
        },
    )
    memory_id = resp.json()["memory_id"]

    confirm = client.post(
        "/api/memory/feedback",
        json={"user_id": "u-api", "memory_id": memory_id, "action": "confirm"},
    )
    assert confirm.status_code == 200
    assert confirm.json()["action"] == "confirm"

    update = client.post(
        "/api/memory/feedback",
        json={
            "user_id": "u-api",
            "memory_id": memory_id,
            "action": "update",
            "feedback_text": "修订后的内容",
        },
    )
    assert update.status_code == 200
    detail = client.get(
        f"/api/memory/knowledge/{memory_id}", params={"user_id": "u-api"}
    ).json()
    assert detail["content"] == "修订后的内容"

    reject = client.post(
        "/api/memory/feedback",
        json={"user_id": "u-api", "memory_id": memory_id, "action": "reject"},
    )
    assert reject.status_code == 200
    # archived 后不再出现在 active 列表与检索结果
    active = client.get("/api/memory/knowledge", params={"user_id": "u-api"}).json()
    assert all(k["memory_id"] != memory_id for k in active)
    search = client.post(
        "/api/memory/search",
        json={"user_id": "u-api", "query": "归档流程", "top_k": 5},
    ).json()
    assert memory_id not in {m["memory_id"] for m in search["knowledge"]}


def test_api_07_manual_memory_write(client: TestClient) -> None:
    """POST /memories/preference 与 /memories/knowledge → 200"""
    pref = client.post(
        "/api/memory/memories/preference",
        json={"user_id": "u-api", "text": "手写偏好条目", "confidence": 0.8},
    )
    assert pref.status_code == 200, pref.text
    assert pref.json()["memory_id"]

    know = client.post(
        "/api/memory/memories/knowledge",
        json={"user_id": "u-api", "name": "手写知识", "content": "内容"},
    )
    assert know.status_code == 200, know.text
    assert know.json()["memory_id"]


def test_api_08_forget_and_history(client: TestClient) -> None:
    """POST /forget + GET /forget/history → 200;遗忘后详情 404"""
    pref = client.post(
        "/api/memory/memories/preference",
        json={"user_id": "u-api", "text": "将被遗忘的偏好", "confidence": 0.9},
    ).json()
    memory_id = pref["memory_id"]

    resp = client.post(
        "/api/memory/forget",
        json={"user_id": "u-api", "target_memory_ids": [memory_id], "cascade": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_count"] == 1

    # 遗忘后不再出现在 active 列表
    active = client.get("/api/memory/preferences", params={"user_id": "u-api"}).json()
    assert all(p["memory_id"] != memory_id for p in active)

    history = client.get("/api/memory/forget/history", params={"user_id": "u-api"})
    assert history.status_code == 200
    assert any(r["record_id"] == resp.json()["record_id"] for r in history.json())


def test_api_09_facts_crud(client: TestClient) -> None:
    """GET /facts、/facts/conflicts、/facts/{id}、/facts/{id}/evidence、DELETE /facts/{id}"""
    pipeline = client.app.state.fact_pipeline
    proposal = pipeline.propose("项目周报的负责人是李四", metadata={"user_id": "u-api"})[0]
    pipeline.commit(proposal, scope="global", user_id="u-api")
    fact = pipeline.get_facts(user_id="u-api")[0]

    facts = client.get("/api/memory/facts", params={"user_id": "u-api"})
    assert facts.status_code == 200
    assert any(f["fact_id"] == fact.fact_id for f in facts.json())

    conflicts = client.get("/api/memory/facts/conflicts", params={"user_id": "u-api"})
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)

    detail = client.get(f"/api/memory/facts/{fact.fact_id}", params={"user_id": "u-api"})
    assert detail.status_code == 200
    assert detail.json()["fact_id"] == fact.fact_id

    evidence = client.get(f"/api/memory/facts/{fact.fact_id}/evidence", params={"user_id": "u-api"})
    assert evidence.status_code == 200

    deleted = client.delete(f"/api/memory/facts/{fact.fact_id}", params={"user_id": "u-api"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    # 软删除：active 列表不再包含,详情状态为 deleted
    active_facts = client.get("/api/memory/facts", params={"user_id": "u-api"}).json()
    assert all(f["fact_id"] != fact.fact_id for f in active_facts)
    soft = client.get(f"/api/memory/facts/{fact.fact_id}", params={"user_id": "u-api"})
    assert soft.status_code == 200
    assert soft.json()["status"] == "deleted"


def test_api_10_extraction_tasks_endpoints(client: TestClient) -> None:
    """GET /extraction/tasks[/metrics]、POST /run、POST /{task_id}/retry"""
    tasks = client.get("/api/memory/extraction/tasks", params={"user_id": "u-api"})
    assert tasks.status_code == 200
    assert isinstance(tasks.json(), list)

    metrics = client.get("/api/memory/extraction/tasks/metrics")
    assert metrics.status_code == 200
    body = metrics.json()
    assert "total_runs" in body
    assert "total_dead_lettered" in body

    run = client.post("/api/memory/extraction/tasks/run", json={"user_id": "u-api", "limit": 10})
    assert run.status_code == 200, run.text
    assert run.json()["claimed"] == 0

    retry_missing = client.post(
        "/api/memory/extraction/tasks/task_missing/retry", params={"user_id": "u-api"}
    )
    assert retry_missing.status_code == 404


def test_api_11_evaluate_endpoints(client: TestClient) -> None:
    """POST /evaluate/{task_name}、GET /evaluate/reports"""
    # preference/conflict 评测框架已定义、实现未落地 → 501 稳定错误码
    resp = client.post("/api/memory/evaluate/preference")
    assert resp.status_code == 501, resp.text
    assert resp.json()["detail"]["code"] == "evaluation.not_implemented"

    # retrieval 评测需要服务器端数据集路径，缺省 → 400
    resp = client.post("/api/memory/evaluate/retrieval")
    assert resp.status_code == 400, resp.text

    reports = client.get("/api/memory/evaluate/reports")
    assert reports.status_code == 200
    assert reports.json() == []


def test_api_12_validation_error_422(client: TestClient) -> None:
    """参数校验失败 → 422 稳定错误码"""
    bad_event = _event_payload("坏事件", "evt-bad")
    bad_event["quality"] = {"score": 2.0, "status": "accepted"}
    resp = client.post("/api/memory/events", json={"events": [bad_event]})
    assert resp.status_code == 422

    bad_search = client.post("/api/memory/search", json={"user_id": "u-api", "top_k": "abc"})
    assert bad_search.status_code == 422

    bad_feedback = client.post(
        "/api/memory/feedback",
        json={"user_id": "u-api", "memory_id": "x", "action": "explode"},
    )
    assert bad_feedback.status_code == 422


def test_api_13_not_found_404(client: TestClient) -> None:
    """不存在的资源 → 404 稳定错误码"""
    missing_pref = client.get(
        "/api/memory/preferences/pref_missing", params={"user_id": "u-api"}
    )
    assert missing_pref.status_code == 404
    missing_know = client.get(
        "/api/memory/knowledge/know_missing", params={"user_id": "u-api"}
    )
    assert missing_know.status_code == 404
    missing_fact = client.get("/api/memory/facts/fact_missing", params={"user_id": "u-api"})
    assert missing_fact.status_code == 404

    reject = client.post(
        "/api/memory/feedback",
        json={"user_id": "u-api", "memory_id": "no_such", "action": "confirm"},
    )
    assert reject.status_code == 404
