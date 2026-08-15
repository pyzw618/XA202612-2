from __future__ import annotations

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import PreferenceMemory
from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository


def _client(tmp_path):
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    return TestClient(create_app(config))


def test_memory_v2_exposes_owned_provenance_and_redacts_evidence(tmp_path):
    with _client(tmp_path) as client:
        memory = PreferenceMemory(
            user_id="u1",
            text="Use concise markdown reports",
            payload={"target": "report_format", "value": "markdown"},
        )
        client.app.state.memory_write_service.upsert_memory(memory)

        lineage = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/lineage",
            params={"user_id": "u1"},
        )
        evidence = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/evidence",
            params={"user_id": "u1"},
        )
        audit = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/audit",
            params={"user_id": "u1"},
        )

        assert lineage.status_code == 200
        assert lineage.json()["items"][0]["transition_action"] == "new"
        assert evidence.status_code == 200
        assert evidence.json()["items"][0]["excerpt"].endswith("sanitized evidence")
        assert "markdown reports" not in evidence.text
        assert audit.status_code == 200
        assert audit.json()["items"]


def test_memory_v2_enforces_user_scope_for_projections_and_replay(tmp_path):
    with _client(tmp_path) as client:
        memory = PreferenceMemory(user_id="u1", text="Only user one can manage this")
        client.app.state.memory_write_service.upsert_memory(memory)
        outbox = MemoryProjectionOutboxRepository(client.app.state.db).list_by_status(
            ("pending",), limit=10
        )[0]
        repo = MemoryProjectionOutboxRepository(client.app.state.db)
        repo.mark_failed(outbox.outbox_id, error_code="projection.vector_failed")

        foreign_lineage = client.get(
            f"/api/memory/v2/memories/{memory.memory_id}/lineage",
            params={"user_id": "u2"},
        )
        foreign_projections = client.get(
            "/api/memory/v2/projections",
            params={"user_id": "u2", "status": "failed"},
        )
        foreign_replay = client.post(
            "/api/memory/v2/projections/replay",
            json={"user_id": "u2", "outbox_ids": [outbox.outbox_id]},
        )
        owner_replay = client.post(
            "/api/memory/v2/projections/replay",
            json={"user_id": "u1", "outbox_ids": [outbox.outbox_id]},
        )

        assert foreign_lineage.status_code == 404
        assert foreign_projections.json()["items"] == []
        assert foreign_replay.json()["requeued"] == 0
        assert owner_replay.json()["requeued"] == 1


def test_memory_v2_search_can_include_safe_provenance_references(tmp_path):
    with _client(tmp_path) as client:
        memory = PreferenceMemory(user_id="u1", text="Use concise report sections")
        client.app.state.memory_write_service.upsert_memory(memory)

        response = client.get(
            "/api/memory/v2/search",
            params={
                "user_id": "u1",
                "query": "concise report",
                "include_provenance": "true",
            },
        )

        assert response.status_code == 200
        assert memory.memory_id in response.json()["provenance"]
        provenance = response.json()["provenance"][memory.memory_id]
        assert provenance["lineage_count"] == 1
        assert provenance["evidence_count"] == 1
