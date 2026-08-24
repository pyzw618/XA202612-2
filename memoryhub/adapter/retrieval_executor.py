"""Channel executors that adapt the existing retrieval stack to vNext retrieval.

These executors let the vNext ``RetrievalService`` reuse the current vector,
keyword and in-memory lookup infrastructure without copying algorithms into
S3 components.  Each executor returns ``RetrievedMemory`` candidates so later
stages (fusion, rerank, scope, budget) see a uniform shape.
"""

from __future__ import annotations

from typing import Any

from memoryhub.adapter.schemas import SearchRequest, SearchResult
from memoryhub.adapter.vnext_schemas import (
    MemoryRetrievalRequest,
    RetrievedMemory,
)
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    MemoryScope,
    MemoryType,
)
from memoryhub.retrieval.planner import RetrievalPlan


def _search_request_from_vnext(request: MemoryRetrievalRequest) -> SearchRequest:
    """Build the legacy SearchRequest used by the current retriever."""
    from memoryhub.adapter.schemas import SceneScope

    return SearchRequest(
        user_id=request.user_id,
        query=request.query,
        context=SceneScope(),
        project_id="",
        top_k=request.page_size,
        memory_types=[],
        min_confidence=0.0,
        level="long",
        session_id=request.session_id,
    )


def _search_result_to_retrieved_memory(result: SearchResult) -> RetrievedMemory | None:
    """Best-effort conversion from legacy SearchResult to vNext RetrievedMemory."""
    metadata = result.metadata or {}
    scope_level_str = metadata.get("scope_level", "GLOBAL")
    scope = metadata.get("scope", "GLOBAL")
    memory_type_str = result.memory_type or "semantic"
    memory_level_str = result.memory_level or "long"
    evolution_status = metadata.get("evolution_status", "ACTIVE")
    content_version = metadata.get("content_version", 1)

    scope_level = _safe_scope(scope_level_str)
    memory_type = _safe_memory_type(memory_type_str)
    layer = _safe_layer(memory_level_str)
    status = _safe_status(evolution_status)

    return RetrievedMemory(
        tenant_id=metadata.get("tenant_id") or "default",
        user_id=result.user_id or "default",
        memory_id=result.memory_id,
        memory_type=memory_type,
        layer=layer,
        scope_level=scope_level,
        scope=scope if scope else "GLOBAL",
        content_version=int(content_version) if isinstance(content_version, int) else 1,
        evolution_status=status.value,
        content={"text": result.content or ""},
        score=float(result.score),
        score_breakdown=metadata.get("score_breakdown", {}),
        source_ids=[result.source or "retriever"],
    )


def _safe_scope(value: str) -> MemoryScope:
    try:
        return MemoryScope(value.upper())
    except ValueError:
        return MemoryScope.GLOBAL


def _safe_memory_type(value: str) -> MemoryType:
    from memoryhub.domain.contracts import LEGACY_TYPE_MAP

    normalized = (value or "").strip().lower()
    if normalized == "knowledge":
        normalized = "knowledge.fact"
    return LEGACY_TYPE_MAP.get(normalized, MemoryType.SEMANTIC)


def _safe_layer(value: str) -> LifecycleLayer:
    from memoryhub.domain.contracts import LEGACY_LAYER_MAP

    normalized = (value or "").strip().lower()
    return LEGACY_LAYER_MAP.get(normalized, LifecycleLayer.LONG_TERM)


def _safe_status(value: str) -> EvolutionStatus:
    try:
        return EvolutionStatus(value.upper())
    except ValueError:
        return EvolutionStatus.ACTIVE


def build_legacy_retriever_executor(state: Any) -> Any:
    """Return an executor callable that uses the existing retriever/search path.

    The returned executor has signature ``(request, plan, channel) -> list[RetrievedMemory]``.
    """

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        retriever = getattr(state, "retriever", None)
        if retriever is None:
            return []
        try:
            search_req = _search_request_from_vnext(request)
            response = retriever.search(search_req)
        except Exception:
            return []

        results: list[RetrievedMemory] = []
        for result in response.results:
            converted = _search_result_to_retrieved_memory(result)
            if converted is not None:
                results.append(converted)
        return results

    return executor


def build_channel_executors(state: Any) -> dict[str, Any]:
    """Build a minimal set of channel executors from application state.

    The ``vector`` channel is mapped to the existing retriever so every read
    entrypoint can delegate to the same ``RetrievalService``.  Additional
    channels can be registered here as the retrieval stack evolves.
    """
    executors: dict[str, Any] = {}
    if getattr(state, "retriever", None) is not None:
        executors["vector"] = build_legacy_retriever_executor(state)
    return executors
