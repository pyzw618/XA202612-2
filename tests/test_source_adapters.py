# -*- coding: utf-8 -*-
"""I-7 多源适配层测试：工具/行为/配置源适配器 + /sources API 端点。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig
from memoryhub.core.ingestion.adapters import BehaviorAdapter, ConfigAdapter, ToolResultAdapter


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "sources.db"),
            vector_index_path=str(tmp_path / "v"),
            evidence_path=str(tmp_path / "e"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as c:
        yield c


def test_tool_result_adapter_produces_tool_result_event():
    event = ToolResultAdapter().to_event(
        "shell_exec", {"output": "ls 结果", "status": "success", "user_id": "u"}
    )
    assert event.source_type.value == "tool_result"
    assert event.tool_calls and event.tool_calls[0].tool_name == "shell_exec"
    assert event.tool_calls[0].status.value == "success"


def test_tool_result_adapter_rejects_non_dict():
    with pytest.raises(ValueError):
        ToolResultAdapter().to_event("shell", "not a dict")  # type: ignore


def test_behavior_adapter_builds_behavior_event():
    event = BehaviorAdapter().to_event(
        {"text": "选择 Markdown", "session_id": "s1", "scene": "office"},
        behavior_type="selection",
        user_id="u",
    )
    assert event.source_type.value == "user_behavior"
    assert event.event_type == "selection"
    assert event.payload["behavior_type"] == "selection"


def test_behavior_adapter_rejects_invalid_type():
    with pytest.raises(ValueError):
        BehaviorAdapter().to_event({"text": "x"}, behavior_type="bogus")


def test_config_adapter_version_chain():
    adapter = ConfigAdapter()
    c1 = adapter.to_manual_config(
        user_id="u", config_type="output_style", payload={"format": "markdown"}
    )
    c2 = adapter.to_manual_config(
        user_id="u", config_type="output_style", payload={"format": "html"}, previous=c1
    )
    assert c1.version == 1
    assert c2.version == 2
    assert c2.config_id == c1.config_id
    assert c2.parent_id == c1.config_id
    assert c2.root_id == c1.config_id
    event = adapter.to_event(c2, previous=c1)
    assert event.source_type.value == "manual_config"
    assert event.payload["version"] == 2
    assert event.payload["previous_version"] == 1


def test_config_adapter_roundtrip_from_event():
    adapter = ConfigAdapter()
    c1 = adapter.to_manual_config(
        user_id="u", config_type="safety_policy", payload={"allow_external": False}
    )
    event = adapter.to_event(c1)
    restored = ConfigAdapter.from_event(event)
    assert restored is not None
    assert restored.config_id == c1.config_id
    assert restored.payload == c1.payload


def test_sources_behavior_endpoint(client: TestClient):
    resp = client.post(
        "/api/memory/sources/behavior",
        json={
            "user_id": "u-beh",
            "behavior_type": "selection",
            "behavior": {"text": "以后选择 JSON 输出", "session_id": "sx"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] == 1
    assert body["event_id"]


def test_sources_config_endpoint_returns_versioned_config(client: TestClient):
    resp = client.post(
        "/api/memory/sources/config",
        json={
            "user_id": "u-cfg",
            "config_type": "output_style",
            "payload": {"format": "markdown"},
            "scope": {"scene": "office", "task_type": "office.weekly_report"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] == 1
    mc = body["manual_config"]
    assert mc["version"] == 1
    assert mc["config_id"]
    assert mc["source"] == "manual_config"
