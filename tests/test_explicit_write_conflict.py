# -*- coding: utf-8 -*-
"""显式写入端点（MCP `write_preference` / `write_knowledge`、CLI `remember`）的冲突检测。

这两条端点原先直接落库、不经过 `PreferenceUpdater` / `KnowledgeUpdater`，因此
MCP/CLI 显式写入的记忆永远不会产生冲突记录。这里锁定修复后的契约：

1. 命中冲突 → 记录一条 PENDING 冲突（**只记录，不裁决**）；
2. 响应契约不变（``memory_id`` 回显请求里的 id、状态仍为 active）；
3. 兼容写入不产生伪冲突；
4. 大批量同类写入（评测播种形态）不因检测被合并或丢失。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig

PREFERENCE_URL = "/api/memory/memories/preference"
KNOWLEDGE_URL = "/api/memory/memories/knowledge"
CONFLICTS_URL = "/api/memory/conflicts"


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as test_client:
        yield test_client


def _write_preference(client: TestClient, *, user_id: str, target: str, value: str, text: str) -> dict:
    response = client.post(
        PREFERENCE_URL,
        json={
            "user_id": user_id,
            "preference_type": "output_style",
            "text": text,
            "payload": {"target": target, "value": value},
            "scope": {"scene": "office", "task_type": "weekly_report"},
            "confidence": 0.8,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _write_knowledge(
    client: TestClient, *, user_id: str, memory_id: str, name: str, content: str, steps: list[str] | None = None
) -> dict:
    response = client.post(
        KNOWLEDGE_URL,
        json={
            "memory_id": memory_id,
            "user_id": user_id,
            "knowledge_type": "workflow",
            "name": name,
            "content": content,
            "steps": steps or ["collect", "render"],
            "scope": {"scene": "office", "task_type": "weekly_report"},
            "confidence": 0.9,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _conflicts(client: TestClient, user_id: str) -> list[dict]:
    return client.get(CONFLICTS_URL, params={"user_id": user_id}).json()


def test_conflicting_preference_write_records_pending_conflict(client: TestClient) -> None:
    """同 target、不同 value 的两次显式写入 → 一条 PENDING 冲突，且不裁决。"""
    first = _write_preference(
        client, user_id="u-conflict", target="output.format", value="markdown", text="输出用 markdown"
    )
    second = _write_preference(
        client, user_id="u-conflict", target="output.format", value="plain", text="输出改用纯文本"
    )

    records = _conflicts(client, "u-conflict")
    assert len(records) == 1, records
    record = records[0]
    assert record["decision"] == "pending"
    assert record["resolved_at"] is None
    assert record["memory_type"] == "preference"
    assert record["old_memory_id"] == first["memory_id"]
    assert record["new_memory_id"] == second["memory_id"]
    assert record["old_content"] == "输出用 markdown"
    assert record["new_content"] == "输出改用纯文本"

    # 只记录不裁决：两条记忆都保持 active，没有谁被归档或降级为 pending。
    active = {
        item["memory_id"]
        for item in client.get(
            "/api/memory/preferences", params={"user_id": "u-conflict", "status": "active"}
        ).json()
    }
    assert {first["memory_id"], second["memory_id"]} <= active


def test_compatible_preference_write_records_no_conflict(client: TestClient) -> None:
    """目标不同 / 类型不同的显式写入不得产生伪冲突记录。"""
    # 同类型同 scope，但 target 不同 → 不是同一条偏好，各自独立。
    _write_preference(
        client, user_id="u-compat", target="output.structure", value="conclusion_first", text="先给结论"
    )
    _write_preference(
        client, user_id="u-compat", target="output.tone", value="concise", text="语气简洁"
    )
    assert _conflicts(client, "u-compat") == []

    # preference_type 不同 → 检测器按类型隔离，不比对。
    client.post(
        PREFERENCE_URL,
        json={
            "user_id": "u-compat-type",
            "preference_type": "language_preference",
            "text": "项目材料默认使用中文",
            "scope": {"scene": "office", "task_type": "weekly_report"},
            "confidence": 0.9,
        },
    )
    client.post(
        PREFERENCE_URL,
        json={
            "user_id": "u-compat-type",
            "preference_type": "output_style",
            "text": "输出保持简洁",
            "scope": {"scene": "office", "task_type": "weekly_report"},
            "confidence": 0.9,
        },
    )
    assert _conflicts(client, "u-compat-type") == []


def test_identical_preference_write_records_merge_conflict(client: TestClient) -> None:
    """同 target 同 value 的重复写入是「支持性证据」→ 记录为 merge 冲突。"""
    _write_preference(
        client, user_id="u-identical", target="output.format", value="markdown", text="输出用 markdown"
    )
    _write_preference(
        client, user_id="u-identical", target="output.format", value="markdown", text="输出用 markdown"
    )
    records = _conflicts(client, "u-identical")
    assert len(records) == 1, records
    assert records[0]["decision"] == "pending"
    assert "Identical preference reinforced" in records[0]["reason"]


def test_conflicting_knowledge_write_records_conflict(client: TestClient) -> None:
    """同类同 scope 的高相似知识写入 → 产生冲突记录，且两条都仍然落库。"""
    first = _write_knowledge(
        client, user_id="u-know", memory_id="know_conflict_1", name="周报生成流程", content="先收集数据再渲染成周报"
    )
    second = _write_knowledge(
        client,
        user_id="u-know",
        memory_id="know_conflict_2",
        name="周报生成流程",
        content="先收集数据再渲染成周报，最后人工校对一遍",
    )

    records = _conflicts(client, "u-know")
    assert len(records) == 1, records
    assert records[0]["memory_type"] == "knowledge"
    assert records[0]["old_memory_id"] == first["memory_id"]
    assert records[0]["new_memory_id"] == second["memory_id"]
    assert records[0]["decision"] == "pending"

    # 检测不裁决：两条知识都保持 active（评测播种依赖这一点）。
    active = {
        item["memory_id"]
        for item in client.get(
            "/api/memory/knowledge", params={"user_id": "u-know", "status": "active"}
        ).json()
    }
    assert {"know_conflict_1", "know_conflict_2"} <= active


def test_conflict_id_is_deterministic_and_upserts(client: TestClient) -> None:
    """同一 (user, old, new) 三元组摘要相同，重复保存只保留一行。"""
    from memoryhub.adapter.api import _explicit_conflict

    state = client.app.state
    fields = {
        "prefix": "conf_pref",
        "memory_type": "preference",
        "user_id": "u-idem",
        "old_memory_id": "pref_old",
        "new_memory_id": "pref_new",
        "old_content": "用 JSON",
        "new_content": "用 Markdown",
        "conflict_field": "text/payload",
        "reason": "explicit write",
    }
    first = _explicit_conflict(**fields)
    second = _explicit_conflict(**fields)
    assert first.conflict_id == second.conflict_id

    state.conflict_repo.save(first)
    state.conflict_repo.save(second)
    assert len(_conflicts(client, "u-idem")) == 1


def test_detection_failure_does_not_break_the_write(client: TestClient, monkeypatch) -> None:
    """检测抛异常时写入仍须成功：显式写入的成败只由安全门禁和落库决定。"""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(
        client.app.state.event_processor.preference_updater, "_find_existing", _boom
    )
    result = _write_preference(
        client, user_id="u-boom", target="format", value="json", text="用 JSON"
    )
    assert result["status"] == "ok"
    detail = client.get(
        f"/api/memory/preferences/{result['memory_id']}", params={"user_id": "u-boom"}
    )
    assert detail.status_code == 200


def test_bulk_knowledge_writes_keep_every_memory_active(client: TestClient) -> None:
    """评测播种形态：同一用户连续写入多条同类知识，全部落库且不被合并。"""
    total = 40
    for index in range(total):
        _write_knowledge(
            client,
            user_id="u-seed",
            memory_id=f"know_seed_{index}",
            name=f"流程 {index}",
            content=f"步骤说明 {index}：收集数据然后渲染输出成文档",
        )

    active = {
        item["memory_id"]
        for item in client.get(
            "/api/memory/knowledge", params={"user_id": "u-seed", "status": "active"}
        ).json()
    }
    assert {f"know_seed_{index}" for index in range(total)} <= active
