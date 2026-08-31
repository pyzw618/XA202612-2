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

import json
from typing import Any

from memoryhub.adapter.schemas import SearchResult
from memoryhub.adapter.vnext_schemas import (
    MemoryRetrievalRequest,
    RetrievedMemory,
    legacy_search_request_from_vnext,
)
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    MemoryScope,
    MemoryType,
)
from memoryhub.retrieval.keyword_search import _tokenize
from memoryhub.retrieval.planner import RetrievalPlan


def _search_request_from_vnext(
    request: MemoryRetrievalRequest, plan: RetrievalPlan | None = None
) -> Any:
    """Build the legacy SearchRequest used by the current retriever."""
    return legacy_search_request_from_vnext(
        request,
        intent=plan.intent if plan is not None else None,
        memory_types=plan.required_types if plan is not None else None,
        top_k=plan.vector_top_k if plan is not None else None,
    )


def _scope_text(value: Any) -> str:
    if isinstance(value, str):
        return value or "GLOBAL"
    if isinstance(value, dict):
        for key in ("scope", "project_id", "task_id", "task_type", "scene", "app"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value) if value else "GLOBAL"


def _requested_project_id(request: MemoryRetrievalRequest) -> str | None:
    """Return an explicit project constraint, or None for an unscoped request."""
    if request.scope_level is not MemoryScope.PROJECT or not request.scope:
        return None
    value = request.scope.strip()
    if value.upper().startswith("PROJECT:"):
        value = value.split(":", 1)[1]
    return value or None


def _legacy_memory_metadata(memory: Any) -> dict[str, Any]:
    extra_payload = getattr(memory, "extra_payload", {}) or {}
    authority = extra_payload.get("vnext_authority", {})
    status = getattr(memory, "status", "ACTIVE")
    return {
        "tenant_id": getattr(memory, "tenant_id", "") or authority.get("tenant_id", "default"),
        "user_id": getattr(memory, "user_id", "default"),
        "memory_type": getattr(memory, "memory_type", "semantic"),
        "confidence": float(getattr(memory, "confidence", 0.0) or 0.0),
        "status": getattr(status, "value", status),
        "scope": getattr(memory, "scope", {}),
    }


def _legacy_memory_text(memory: Any) -> str:
    parts = [
        getattr(memory, "text", ""),
        getattr(memory, "content", ""),
        getattr(memory, "name", ""),
        getattr(memory, "subject", ""),
        getattr(memory, "predicate", ""),
        getattr(memory, "object_value", ""),
    ]
    steps = getattr(memory, "steps", []) or []
    parts.extend(str(step) for step in steps)
    return " ".join(str(part).strip() for part in parts if part).strip()


def _memory_scope(metadata: dict[str, Any]) -> tuple[MemoryScope, str]:
    raw_scope = metadata.get("scope", "GLOBAL")
    authority = metadata.get("vnext_authority", {})
    scope_level = metadata.get("scope_level") or authority.get("scope_level")
    if scope_level:
        level = _safe_scope(scope_level)
    elif isinstance(raw_scope, dict) and raw_scope.get("project_id"):
        level = MemoryScope.PROJECT
    elif isinstance(raw_scope, dict) and any(
        raw_scope.get(key) for key in ("task_id", "task_type")
    ):
        level = MemoryScope.TASK
    elif isinstance(raw_scope, dict) and any(
        raw_scope.get(key) for key in ("scene", "app")
    ):
        level = MemoryScope.APPLICATION
    else:
        level = MemoryScope.GLOBAL
    return level, _scope_text(raw_scope)


def _search_result_to_retrieved_memory(
    result: SearchResult,
    *,
    tenant_id: str = "default",
    user_id: str = "default",
    source: str | None = None,
) -> RetrievedMemory | None:
    """Best-effort conversion from legacy SearchResult to vNext RetrievedMemory."""
    metadata = result.metadata or {}
    scope_level, scope = _memory_scope(metadata)
    memory_type_str = result.memory_type or "semantic"
    memory_level_str = result.memory_level or "long"
    evolution_status = metadata.get("evolution_status", "ACTIVE")
    content_version = metadata.get("content_version", 1)

    memory_type = _safe_memory_type(memory_type_str)
    layer = _safe_layer(memory_level_str)
    status = _safe_status(evolution_status)
    owner = metadata.get("user_id") or user_id
    if owner != user_id:
        return None
    result_tenant = metadata.get("tenant_id") or tenant_id
    if result_tenant != tenant_id:
        return None

    return RetrievedMemory(
        tenant_id=result_tenant,
        user_id=owner,
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
        source_ids=[source or result.source or "retriever"],
    )


def _safe_scope(value: str) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value
    try:
        return MemoryScope(str(value).upper())
    except (TypeError, ValueError):
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
            search_req = _search_request_from_vnext(request, plan)
            response = retriever.search(search_req)
        except Exception:
            return []

        results: list[RetrievedMemory] = []
        for result in response.results:
            converted = _search_result_to_retrieved_memory(
                result,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                source="vector",
            )
            if converted is not None:
                if _matches_request_scope(converted, request):
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
            project_id = _requested_project_id(request)
            if task_id:
                view = working_repository.get(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    task_id=task_id,
                    project_id=project_id,
                )
                if view is not None and view.task_id:
                    return [
                        _working_memory_from_view(
                            view,
                            score=1.0,
                            breakdown={"channel": channel, "match": "task"},
                        )
                    ]
                # An explicit task constraint is authoritative.  Do not silently
                # replace it with another recent task when the project/task pair
                # does not exist.
                return []
            session_id = (request.session_id or "").strip()
            views = working_repository.list_recent(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                session_id=session_id or None,
                project_id=project_id,
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
            project_id = _requested_project_id(request)
            if task_id:
                view = episode_repository.get_by_task_id(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    task_id=task_id,
                    project_id=project_id,
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
                # An explicit task constraint is authoritative.  A miss must not
                # degrade into another task's history.
                return []
            session_id = (request.session_id or "").strip()
            views = episode_repository.list_recent(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                session_id=session_id or None,
                project_id=project_id,
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


# --------------------------------------------------------------------------
# Long-term channels: reuse the existing BM25 and Authority adapters.
# --------------------------------------------------------------------------


def _memory_type_matches(memory_type: MemoryType, plan: RetrievalPlan | None) -> bool:
    return not plan or not plan.required_types or memory_type in plan.required_types


def _matches_request_scope(memory: RetrievedMemory, request: MemoryRetrievalRequest) -> bool:
    """Allow global fallback, otherwise require the exact requested scope.

    The executor boundary must not return project/task/session records from a
    different scope and rely on later conflict resolution to hide them.
    """
    if memory.tenant_id != request.tenant_id or memory.user_id != request.user_id:
        return False
    if request.scope_level is None or not request.scope:
        return True
    return memory.scope_level is MemoryScope.GLOBAL or (
        memory.scope_level is request.scope_level and memory.scope == request.scope
    )


def _long_term_memory_from_legacy(
    memory: Any,
    *,
    tenant_id: str,
    channel: str,
    score: float,
) -> RetrievedMemory:
    metadata = _legacy_memory_metadata(memory)
    memory_type = _safe_memory_type(str(metadata.get("memory_type", "semantic")))
    scope_level, scope = _memory_scope(metadata)
    text = _legacy_memory_text(memory)
    content: dict[str, Any] = {"text": text}
    if getattr(memory, "payload", None):
        content["payload"] = memory.payload
    if getattr(memory, "steps", None):
        content["steps"] = list(memory.steps)
    return RetrievedMemory(
        tenant_id=tenant_id,
        user_id=str(metadata.get("user_id") or "default"),
        memory_id=str(getattr(memory, "memory_id", "")),
        memory_type=memory_type,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=scope_level,
        scope=scope,
        content_version=max(1, int(getattr(memory, "version", 1) or 1)),
        evolution_status=_safe_status(str(metadata.get("status", "ACTIVE"))).value,
        content=content,
        score=max(0.0, float(score)),
        score_breakdown={"channel": channel},
        source_ids=[f"{channel}:{getattr(memory, 'memory_id', '')}"],
    )


def _normalize_keyword_scores(raw_results: list[SearchResult]) -> list[SearchResult]:
    """Min-max normalize BM25 scores into [0, 1].

    BM25Okapi can return negative scores when a term appears in more than half
    of the indexed documents (negative IDF).  The vNext ``RetrievedMemory`` schema
    requires a non-negative score, and downstream RRF weights expect comparable
    positive values, so we normalize the raw BM25 scores per query.
    """
    if not raw_results:
        return []
    scores = [float(r.score) for r in raw_results]
    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        # All results have the same signal; treat them as equally relevant.
        return [r.model_copy(update={"score": 1.0}) for r in raw_results]
    normalized: list[SearchResult] = []
    for result, raw_score in zip(raw_results, scores):
        norm_score = (raw_score - min_score) / (max_score - min_score)
        normalized.append(result.model_copy(update={"score": norm_score}))
    return normalized


def build_keyword_executor(keyword_search: Any) -> Any:
    """Execute BM25 independently of the Legacy hybrid fusion path."""

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        if keyword_search is None or not request.query:
            return []
        try:
            raw_results = keyword_search.search(
                request.query, top_k=max(1, plan.keyword_top_k)
            )
        except Exception:
            return []
        # BM25 raw scores may be negative when IDF is negative; normalize to [0, 1]
        # so downstream Pydantic constraints and RRF weights remain valid.
        normalized_results = _normalize_keyword_scores(raw_results)
        results: list[RetrievedMemory] = []
        for result in normalized_results:
            converted = _search_result_to_retrieved_memory(
                result,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                source=channel,
            )
            if converted is not None:
                if _matches_request_scope(converted, request):
                    results.append(converted)
        return results

    return executor


def build_authority_executor(authority_repository: Any) -> Any:
    """Read active, tenant/user-bound LongTermEnvelopes from Authority."""

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        if authority_repository is None:
            return []
        try:
            envelopes = authority_repository.list(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                include_inactive=False,
            )
        except Exception:
            return []

        ranked: list[tuple[float, Any]] = []
        for envelope in envelopes:
            if not _memory_type_matches(envelope.memory_type, plan):
                continue
            text = json.dumps(envelope.content, ensure_ascii=False, sort_keys=True)
            relevance = _query_relevance(
                request.query, f"{envelope.normalized_key} {text}"
            )
            scope_bonus = 0.1 if request.scope and envelope.scope == request.scope else 0.0
            ranked.append((min(1.0, 0.5 + 0.5 * relevance + scope_bonus), envelope))
        ranked.sort(key=lambda item: (-item[0], item[1].memory_id))
        results = [
            RetrievedMemory(
                tenant_id=envelope.tenant_id,
                user_id=envelope.user_id,
                memory_id=envelope.memory_id,
                memory_type=envelope.memory_type,
                layer=LifecycleLayer.LONG_TERM,
                scope_level=envelope.scope_level,
                scope=envelope.scope,
                content_version=envelope.content_version,
                projection_version=envelope.projection_version,
                evolution_status=envelope.evolution_status.value,
                content=dict(envelope.content),
                score=score,
                score_breakdown={"channel": channel, "authority": True},
                source_ids=[f"authority:{envelope.memory_id}"],
            )
            for score, envelope in ranked[: max(1, plan.top_k * 2)]
        ]
        return [memory for memory in results if _matches_request_scope(memory, request)]

    return executor


def build_metadata_executor(memory_lookup: dict[str, Any] | None) -> Any:
    """Metadata-only long-term candidate lookup over the existing memory cache."""

    def executor(
        request: MemoryRetrievalRequest,
        plan: RetrievalPlan,
        channel: str,
    ) -> list[RetrievedMemory]:
        results: list[RetrievedMemory] = []
        for memory in (memory_lookup or {}).values():
            metadata = _legacy_memory_metadata(memory)
            if metadata.get("tenant_id") != request.tenant_id:
                continue
            if metadata.get("user_id") != request.user_id:
                continue
            memory_type = _safe_memory_type(str(metadata.get("memory_type", "semantic")))
            if not _memory_type_matches(memory_type, plan):
                continue
            if plan.required_layers and LifecycleLayer.LONG_TERM not in plan.required_layers:
                continue
            text = _legacy_memory_text(memory)
            relevance = _query_relevance(request.query, text)
            candidate = _long_term_memory_from_legacy(
                memory,
                tenant_id=request.tenant_id,
                channel=channel,
                score=0.5 + 0.5 * relevance,
            )
            if _matches_request_scope(candidate, request):
                results.append(candidate)
        results.sort(key=lambda item: (-item.score, item.memory_id))
        return results[: max(1, plan.top_k * 2)]

    return executor


def build_channel_executors(state: Any) -> dict[str, Any]:
    """Build the channel executors available in the current application state.

    ``vector`` maps to the existing retriever; ``working`` and ``episode``
    read their structured repositories directly.  Long-term channels reuse
    the existing BM25, memory lookup and Authority adapters independently.
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
    keyword_search = getattr(state, "keyword_search", None)
    if keyword_search is not None:
        executors["keyword"] = build_keyword_executor(keyword_search)
    if getattr(state, "memory_lookup", None) is not None:
        executors["metadata"] = build_metadata_executor(state.memory_lookup)
    authority_repository = getattr(state, "authority_repository", None)
    if authority_repository is not None:
        executors["authority"] = build_authority_executor(authority_repository)
    return executors
