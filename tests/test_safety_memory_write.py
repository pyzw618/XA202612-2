from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryhub.adapter.api import router
from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SafetyAction,
    SensitiveLevel,
    SensitiveRule,
)
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.detector import SensitiveDetector
from memoryhub.core.safety.gate import SafetyWriteGate
from memoryhub.core.safety.memory_write import guard_memory_write
from memoryhub.core.safety.quarantine import ReviewQuarantineStore

_PHONE = "13800138000"
_ID_CARD = "11010519491231002X"
_EMAIL = "132987645@qq.com"


def _gate(tmp_path, detector: SensitiveDetector | None = None) -> SafetyWriteGate:
    return SafetyWriteGate(
        detector or SensitiveDetector(),
        SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32),
        quarantine=ReviewQuarantineStore(
            tmp_path / "review",
            encryption_key=b"q" * 32,
        ),
    )


def _rule(token: str, action: SafetyAction) -> SensitiveRule:
    return SensitiveRule(
        name=f"test.memory_write.{action.value}",
        pattern=re.escape(token),
        level=SensitiveLevel.HIGH,
        action=action,
        replacement="[REDACTED_TEST]",
        reason_code=f"test.memory_write.{action.value}",
        reason="Synthetic explicit-memory write policy.",
        standard_source="test-suite",
    )


class _SyncSpy:
    def __init__(self):
        self.memories = []

    def index_memory(self, memory):
        self.memories.append(memory)
        return True, memory.memory_id


class _FailingSync:
    def index_memory(self, _memory):
        raise RuntimeError("untrusted downstream detail 13800138000")


def _api(gate=None, sync_service=None, *, pref_repo=None, know_repo=None, writer=None):
    app = FastAPI()
    app.include_router(router)
    app.state.safety_gate = gate
    app.state.sync_service = sync_service
    app.state.pref_repo = pref_repo
    app.state.know_repo = know_repo
    app.state.memory_write_service = writer
    return TestClient(app)


def test_guard_memory_write_masks_builtin_personal_information_before_sink(tmp_path):
    original = KnowledgeMemory(
        user_id="opencode",
        name="光头强的个人信息",
        content=(
            f"手机号 {_PHONE}，身份证号 {_ID_CARD}，电子邮箱 {_EMAIL}，"
            "家庭住址狗熊岭"
        ),
        confidence=0.95,
    )
    received = []

    result = guard_memory_write(_gate(tmp_path), original, received.append)

    assert result.action is SafetyAction.MASK
    assert result.memory is received[0]
    assert result.memory.status.value == "active"
    serialized = json.dumps(result.memory.model_dump(mode="json"), ensure_ascii=False)
    assert _PHONE not in serialized
    assert _ID_CARD not in serialized
    assert _EMAIL not in serialized
    assert "[REDACTED_PHONE]" in serialized
    assert "[REDACTED_ID_CARD]" in serialized
    assert "[REDACTED_EMAIL]" in serialized
    assert _PHONE in original.content
    assert _ID_CARD in original.content
    assert _EMAIL in original.content


def test_guard_memory_write_scans_every_knowledge_content_field(tmp_path):
    token = "field-secret-4242"
    memory = KnowledgeMemory(
        user_id="u1",
        name=f"name {token}",
        content=f"content {token}",
        steps=[f"step {token}"],
        tools=[f"tool {token}"],
        template_body=f"template {token}",
        scope={"scene": f"scene {token}", "task_type": "task", "app": "app"},
    )
    received = []
    detector = SensitiveDetector(rules=[_rule(token, SafetyAction.MASK)])

    result = guard_memory_write(_gate(tmp_path, detector), memory, received.append)

    assert result.action is SafetyAction.MASK
    serialized = json.dumps(received[0].model_dump(mode="json"), ensure_ascii=False)
    assert token not in serialized
    assert serialized.count("[REDACTED_TEST]") == 6


@pytest.mark.parametrize("action", [SafetyAction.REVIEW, SafetyAction.REJECT])
def test_guard_memory_write_never_calls_sink_for_blocking_actions(tmp_path, action):
    token = f"block-{action.value}"
    memory = PreferenceMemory(user_id="u1", text=token)
    received = []

    result = guard_memory_write(
        _gate(tmp_path, SensitiveDetector(rules=[_rule(token, action)])),
        memory,
        received.append,
    )

    assert result.action is action
    assert result.memory is None
    assert result.sink_result is None
    assert received == []


def test_explicit_knowledge_api_persists_only_masked_memory(tmp_path):
    sync = _SyncSpy()
    payload = KnowledgeMemory(
        user_id="opencode",
        name="个人信息",
        content=f"手机号 {_PHONE}，身份证号 {_ID_CARD}，邮箱 {_EMAIL}",
        confidence=0.95,
    ).model_dump(mode="json")

    with _api(_gate(tmp_path), sync) as client:
        response = client.post("/api/memory/memories/knowledge", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["safety_action"] == "mask"
    assert response.json()["audit_id"]
    assert len(sync.memories) == 1
    persisted = json.dumps(sync.memories[0].model_dump(mode="json"), ensure_ascii=False)
    assert _PHONE not in persisted
    assert _ID_CARD not in persisted
    assert _EMAIL not in persisted


@pytest.mark.parametrize(
    ("action", "status_code"),
    [(SafetyAction.REVIEW, 409), (SafetyAction.REJECT, 403)],
)
def test_explicit_memory_api_blocks_review_and_reject_without_writes(
    tmp_path, action, status_code
):
    token = f"api-{action.value}"
    sync = _SyncSpy()
    gate = _gate(tmp_path, SensitiveDetector(rules=[_rule(token, action)]))
    payload = PreferenceMemory(user_id="u1", text=token).model_dump(mode="json")

    with _api(gate, sync) as client:
        response = client.post("/api/memory/memories/preference", json=payload)

    assert response.status_code == status_code
    assert sync.memories == []


def test_explicit_memory_api_fails_closed_without_gate():
    sync = _SyncSpy()
    payload = PreferenceMemory(user_id="u1", text="clean").model_dump(mode="json")

    with _api(None, sync) as client:
        response = client.post("/api/memory/memories/preference", json=payload)

    assert response.status_code == 503
    assert sync.memories == []


def test_explicit_memory_api_hides_downstream_failure_details(tmp_path):
    payload = PreferenceMemory(user_id="u1", text="clean").model_dump(mode="json")

    with _api(_gate(tmp_path), _FailingSync()) as client:
        response = client.post("/api/memory/memories/preference", json=payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "memory safety gate failed"}
    assert _PHONE not in response.text


class _PreferenceRepo:
    def __init__(self, memory):
        self.memory = memory

    def get_by_id(self, memory_id):
        if memory_id != self.memory.memory_id:
            return None
        return self.memory.model_copy(deep=True)


class _WriterSpy:
    def __init__(self):
        self.memories = []

    def upsert_memory(self, memory):
        self.memories.append(memory)


def test_feedback_update_is_masked_before_reindexing(tmp_path):
    memory = PreferenceMemory(memory_id="pref_feedback", user_id="u1", text="clean")
    writer = _WriterSpy()
    client = _api(
        _gate(tmp_path),
        _SyncSpy(),
        pref_repo=_PreferenceRepo(memory),
        know_repo=None,
        writer=writer,
    )

    with client:
        response = client.post(
            "/api/memory/feedback",
            json={
                "user_id": "u1",
                "memory_id": memory.memory_id,
                "action": "update",
                "feedback_text": f"联系电话 {_PHONE}，邮箱 {_EMAIL}",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["safety_action"] == "mask"
    assert len(writer.memories) == 1
    assert _PHONE not in writer.memories[0].text
    assert _EMAIL not in writer.memories[0].text
