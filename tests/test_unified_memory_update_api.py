from __future__ import annotations

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryDecision,
    PreferenceMemory,
    SourceType,
)
from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig


def _client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    return TestClient(create_app(config))


def test_put_updates_preference_metadata_version_and_evidence(tmp_path) -> None:
    with _client(tmp_path) as client:
        memory = PreferenceMemory(user_id="u1", text="Use markdown")
        client.app.state.memory_write_service.upsert_memory(memory)

        response = client.put(
            f"/api/memory/preference/{memory.memory_id}",
            json={
                "user_id": "u1",
                "text": "Use concise markdown",
                "tags": ["markdown", "concise"],
                "is_global": True,
                "confidence": 0.88,
                "transition_action": "revise",
                "evidences": [
                    {
                        "event_id": "evt_manual_pref",
                        "content": "User explicitly revised the report style",
                        "source_type": "manual_config",
                        "weight": 1.0,
                    }
                ],
            },
        )

        assert response.status_code == 200, response.text
        updated = response.json()["memory"]
        assert updated["text"] == "Use concise markdown"
        assert updated["tags"] == ["markdown", "concise"]
        assert updated["is_global"] is True
        assert updated["confidence"] == 0.88
        assert updated["version"] == 2
        lineage = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/lineage",
            params={"user_id": "u1"},
        ).json()["items"]
        assert lineage[-1]["transition_action"] == "revise"
        evidence = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/evidence",
            params={"user_id": "u1"},
        ).json()["items"]
        assert len(evidence) >= 2


def test_put_updates_knowledge_template_and_steps(tmp_path) -> None:
    with _client(tmp_path) as client:
        memory = KnowledgeMemory(
            user_id="u1",
            knowledge_type="template",
            name="Weekly report",
            content="Initial template",
            steps=["collect"],
            template_body="# Weekly report",
        )
        client.app.state.memory_write_service.upsert_memory(memory)

        response = client.put(
            f"/api/memory/knowledge/{memory.memory_id}",
            json={
                "user_id": "u1",
                "content": "Revised template guidance",
                "steps": ["collect", "summarize", "review"],
                "template_body": "# Weekly report\n\n## Risks",
                "tools": ["search", "writer"],
                "transition_action": "revise",
            },
        )

        assert response.status_code == 200, response.text
        updated = response.json()["memory"]
        assert updated["content"] == "Revised template guidance"
        assert updated["steps"] == ["collect", "summarize", "review"]
        assert updated["template_body"].endswith("## Risks")
        assert updated["tools"] == ["search", "writer"]
        assert updated["version"] == 2


def test_put_updates_fact_knowledge_confidence_and_evidence(tmp_path) -> None:
    with _client(tmp_path) as client:
        user_id = "u1"
        fact = KnowledgeMemory(
            memory_id="fact_unified_update",
            user_id=user_id,
            knowledge_type=KnowledgeType.FACT,
            subject="Project A",
            predicate="owner",
            object_value="Alice",
            object_type="Person",
            single_value=True,
            content="Project A owner is Alice",
            confidence=0.70,
            evidences=[
                Evidence(
                    event_id="evt_fact_initial",
                    evidence_id="evt_fact_initial:1",
                    content="Project A owner is Alice",
                    source_type=SourceType.TOOL_RESULT,
                )
            ],
        )
        client.app.state.memory_write_service.upsert_memory(
            fact, action=MemoryDecision.NEW
        )

        response = client.put(
            f"/api/memory/knowledge/{fact.memory_id}",
            json={
                "user_id": user_id,
                "content": "Project A owner changed to Bob",
                "confidence": 0.91,
                "evidences": [
                    {
                        "event_id": "evt_fact_manual_proof",
                        "content": "The project handover was approved by the sponsor",
                        "source_type": "manual_config",
                        "weight": 0.9,
                    }
                ],
                "transition_action": "supersede",
            },
        )

        assert response.status_code == 200, response.text
        body = response.json()
        updated = body["memory"]
        assert body["action"] == "supersede"
        assert updated["content"] == "Project A owner changed to Bob"
        assert updated["confidence"] == 0.91
        assert updated["version"] == 2
        evidence = client.get(
            f"/api/memory/v2/memories/{fact.memory_id}/evidence",
            params={"user_id": user_id},
        ).json()["items"]
        assert len(evidence) == 2


def test_put_rejects_type_mismatch_and_version_regression(tmp_path) -> None:
    with _client(tmp_path) as client:
        memory = PreferenceMemory(user_id="u1", text="Use markdown")
        client.app.state.memory_write_service.upsert_memory(memory)

        mismatch = client.put(
            f"/api/memory/knowledge/{memory.memory_id}",
            json={"user_id": "u1", "content": "wrong type"},
        )
        regression = client.put(
            f"/api/memory/preference/{memory.memory_id}",
            json={"user_id": "u1", "version": 0},
        )

        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "memory.type_mismatch"
        assert regression.status_code == 422
