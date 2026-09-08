from __future__ import annotations

from memoryhub.adapter.schemas import SearchRequest, SearchResult
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, legacy_search_request_from_vnext
from memoryhub.domain.contracts import MemoryScope
from memoryhub.retrieval.hybrid import HybridRetriever


class _Vector:
    def search(self, _vector, top_k: int):
        rows = [
            SearchResult(memory_id="blocked", memory_type="knowledge", content="blocked", score=0.99,
                         metadata={"user_id": "alice", "confidence": 0.2, "scope": {"scene": "code", "task_type": "fix"}}),
            SearchResult(memory_id="wrong-scene", memory_type="knowledge", content="wrong", score=0.95,
                         metadata={"user_id": "alice", "confidence": 0.9, "scope": {"scene": "chat", "task_type": "fix"}}),
            SearchResult(memory_id="eligible", memory_type="knowledge", content="eligible", score=0.8,
                         metadata={"user_id": "alice", "confidence": 0.9, "scope": {"scene": "code", "task_type": "fix"}}),
            SearchResult(memory_id="other-user", memory_type="knowledge", content="private", score=0.7,
                         metadata={"user_id": "bob", "confidence": 1.0, "scope": {"scene": "code", "task_type": "fix"}}),
        ]
        return rows[:top_k]


def test_hard_filters_precede_top_k_and_keep_later_eligible_candidate() -> None:
    retriever = HybridRetriever(vector_search=_Vector(), embedding_fn=lambda _q: [0.0])
    response = retriever.search(SearchRequest(
        user_id="alice", query="release", top_k=1, memory_types=["knowledge"],
        min_confidence=0.8, scenes=["code"], task_types=["fix"],
    ))
    assert [item.memory_id for item in response.results] == ["eligible"]


def test_vnext_conversion_preserves_all_server_filter_predicates() -> None:
    request = MemoryRetrievalRequest(
        request_id="filter-request", tenant_id="tenant-a", user_id="alice", query="release",
        page_size=3, scope_level=MemoryScope.PROJECT, scope="PROJECT:project-a",
        memory_types=["fact"], min_confidence=0.75, scenes=["code"], task_types=["fix"],
    )
    legacy = legacy_search_request_from_vnext(request)
    assert legacy.project_id == "project-a"
    assert legacy.memory_types == ["fact"]
    assert legacy.min_confidence == 0.75
    assert legacy.scenes == ["code"]
    assert legacy.task_types == ["fix"]
