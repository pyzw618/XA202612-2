# -*- coding: utf-8 -*-
"""第 7 章 REST API 契约专项验收测试。

对应 old/docs/0811功能性测试/TEST_PLAN.md 7 REST API 契约测试（API）：
覆盖全部端点：正向(200)、参数校验(422)、不存在(404)、稳定错误码。
user-rules CRUD 由 SEC-15~17 / test_user_rule_api.py 覆盖，此处不重复。
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import (
    ConflictDecision,
    ConflictRecord,
    MemoryStatus,
    PreferenceMemory,
)
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
    """GET /conflicts + POST /{id}/resolve → 200;缺失冲突 → 404;非法裁决值 → 400"""
    listing = client.get("/api/memory/conflicts", params={"user_id": "u-api"})
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)

    missing = client.post(
        "/api/memory/conflicts/conf_missing/resolve",
        json={"user_id": "u-api", "decision": "override"},
    )
    assert missing.status_code == 404

    invalid = client.post(
        "/api/memory/conflicts/conf_missing/resolve",
        json={"user_id": "u-api", "decision": "definitely_not_a_decision"},
    )
    assert invalid.status_code == 400


def test_api_05b_conflict_resolve_persists_valid_decision(client: TestClient) -> None:
    """合法裁决值落库：override/merge/coexist/pending 之外一律 400。"""
    repo = client.app.state.conflict_repo
    assert repo is not None
    repo.save(
        ConflictRecord(
            conflict_id="conf_api_decision",
            user_id="u-api",
            old_memory_id="pref_old",
            new_memory_id="pref_new",
            memory_type="preference",
            old_content="Use JSON",
            new_content="Use Markdown",
            decision=ConflictDecision.PENDING,
        )
    )

    resolved = client.post(
        "/api/memory/conflicts/conf_api_decision/resolve",
        json={"user_id": "u-api", "decision": "merge", "reason": "merged manually"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["decision"] == "merge"

    stored = client.get(
        "/api/memory/conflicts", params={"user_id": "u-api", "status": "merge"}
    ).json()
    assert len(stored) == 1
    assert stored[0]["result_memory_id"] == ""
    assert stored[0]["resolved_at"] is not None


def _seed_conflict(client: TestClient, *, conflict_id: str, old, new, memory_type: str = "preference"):
    """写入冲突双方并登记一条 PENDING 冲突记录，返回 app.state。"""
    state = client.app.state
    state.memory_write_service.upsert_memory(old)
    state.memory_write_service.upsert_memory(new)
    state.conflict_repo.save(
        ConflictRecord(
            conflict_id=conflict_id,
            user_id=old.user_id,
            old_memory_id=old.memory_id,
            new_memory_id=new.memory_id,
            memory_type=memory_type,
            old_content=old.text,
            new_content=new.text,
            decision=ConflictDecision.PENDING,
        )
    )
    return state


def _pref_pair(prefix: str):
    old = PreferenceMemory(
        memory_id=f"{prefix}_old",
        user_id="u-api",
        text="Use JSON",
        payload={"target": "format", "value": "json"},
    )
    new = PreferenceMemory(
        memory_id=f"{prefix}_new",
        user_id="u-api",
        text="Use Markdown",
        payload={"target": "format", "value": "markdown"},
        status=MemoryStatus.PENDING,
    )
    return old, new


def test_api_05c_conflict_filter_by_resolved_and_memory_type(client: TestClient) -> None:
    """status=resolved 等价于 decision != pending；memory_type 走服务端过滤。"""
    old, new = _pref_pair("pref_filter")
    state = _seed_conflict(
        client, conflict_id="conf_filter_pending", old=old, new=new
    )
    state.conflict_repo.save(
        ConflictRecord(
            conflict_id="conf_filter_done",
            user_id="u-api",
            old_memory_id="pref_done_old",
            new_memory_id="pref_done_new",
            memory_type="knowledge",
            decision=ConflictDecision.MERGE,
        )
    )

    resolved = client.get(
        "/api/memory/conflicts", params={"user_id": "u-api", "status": "resolved"}
    ).json()
    assert [item["conflict_id"] for item in resolved] == ["conf_filter_done"]

    only_knowledge = client.get(
        "/api/memory/conflicts",
        params={"user_id": "u-api", "status": "", "memory_type": "knowledge"},
    ).json()
    assert [item["conflict_id"] for item in only_knowledge] == ["conf_filter_done"]

    paged = client.get(
        "/api/memory/conflicts",
        params={"user_id": "u-api", "status": "resolved", "page": 1, "size": 1},
    ).json()
    assert paged["total"] == 1
    assert len(paged["items"]) == 1


def test_api_05d_conflict_apply_override_versions_old(client: TestClient) -> None:
    """apply=true 的 override：归档旧记忆并生成带版本链的后继。"""
    old, new = _pref_pair("pref_apply_ovr")
    state = _seed_conflict(client, conflict_id="conf_apply_override", old=old, new=new)

    resp = client.post(
        "/api/memory/conflicts/conf_apply_override/resolve",
        json={"user_id": "u-api", "decision": "override", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] is True
    assert state.pref_repo.get_by_id(old.memory_id).status.value == "archived"
    successor = state.pref_repo.get_by_id(body["result_id"])
    assert successor.status.value == "active"
    assert successor.parent_id == old.memory_id
    assert successor.version == old.version + 1


def test_api_05e_conflict_apply_merge_archives_old(client: TestClient) -> None:
    """apply=true 的 merge：旧记忆归档，合并结果为新版本。"""
    old, new = _pref_pair("pref_apply_mrg")
    state = _seed_conflict(client, conflict_id="conf_apply_merge", old=old, new=new)

    resp = client.post(
        "/api/memory/conflicts/conf_apply_merge/resolve",
        json={"user_id": "u-api", "decision": "merge", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    assert state.pref_repo.get_by_id(old.memory_id).status.value == "archived"
    merged = state.pref_repo.get_by_id(resp.json()["result_id"])
    assert merged.status.value == "active"
    assert merged.parent_id == old.memory_id


def test_api_05f_conflict_apply_coexist_activates_both(client: TestClient) -> None:
    """apply=true 的 coexist：两条都保持可用（待确认的新记忆被激活）。"""
    old, new = _pref_pair("pref_apply_co")
    state = _seed_conflict(client, conflict_id="conf_apply_coexist", old=old, new=new)

    resp = client.post(
        "/api/memory/conflicts/conf_apply_coexist/resolve",
        json={"user_id": "u-api", "decision": "coexist", "apply": True},
    )
    assert resp.status_code == 200, resp.text
    assert state.pref_repo.get_by_id(old.memory_id).status.value == "active"
    assert state.pref_repo.get_by_id(new.memory_id).status.value == "active"


def test_api_05g_conflict_apply_rejects_pending_and_missing_memory(client: TestClient) -> None:
    """pending 无法落地；冲突任一方记忆缺失时返回 409。"""
    old, new = _pref_pair("pref_apply_guard")
    state = _seed_conflict(client, conflict_id="conf_apply_guard", old=old, new=new)

    pending = client.post(
        "/api/memory/conflicts/conf_apply_guard/resolve",
        json={"user_id": "u-api", "decision": "pending", "apply": True},
    )
    assert pending.status_code == 400
    assert pending.json()["detail"]["code"] == "conflict.cannot_apply_pending"

    state.conflict_repo.save(
        ConflictRecord(
            conflict_id="conf_apply_orphan",
            user_id="u-api",
            old_memory_id="pref_gone",
            new_memory_id="pref_also_gone",
            memory_type="preference",
            decision=ConflictDecision.PENDING,
        )
    )
    orphan = client.post(
        "/api/memory/conflicts/conf_apply_orphan/resolve",
        json={"user_id": "u-api", "decision": "override", "apply": True},
    )
    assert orphan.status_code == 409
    assert orphan.json()["detail"]["code"] == "conflict.memory_missing"


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
    # §4.9.2 反馈闭环：confirm 触发复习强化（访问计数/成功计数）并刷新健康度
    confirmed = client.get(
        f"/api/memory/knowledge/{memory_id}", params={"user_id": "u-api"}
    ).json()
    assert confirmed["access_count_30d"] == 1
    assert confirmed["total_count"] == 1
    assert confirmed["success_count"] == 1
    assert 0.0 < confirmed["health_score"] <= 1.0

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


def test_api_08b_forget_history_record_detail(client: TestClient) -> None:
    """GET /forget/history/{record_id} → 200 单条详情；记录不存在 → 404"""
    pref = client.post(
        "/api/memory/memories/preference",
        json={"user_id": "u-api", "text": "将被遗忘的偏好（详情）", "confidence": 0.9},
    ).json()
    memory_id = pref["memory_id"]

    resp = client.post(
        "/api/memory/forget",
        json={"user_id": "u-api", "target_memory_ids": [memory_id], "cascade": True},
    )
    assert resp.status_code == 200, resp.text
    record_id = resp.json()["record_id"]

    detail = client.get(f"/api/memory/forget/history/{record_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["record_id"] == record_id
    assert body["user_id"] == "u-api"
    assert body["deleted_count"] == 1
    assert memory_id in body["target_memory_ids"]

    missing = client.get("/api/memory/forget/history/forg_doesnotexist")
    assert missing.status_code == 404


def test_api_fact_knowledge_write_and_search(client: TestClient) -> None:
    """FACT 并入知识：knowledge_type=fact 经 API 写入并可被混合检索命中。"""
    resp = client.post(
        "/api/memory/memories/knowledge",
        json={
            "user_id": "u-api",
            "knowledge_type": "fact",
            "subject": "项目A",
            "predicate": "负责人",
            "object_value": "张三",
            "object_type": "Person",
            "single_value": True,
            "content": "项目A 负责人 张三",
        },
    )
    assert resp.status_code == 200, resp.text
    memory_id = resp.json()["memory_id"]

    detail = client.get(
        f"/api/memory/knowledge/{memory_id}", params={"user_id": "u-api"}
    ).json()
    assert detail["knowledge_type"] == "fact"
    assert detail["subject"] == "项目A"
    assert detail["predicate"] == "负责人"

    search = client.post(
        "/api/memory/search",
        json={"user_id": "u-api", "query": "项目A负责人张三", "top_k": 5},
    )
    assert search.status_code == 200, search.text
    hit_ids = [r["memory_id"] for r in search.json().get("results", [])]
    assert memory_id in hit_ids or detail["content"] in str(search.json())


def test_api_facts_forward_to_knowledge_fact(client: TestClient) -> None:
    """/facts 兼容转发：knowledge(FACT) 经 GET /facts 与 GET /facts/{id} 可查。"""
    resp = client.post(
        "/api/memory/memories/knowledge",
        json={
            "user_id": "u-api",
            "knowledge_type": "fact",
            "subject": "项目B",
            "predicate": "负责人",
            "object_value": "李四",
            "object_type": "Person",
            "content": "项目B 负责人 李四",
        },
    )
    assert resp.status_code == 200, resp.text
    memory_id = resp.json()["memory_id"]

    listed = client.get("/api/memory/facts", params={"user_id": "u-api"}).json()
    assert any(item["fact_id"] == memory_id and item["subject"] == "项目B" for item in listed)

    detail = client.get(f"/api/memory/facts/{memory_id}", params={"user_id": "u-api"}).json()
    assert detail["object_value"] == "李四"
    assert detail["status"] == "active"


def test_api_memory_tiers_short_and_mid_term(client: TestClient) -> None:
    """记忆分层：事件→短期缓冲；consolidate 聚合为中期情景。"""
    source_hash = hashlib.sha256(b"tier-event-1").hexdigest()
    write = client.post(
        "/api/memory/events",
        json={
            "events": [
                {
                    "event_id": "tier-e1",
                    "user_id": "u-api",
                    "session_id": "tier-s1",
                    "turn_id": "tier-t1",
                    "task_type": "tier-task",
                    "scene": "office",
                    "source_type": "user_behavior",
                    "event_type": "user_message",
                    "text": "分层测试事件内容",
                    "occurred_at": "2026-08-18T00:00:00Z",
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
            ]
        },
    )
    assert write.status_code == 200, write.text

    short = client.get(
        "/api/memory/short-term",
        params={"user_id": "u-api", "session_id": "tier-s1"},
    )
    assert short.status_code == 200
    assert any(r["event_id"] == "tier-e1" for r in short.json())

    cons = client.post("/api/memory/lifecycle/consolidate", params={"user_id": "u-api"})
    assert cons.status_code == 200, cons.text

    mid = client.get("/api/memory/mid-term", params={"user_id": "u-api"})
    assert mid.status_code == 200
    assert any(ep["session_ids"] == ["tier-s1"] for ep in mid.json())


def test_api_09_facts_crud(client: TestClient) -> None:
    """GET /facts、/facts/conflicts、/facts/{id}、/facts/{id}/evidence、DELETE /facts/{id}"""
    created = client.post(
        "/api/memory/memories/knowledge",
        json={
            "user_id": "u-api",
            "knowledge_type": "fact",
            "subject": "项目周报",
            "predicate": "负责人",
            "object_value": "李四",
            "object_type": "Person",
            "content": "项目周报 负责人 李四",
        },
    )
    assert created.status_code == 200, created.text
    fact_id = created.json()["memory_id"]

    facts = client.get("/api/memory/facts", params={"user_id": "u-api"})
    assert facts.status_code == 200
    assert any(f["fact_id"] == fact_id for f in facts.json())

    conflicts = client.get("/api/memory/facts/conflicts", params={"user_id": "u-api"})
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)

    detail = client.get(f"/api/memory/facts/{fact_id}", params={"user_id": "u-api"})
    assert detail.status_code == 200
    assert detail.json()["fact_id"] == fact_id

    evidence = client.get(f"/api/memory/facts/{fact_id}/evidence", params={"user_id": "u-api"})
    assert evidence.status_code == 200

    deleted = client.delete(f"/api/memory/facts/{fact_id}", params={"user_id": "u-api"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


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
    # preference/conflict 评测需服务器端数据集路径，缺省 → 400（已实现，I-10）
    resp = client.post("/api/memory/evaluate/preference")
    assert resp.status_code == 400, resp.text
    resp = client.post("/api/memory/evaluate/conflict")
    assert resp.status_code == 400, resp.text

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
