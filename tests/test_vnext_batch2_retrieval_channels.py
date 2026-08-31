from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from memoryhub.adapter.retrieval_executor import (
    build_authority_executor,
    build_channel_executors,
    build_keyword_executor,
    build_legacy_retriever_executor,
    build_metadata_executor,
)
from memoryhub.adapter.schemas import SearchRequest, SearchResponse, SearchResult
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.keyword_search import BM25Okapi, KeywordSearcher
from memoryhub.retrieval.planner import RetrievalPlan
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database


def _request(*, tenant_id: str = "tenant-1", user_id: str = "user-1", query: str = "report"):
    return MemoryRetrievalRequest(
        request_id="batch2-request",
        tenant_id=tenant_id,
        user_id=user_id,
        query=query,
        intent_hint=RetrievalIntent.PREFERENCE,
        page_size=5,
    )


def _plan() -> RetrievalPlan:
    return RetrievalPlan(
        intent=RetrievalIntent.PREFERENCE,
        enabled_channels=["vector", "keyword", "metadata", "authority"],
        required_layers=[],
        required_types=[MemoryType.PREFERENCE, MemoryType.SEMANTIC],
        top_k=5,
        keyword_top_k=10,
    )


def test_vector_executor_converts_legacy_search_result_without_user_id_field():
    class Retriever:
        def search(self, request: SearchRequest) -> SearchResponse:
            assert request.user_id == "user-1"
            return SearchResponse(
                results=[
                    SearchResult(
                        memory_id="m-vector",
                        memory_type="knowledge",
                        content="vector result",
                        score=0.9,
                        source="vector",
                        metadata={"tenant_id": "tenant-1", "user_id": "user-1"},
                    )
                ]
            )

    executor = build_legacy_retriever_executor(SimpleNamespace(retriever=Retriever()))
    results = executor(_request(), _plan(), "vector")

    assert [item.memory_id for item in results] == ["m-vector"]
    assert results[0].tenant_id == "tenant-1"
    assert results[0].user_id == "user-1"
    assert results[0].source_ids == ["vector"]


@pytest.mark.skipif(BM25Okapi is None, reason="optional rank-bm25 dependency is unavailable")
def test_keyword_executor_reuses_bm25_and_enforces_owner_metadata():
    keyword = KeywordSearcher()
    keyword.build_index(
        [
            (
                "m-owner",
                "report exact phrase",
                json.dumps(
                    {"tenant_id": "tenant-1", "user_id": "user-1", "memory_type": "knowledge"}
                ),
            ),
            (
                "m-other-user",
                "report exact phrase",
                json.dumps(
                    {"tenant_id": "tenant-1", "user_id": "user-2", "memory_type": "knowledge"}
                ),
            ),
        ]
    )

    results = build_keyword_executor(keyword)(_request(query="exact phrase"), _plan(), "keyword")

    assert results
    assert [item.memory_id for item in results] == ["m-owner"]


def test_authority_executor_reads_only_active_tenant_user_records():
    db_path = Path("evaluation/results") / f"vnext_batch2_authority_{os.getpid()}.db"
    db = Database(db_path=str(db_path))
    db.init_schema()
    repository = AuthorityRepository(db)
    active = LongTermEnvelope(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="authority-active",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="report.style",
        content={"text": "Use concise reports"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        confidence=0.9,
        utility=0.8,
        evidence_refs=["event-authority"],
    )
    other_user = active.model_copy(update={"memory_id": "authority-other", "user_id": "user-2"})
    inactive = active.model_copy(
        update={"memory_id": "authority-inactive", "evolution_status": EvolutionStatus.ARCHIVED}
    )
    repository.save(active)
    repository.save(other_user)
    repository.save(inactive)

    results = build_authority_executor(repository)(_request(), _plan(), "authority")

    assert [item.memory_id for item in results] == ["authority-active"]
    assert results[0].source_ids == ["authority:authority-active"]
    db.close()
    db_path.unlink(missing_ok=True)


def test_metadata_executor_uses_existing_memory_lookup_with_scope_and_owner_filter():
    owner = SimpleNamespace(
        memory_id="metadata-owner",
        user_id="user-1",
        tenant_id="tenant-1",
        memory_type="preference",
        text="report format",
        payload={"style": "concise"},
        scope=SimpleNamespace(scene="", task_type="", app=""),
        confidence=0.8,
        status="active",
        version=2,
    )
    other = SimpleNamespace(
        memory_id="metadata-other",
        user_id="user-2",
        tenant_id="tenant-1",
        memory_type="preference",
        text="report format",
        payload={},
        scope=SimpleNamespace(scene="", task_type="", app=""),
        confidence=0.8,
        status="active",
        version=1,
    )
    results = build_metadata_executor({owner.memory_id: owner, other.memory_id: other})(
        _request(query="report format"), _plan(), "metadata"
    )

    assert [item.memory_id for item in results] == ["metadata-owner"]
    assert results[0].layer.value == "LONG_TERM"


def test_channel_registration_exposes_all_batch2_and_structured_channels():
    state = SimpleNamespace(
        retriever=object(),
        keyword_search=object(),
        memory_lookup={},
        authority_repository=object(),
        working_state_repository=None,
        episode_repository=None,
    )

    assert set(build_channel_executors(state)) == {
        "vector",
        "keyword",
        "metadata",
        "authority",
    }
