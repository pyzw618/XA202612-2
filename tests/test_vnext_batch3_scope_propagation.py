"""Stage 2 Batch 3: Intent and scope must survive every retrieval boundary."""

from __future__ import annotations

from types import SimpleNamespace

from memoryhub.adapter.retrieval_executor import (
    build_authority_executor,
    build_legacy_retriever_executor,
)
from memoryhub.adapter.schemas import SearchResponse, SearchResult
from memoryhub.adapter.vnext_api import _legacy_request
from memoryhub.adapter.vnext_schemas import (
    MemoryRetrievalRequest,
    RetrievedMemory,
    legacy_search_request_from_vnext,
)
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.planner import RetrievalPlan
from memoryhub.retrieval.scope_resolver import ScopeResolver


def _request(**updates: object) -> MemoryRetrievalRequest:
    values: dict[str, object] = {
        "request_id": "batch3-request",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "query": "which build tool should this project use",
        "scope_level": MemoryScope.PROJECT,
        "scope": "PROJECT:project-b",
        "session_id": "session-b",
        "page_size": 4,
    }
    values.update(updates)
    return MemoryRetrievalRequest(**values)


def _plan(intent: RetrievalIntent = RetrievalIntent.PREFERENCE) -> RetrievalPlan:
    return RetrievalPlan(
        intent=intent,
        enabled_channels=["vector", "authority"],
        required_types=[MemoryType.PREFERENCE],
        top_k=4,
        vector_top_k=8,
    )


def _memory(memory_id: str, *, scope: str) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.GLOBAL if scope == "GLOBAL" else MemoryScope.PROJECT,
        scope=scope,
        content_version=1,
        evolution_status="ACTIVE",
        content={"text": memory_id},
        score=0.9,
        source_ids=[memory_id],
    )


def test_vnext_to_legacy_preserves_project_session_intent_and_type() -> None:
    request = _request(task_id="task-build", intent_hint=RetrievalIntent.PREFERENCE)

    legacy = legacy_search_request_from_vnext(
        request,
        intent=RetrievalIntent.PREFERENCE,
        memory_types=[MemoryType.PREFERENCE],
        top_k=8,
    )

    assert legacy.project_id == "project-b"
    assert legacy.context.task_type == "task-build"
    assert legacy.session_id == "session-b"
    assert legacy.level == "long"
    assert legacy.memory_types == ["preference"]
    assert legacy.top_k == 8
    assert _legacy_request(request).project_id == "project-b"


def test_vnext_to_legacy_maps_task_history_to_existing_legacy_scope() -> None:
    request = _request(
        scope_level=MemoryScope.TASK,
        scope="TASK:repair-sse",
        intent_hint=RetrievalIntent.TASK_HISTORY,
    )

    legacy = legacy_search_request_from_vnext(request)

    assert legacy.context.task_type == "repair-sse"
    assert legacy.level == "mid"


def test_vector_executor_passes_planned_scope_and_intent_to_legacy_retriever() -> None:
    captured = []

    class Retriever:
        def search(self, request):
            captured.append(request)
            return SearchResponse(
                results=[
                    SearchResult(
                        memory_id="project-b",
                        memory_type="preference",
                        content="Use Gradle",
                        score=0.9,
                        metadata={
                            "tenant_id": "tenant-1",
                            "user_id": "user-1",
                            "scope_level": "PROJECT",
                            "scope": "PROJECT:project-b",
                        },
                    ),
                    SearchResult(
                        memory_id="project-a",
                        memory_type="preference",
                        content="Use Maven",
                        score=0.8,
                        metadata={
                            "tenant_id": "tenant-1",
                            "user_id": "user-1",
                            "scope_level": "PROJECT",
                            "scope": "PROJECT:project-a",
                        },
                    ),
                ]
            )

    results = build_legacy_retriever_executor(SimpleNamespace(retriever=Retriever()))(
        _request(), _plan(), "vector"
    )

    assert captured[0].project_id == "project-b"
    assert captured[0].memory_types == ["preference"]
    assert captured[0].top_k == 8
    assert [item.memory_id for item in results] == ["project-b"]


def test_authority_executor_returns_exact_project_and_global_fallback_only() -> None:
    def envelope(memory_id: str, scope: str) -> LongTermEnvelope:
        return LongTermEnvelope(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id=memory_id,
            memory_type=MemoryType.PREFERENCE,
            normalized_key=memory_id,
            content={"text": memory_id},
            scope_level=MemoryScope.GLOBAL if scope == "GLOBAL" else MemoryScope.PROJECT,
            scope=scope,
            evolution_status=EvolutionStatus.ACTIVE,
            confidence=0.9,
            utility=0.8,
            evidence_refs=["event-1"],
        )

    repository = SimpleNamespace(
        list=lambda **_kwargs: [
            envelope("project-a", "PROJECT:project-a"),
            envelope("project-b", "PROJECT:project-b"),
            envelope("global", "GLOBAL"),
        ]
    )

    results = build_authority_executor(repository)(_request(), _plan(), "authority")

    assert {item.memory_id for item in results} == {"project-b", "global"}


def test_scope_resolver_rejects_unrelated_project_even_without_a_conflict_group() -> None:
    resolver = ScopeResolver()
    result = resolver.resolve(
        [_memory("build-tool-a", scope="PROJECT:project-a"), _memory("global", scope="GLOBAL")],
        tenant_id="tenant-1",
        user_id="user-1",
        preferred_scope_level=MemoryScope.PROJECT,
        preferred_scope="PROJECT:project-b",
    )

    assert [item.memory_id for item in result.selected] == ["global"]
    assert result.dropped == [
        (_memory("build-tool-a", scope="PROJECT:project-a"), "scope does not match request")
    ]
