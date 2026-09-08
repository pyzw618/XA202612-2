from concurrent.futures import ThreadPoolExecutor
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
    semantic_repo = FactSemanticRepository(client.app.state.db)
    assert semantic_repo.list_decisions(tenant_id="default", user_id="u1")

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
    assert semantic_repo.list_decisions(tenant_id="default", user_id="u1") == []

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


def test_replace_only_targets_the_conflicting_subject(client: TestClient):
    company_b_id = ""
    for subject, value in (("公司A", "北京"), ("公司B", "上海")):
        result = client.post("/api/memory/facts/propose", json={
            "user_id": "u1", "triples": [{
                "subject": subject, "predicate": "总部所在地", "object": value,
                "subject_type": "Organization", "object_type": "Location",
                "single_value": True,
            }],
        }).json()
        assert result["created"]
        if subject == "公司B":
            company_b_id = result["created"][0]["memory_id"]

    pending = client.post("/api/memory/facts/propose", json={
        "user_id": "u1", "triples": [{
            "subject": "公司A", "predicate": "总部所在地", "object": "深圳",
            "subject_type": "Organization", "object_type": "Location",
            "single_value": True,
        }],
    }).json()["pending"][0]
    assert len(pending["decision_task"]["existing_memory_ids"]) == 1
    assert company_b_id not in pending["decision_task"]["existing_memory_ids"]


def test_missing_tenant_header_is_default_not_wildcard(client: TestClient):
    base = {"user_id": "u1", "triples": [{
        "subject": "默认公司", "predicate": "总部所在地", "object": "北京",
        "subject_type": "Organization", "object_type": "Location",
    }]}
    assert client.post("/api/memory/facts/propose", json=base).json()["created"]
    other = {"user_id": "u1", "triples": [{
        **base["triples"][0], "subject": "租户公司", "object": "上海",
    }]}
    assert client.post(
        "/api/memory/facts/propose",
        headers={"X-MemoryHub-Tenant": "tenant-a"}, json=other,
    ).json()["created"]
    rows = client.get("/api/memory/facts", params={"user_id": "u1"}).json()
    assert [row["subject"] for row in rows] == ["默认公司"]


def test_project_scope_without_project_id_is_resumable(client: TestClient):
    response = client.post("/api/memory/facts/propose", json={
        "user_id": "u1", "scope_hint": "project", "triples": [{
            "subject": "项目A", "predicate": "状态", "object": "开发中",
        }],
    }).json()
    proposal = response["pending"][0]
    assert proposal["decision_task"]["decision_type"] == "scope_resolution"
    decided = client.post("/api/memory/facts/decide", json={
        "user_id": "u1", "memory_id": proposal["memory_id"],
        "action": "select_existing", "scope": "global",
        "expected_version": proposal["version"],
    })
    assert decided.status_code == 200, decided.text


def test_custom_predicate_cardinality_is_persistent(client: TestClient):
    first = client.post("/api/memory/facts/propose", json={
        "user_id": "u1", "triples": [{
            "subject": "系统", "predicate": "首选镜像", "object": "镜像A",
            "single_value": True,
        }],
    }).json()
    assert first["created"]
    changed = client.post("/api/memory/facts/propose", json={
        "user_id": "u1", "triples": [{
            "subject": "系统", "predicate": "首选镜像", "object": "镜像B",
            "single_value": False,
        }],
    }).json()
    assert changed["pending"][0]["decision_task"]["decision_type"] == "predicate_cardinality"


def test_concurrent_single_value_writes_leave_only_one_active(client: TestClient):
    def submit(value: str):
        return client.post("/api/memory/facts/propose", json={
            "user_id": "concurrent-user", "triples": [{
                "subject": "并发项目", "predicate": "负责人", "object": value,
                "subject_type": "Other", "object_type": "Person",
                "single_value": True,
            }],
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ["张三", "李四"]))
    assert all(response.status_code == 200 for response in responses)
    active = client.get(
        "/api/memory/facts", params={"user_id": "concurrent-user", "status": "active"}
    ).json()
    pending = client.get(
        "/api/memory/facts/proposals", params={"user_id": "concurrent-user"}
    ).json()
    assert len(active) == 1
    assert len(pending) == 1
