from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from memoryhub.adapter.api import FactProposeRequest, get_fact_evidence, propose_facts
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository


def _request(tmp_path):
    db = Database(str(tmp_path / "facts.db"))
    db.init_schema()
    prefs = PreferenceRepository(db)
    knowledge = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=prefs, know_repo=knowledge, project_immediately=False
    )
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(memory_write_service=writer, know_repo=knowledge)
        )
    ), knowledge


def _propose(request, *, user="alice", scope="global", project_id=None, evidence="source"):
    return asyncio.run(
        propose_facts(
            FactProposeRequest(
                user_id=user,
                scope_hint=scope,
                project_id=project_id,
                triples=[{
                    "subject": "release", "predicate": "uses", "object": "sqlite",
                    "evidence": evidence,
                }],
            ),
            request,
        )
    )


def test_fact_proposal_persists_evidence_and_isolates_project_and_user(tmp_path) -> None:
    request, repository = _request(tmp_path)
    global_fact = _propose(request, evidence="global evidence")["created"][0]
    project_a = _propose(request, scope="project", project_id="project-a", evidence="A evidence")["created"][0]
    project_b = _propose(request, scope="project", project_id="project-b", evidence="B evidence")["created"][0]
    other_user = _propose(request, user="bob", evidence="bob evidence")["created"][0]

    assert len({global_fact["fact_id"], project_a["fact_id"], project_b["fact_id"], other_user["fact_id"]}) == 4
    assert repository.get_by_id(project_a["fact_id"]).project_id == "project-a"
    evidence = asyncio.run(get_fact_evidence(project_a["fact_id"], request, "alice", "project-a"))
    assert [item["content"] for item in evidence] == ["A evidence"]
    with pytest.raises(HTTPException) as hidden:
        asyncio.run(get_fact_evidence(project_a["fact_id"], request, "alice", "project-b"))
    assert hidden.value.status_code == 404


def test_fact_proposal_rejects_missing_evidence_and_invalid_project_scope(tmp_path) -> None:
    request, _ = _request(tmp_path)
    missing = _propose(request, evidence="")
    assert missing["created"] == []
    assert missing["failed"][0]["reason"] == "evidence is required"
    with pytest.raises(HTTPException) as invalid:
        _propose(request, scope="project", project_id=None)
    assert invalid.value.status_code == 422


def test_same_scope_fact_updates_in_place_without_losing_new_evidence(tmp_path) -> None:
    request, repository = _request(tmp_path)
    first = _propose(request, scope="project", project_id="project-a", evidence="first")["created"][0]
    second = _propose(request, scope="project", project_id="project-a", evidence="second")["created"][0]
    assert first["fact_id"] == second["fact_id"]
    stored = repository.get_by_id(first["fact_id"])
    assert stored.version == 2
    assert [item.content for item in stored.evidences] == ["first", "second"]
