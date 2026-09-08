from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import load_config
from memoryhub.core.fact.models import Entity
from memoryhub.storage.database import FactSemanticRepository


@pytest.fixture()
def client(tmp_path: Path):
    config = load_config()
    config.storage.db_path = str(tmp_path / "memoryhub.db")
    config.storage.vector_index_path = str(tmp_path / "vector")
    config.storage.evidence_path = str(tmp_path / "evidence")
    app = create_app(config)
    with TestClient(app) as test_client:
        yield test_client


def _propose(client: TestClient, object_value: str):
    response = client.post(
        "/api/memory/facts/propose",
        json={
            "user_id": "u1",
            "triples": [{
                "subject": "项目A",
                "predicate": "负责人",
                "object": object_value,
                "object_type": "Person",
                "subject_type": "Other",
                "single_value": True,
            }],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_single_value_conflict_is_durable_and_replace_is_atomic(client: TestClient):
    first = _propose(client, "张三")
    first_id = first["created"][0]["memory_id"]
    assert first["created"][0]["outcome"] == "new"

    pending = _propose(client, "李四")
    assert pending["created"] == []
    proposal = pending["pending"][0]
    assert proposal["status"] == "pending"
    assert proposal["decision_task"]["conflict_type"] == "subject_cardinality"

    proposals = client.get("/api/memory/facts/proposals", params={"user_id": "u1"})
    assert proposals.status_code == 200
    assert proposals.json()[0]["memory_id"] == proposal["memory_id"]

    decided = client.post(
        "/api/memory/facts/decide",
        json={
            "user_id": "u1",
            "memory_id": proposal["memory_id"],
            "action": "replace",
            "expected_version": proposal["version"],
        },
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["outcome"] == "replaced"

    active = client.get(
        "/api/memory/facts", params={"user_id": "u1", "status": "active"}
    ).json()
    assert [item["memory_id"] for item in active] == [proposal["memory_id"]]
    archived = client.get(
        f"/api/memory/facts/{first_id}", params={"user_id": "u1"}
    ).json()
    assert archived["status"] == "archived"


def test_fact_memory_and_entities_are_tenant_isolated(client: TestClient):
    first = client.post(
        "/api/memory/facts/propose",
        headers={"X-MemoryHub-Tenant": "tenant-a"},
        json={"user_id": "u1", "triples": [{
            "subject": "同名公司", "predicate": "总部所在地", "object": "北京",
            "subject_type": "Organization", "object_type": "Location",
        }]},
    )
    second = client.post(
        "/api/memory/facts/propose",
        headers={"X-MemoryHub-Tenant": "tenant-b"},
        json={"user_id": "u1", "triples": [{
            "subject": "同名公司", "predicate": "总部所在地", "object": "北京",
            "subject_type": "Organization", "object_type": "Location",
        }]},
    )
    assert first.status_code == second.status_code == 200
    first_id = first.json()["created"][0]["memory_id"]
    second_id = second.json()["created"][0]["memory_id"]
    assert first_id != second_id
    assert len(client.get("/api/memory/facts", headers={"X-MemoryHub-Tenant": "tenant-a"}, params={"user_id": "u1"}).json()) == 1
    assert len(client.get("/api/memory/facts", headers={"X-MemoryHub-Tenant": "tenant-b"}, params={"user_id": "u1"}).json()) == 1
    assert client.get(
        f"/api/memory/facts/{first_id}",
        headers={"X-MemoryHub-Tenant": "tenant-b"},
        params={"user_id": "u1"},
    ).status_code == 404
    assert client.delete(
        f"/api/memory/facts/{first_id}",
        headers={"X-MemoryHub-Tenant": "tenant-b"},
        params={"user_id": "u1"},
    ).status_code == 404


def test_duplicate_proposal_reports_evidence_reinforcement(client: TestClient):
    first = _propose(client, "张三")
    second = _propose(client, "张三")
    assert second["pending"] == []
    assert second["created"][0]["memory_id"] == first["created"][0]["memory_id"]
    assert second["created"][0]["outcome"] == "duplicate"


def test_entity_resolution_proposal_does_not_overwrite_active_fact(client: TestClient):
    payload = {
        "user_id": "u1",
        "triples": [{
            "subject": "同名公司", "predicate": "总部所在地", "object": "北京",
            "subject_type": "Organization", "object_type": "Location",
        }],
    }
    first = client.post("/api/memory/facts/propose", json=payload).json()
    active_id = first["created"][0]["memory_id"]
    semantic_repo = FactSemanticRepository(client.app.state.db)
    active_subject_id = semantic_repo.get_binding(active_id, "default", "u1").subject_id
    second_entity = Entity(
        entity_id=Entity.make_id("Organization", "同名公司", "u1", "default", "second"),
        canonical_name="同名公司", entity_type="Organization", aliases=["同名公司"],
        user_id="u1", tenant_id="default",
    )
    semantic_repo.save_entity(second_entity)

    pending = client.post("/api/memory/facts/propose", json=payload).json()
    proposal = pending["pending"][0]
    assert proposal["memory_id"] != active_id
    assert client.get(
        f"/api/memory/facts/{active_id}", params={"user_id": "u1"}
    ).json()["status"] == "active"

    decided = client.post("/api/memory/facts/decide", json={
        "user_id": "u1", "memory_id": proposal["memory_id"],
        "action": "select_existing", "subject_id": active_subject_id,
        "expected_version": proposal["version"],
    })
    assert decided.status_code == 200, decided.text
    assert decided.json()["outcome"] == "duplicate"
    assert client.get(
        "/api/memory/facts/proposals", params={"user_id": "u1"}
    ).json() == []
