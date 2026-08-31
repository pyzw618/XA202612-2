"""Channel executors that adapt the existing retrieval stack to vNext retrieval.

These executors let the vNext ``RetrievalService`` reuse the current vector,
keyword and in-memory lookup infrastructure without copying algorithms into
S3 components.  Each executor returns ``RetrievedMemory`` candidates so later
stages (fusion, rerank, scope, budget) see a uniform shape.

Channel coverage:

* ``vector``   -- legacy retriever (Milvus/FAISS hybrid) reuse.
* ``working``  -- structured Working State lookup (task match, then session
  / recent fallback).  Never goes through an embedding.
* ``episode``  -- structured Task Episode lookup (task match, then session
  / recent fallback with deterministic query relevance).

Later channels (keyword/metadata/authority) register here as their executors
land; a missing executor degrades to an empty channel result.
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
from memoryhub.retrieval.keyword_search import _tokenize
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


# --------------------------------------------------------------------------
# Working State channel: structured lookup, never an embedding search.
# --------------------------------------------------------------------------

WORKING_FALLBACK_LIMIT = 3

_WORKING_CONTENT_FIELDS = (
    "current_goal",
    "current_step",
    "pending_steps",
    "completed_steps",
    "constraints",
    "active_entities",
    "blockers",
    "recent_findings",
    "recent_failures",
    "next_action",
)


def _working_text(state: dict[str, Any]) -> str:
    """Compact deterministic one-line summary of a working state."""
    parts: list[str] = []
    if state.get("current_goal"):
        parts.append(f"goal: {state['current_goal']}")
    if state.get("current_step"):
        parts.append(f"current step: {state['current_step']}")
    if state.get("next_action"):
        parts.append(f"next: {state['next_action']}")
    blockers = state.get("blockers") or []
    if blockers:
        parts.append(f"blockers: {'; '.join(str(item) for item in blockers[:3])}")
    pending = state.get("pending_steps") or []
    if pending:
        parts.append(f"pending: {'; '.join(str(item) for item in pending[:3])}")
    return "; ".join(parts) if parts else "working state has no active fields"


def _working_content(state: dict[str, Any]) -> dict[str, Any]:
    """Carry the structured working fields so results can restore progress."""
    content: dict[str, Any] = {}
    for key in _WORKING_CONTENT_FIELDS:
        value = state.get(key)
        if value in (None, "", [], {}):
            continue
        content[key] = value
    content["text"] = _working_text(state)
    return content


def _working_memory_from_view(
    view: Any, *, score: float, breakdown: dict[str, Any]
) -> RetrievedMemory:
    state = view.state or {}
    return RetrievedMemory(
        tenant_id=view.tenant_id,
        user_id=view.user_id,
        memory_id=f"ws:{view.working_state_id}",
        memory_type=MemoryType.SEMANTIC,
        layer=LifecycleLayer.WORKING,
        scope_level=MemoryScope.TASK,
        scope=view.task_id,
        content_version=max(1, int(view.version)),
        projection_version=0,
        evolution_status=EvolutionStatus.ACTIVE.value,
        content=_working_content(state),
        score=max(0.0, float(score)),
        score_breakdown=breakdown,
        source_ids=[f"working_state:{view.working_state_id}"],
    )


def build_working_executor(working_repository: Any) -> Any:
    """Executor for the ``working`` channel backed by WorkingStateRepository.

    Narrowing order: exact ``(tenant, user, task_id)`` match first, then the
    most recent working states bound to the request session, then the user's
    most recent states.  Results stay bounded in every case so historical
    states are never returned without limit.
    """

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        if working_repository is None:
            return []
        try:
            task_id = (request.task_id or "").strip()
            if task_id:
                view = working_repository.get(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    task_id=task_id,
                )
                if view is not None and view.task_id:
                    return [
                        _working_memory_from_view(
                            view,
                            score=1.0,
                            breakdown={"channel": channel, "match": "task"},
                        )
                    ]
            session_id = (request.session_id or "").strip()
            views = working_repository.list_recent(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                session_id=session_id or None,
                limit=WORKING_FALLBACK_LIMIT,
            )
        except Exception:
            # Degrade gracefully like the other channels.
            return []

        results: list[RetrievedMemory] = []
        for rank, view in enumerate(views):
            if not getattr(view, "task_id", ""):
                continue
            score = round(max(0.5, 1.0 - 0.1 * rank), 6)
            results.append(
                _working_memory_from_view(
                    view,
                    score=score,
                    breakdown={
                        "channel": channel,
                        "match": "recent",
                        "recency_rank": rank,
                    },
                )
            )
        return results

    return executor


# --------------------------------------------------------------------------
# Task Episode channel: structured lookup with deterministic relevance.
# --------------------------------------------------------------------------

EPISODE_FALLBACK_LIMIT = 5
_EPISODE_EVENT_WINDOW = 5


def _episode_events(episode_repository: Any, view: Any) -> list[str]:
    """Compact bounded summaries of the latest episode events."""
    try:
        events = episode_repository.list_events(
            tenant_id=view.tenant_id,
            user_id=view.user_id,
            episode_id=view.episode_id,
        )
    except Exception:
        return []
    summaries: list[str] = []
    for event in events[-_EPISODE_EVENT_WINDOW:]:
        payload = event.payload or {}
        summary = str(payload.get("summary") or payload.get("action") or "").strip()
        if not summary:
            summary = str(event.event_type)
        summaries.append(f"[{event.event_type}] {summary}"[:200])
    return summaries


def _query_relevance(query: str, text: str) -> float:
    """Deterministic token-overlap relevance in [0, 1]; 0.5 without signal."""
    tokens = [token for token in _tokenize(query or "") if token]
    if not tokens:
        return 0.5
    document_tokens = set(_tokenize(text or ""))
    if not document_tokens:
        return 0.0
    hits = sum(1 for token in tokens if token in document_tokens)
    return hits / len(tokens)


def _episode_memory_from_view(
    view: Any,
    *,
    score: float,
    breakdown: dict[str, Any],
    key_events: list[str],
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id=view.tenant_id,
        user_id=view.user_id,
        memory_id=f"ep:{view.episode_id}",
        memory_type=MemoryType.EPISODIC,
        layer=LifecycleLayer.EPISODE,
        scope_level=MemoryScope.TASK,
        scope=view.task_id,
        content_version=max(1, int(view.snapshot_version)),
        projection_version=0,
        evolution_status=EvolutionStatus.ACTIVE.value,
        content={
            "text": (view.goal or "").strip() or f"Episode for task {view.task_id}",
            "goal": view.goal,
            "status": view.status,
            "current_phase": view.current_phase,
            "task_id": view.task_id,
            "session_id": view.session_id,
            "key_events": key_events,
        },
        score=max(0.0, float(score)),
        score_breakdown=breakdown,
        source_ids=[f"episode:{view.episode_id}"],
    )


def build_episode_executor(episode_repository: Any) -> Any:
    """Executor for the ``episode`` channel backed by EpisodeRepository.

    Narrowing order: exact ``(tenant, user, task_id)`` episode first, then the
    most recent episodes bound to the request session (ARCHIVED excluded).
    Fallback candidates are ranked by deterministic query relevance against
    the episode goal, with recency as the tiebreaker; exact task matches win
    outright.  Episode goal and key events are used directly -- no embedding.
    """

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        if episode_repository is None:
            return []
        try:
            task_id = (request.task_id or "").strip()
            if task_id:
                view = episode_repository.get_by_task_id(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    task_id=task_id,
                    status=None,
                )
                if view is not None and view.task_id:
                    return [
                        _episode_memory_from_view(
                            view,
                            score=1.0,
                            breakdown={"channel": channel, "match": "task"},
                            key_events=_episode_events(episode_repository, view),
                        )
                    ]
            session_id = (request.session_id or "").strip()
            views = episode_repository.list_recent(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                session_id=session_id or None,
                limit=EPISODE_FALLBACK_LIMIT,
            )
        except Exception:
            # Degrade gracefully like the other channels.
            return []

        ranked: list[tuple[int, float, Any, float]] = []
        for rank, view in enumerate(views):
            if not getattr(view, "task_id", ""):
                continue
            relevance = _query_relevance(request.query, view.goal)
            score = round(0.5 + 0.5 * relevance, 6)
            ranked.append((rank, relevance, view, score))
        # Stable order: relevance first, recency as the tiebreaker.
        ranked.sort(key=lambda item: (-item[3], item[0]))

        results: list[RetrievedMemory] = []
        for rank, relevance, view, score in ranked:
            results.append(
                _episode_memory_from_view(
                    view,
                    score=score,
                    breakdown={
                        "channel": channel,
                        "match": "recent",
                        "relevance": round(relevance, 6),
                        "recency_rank": rank,
                    },
                    key_events=_episode_events(episode_repository, view),
                )
            )
        return results

    return executor


def build_channel_executors(state: Any) -> dict[str, Any]:
    """Build the channel executors available in the current application state.

    ``vector`` maps to the existing retriever; ``working`` and ``episode``
    read their structured repositories directly.  Channels without a real
    executor in state (keyword/metadata/authority) are simply absent so the
    retrieval service degrades them to empty results until their executors
    land.
    """
    executors: dict[str, Any] = {}
    if getattr(state, "retriever", None) is not None:
        executors["vector"] = build_legacy_retriever_executor(state)
    working_repository = getattr(state, "working_state_repository", None)
    if working_repository is not None:
        executors["working"] = build_working_executor(working_repository)
    episode_repository = getattr(state, "episode_repository", None)
    if episode_repository is not None:
        executors["episode"] = build_episode_executor(episode_repository)
    return executors
