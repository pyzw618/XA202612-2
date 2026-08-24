"""vNext canonical write and task-resume REST entry points.

These endpoints are the single production write path for events, working
state, episode snapshots and long-term Authority.  All other adapters
(MCP, CLI, SDK, agent replay) delegate to this contract rather than writing
repositories or indexes directly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from memoryhub.adapter.vnext_schemas import (
    APIError,
    APIErrorCode,
    ContextPayload,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    ResumeTaskResponse,
    WriteEventRequest,
    WriteEventResponse,
)
from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    EpisodeEventContract,
    EpisodeSnapshot,
    LongTermEnvelope,
    MemoryEventContract,
    WorkingPatch,
    WorkingSnapshot,
)

router = APIRouter(prefix="/api/memory/vnext", tags=["memory-vnext"])


MemoryHubTenantHeader = ...  # placeholder removed; use Header(...) inline


def _canonical_write_service(request: Request) -> CanonicalWriteService:
    service = getattr(request.app.state, "canonical_write_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "canonical_write.service_unavailable"},
        )
    return service


def _tenant_user(
    request: Request,
    tenant_id: str = Header(..., alias="X-MemoryHub-Tenant", min_length=1),
    user_id: str = Header(..., alias="X-MemoryHub-User", min_length=1),
) -> tuple[str, str]:
    """Resolve the authenticated identity for a vNext request.

    The header resolver, when configured, overrides the supplied header so the
    request identity is bound to the application's authentication boundary.
    """
    resolver = getattr(request.app.state, "user_rule_identity_resolver", None)
    if callable(resolver):
        try:
            authenticated = resolver(request)
            if not isinstance(authenticated, str) or not authenticated.strip():
                raise ValueError
        except Exception:
            raise HTTPException(
                status_code=503,
                detail={"code": "user_rule.identity_unavailable"},
            ) from None
        return tenant_id, authenticated
    return tenant_id, user_id


def _canonical_error(
    exc: Exception, *, code: APIErrorCode, request_id: str, trace_id: str
) -> HTTPException:
    message = "internal canonical write error"
    details: dict[str, Any] = {}
    if isinstance(exc, (ValueError, KeyError)):
        message = str(exc)
        code = APIErrorCode.INVALID_REQUEST
    elif hasattr(exc, "code") and isinstance(exc.code, str):
        message = exc.code
        details["inner_code"] = exc.code
    return HTTPException(
        status_code=_error_status(code),
        detail=APIError(
            code=code,
            message=message,
            trace_id=trace_id,
            details={**details, "request_id": request_id},
        ).model_dump(mode="json"),
    )


def _error_status(code: APIErrorCode) -> int:
    mapping = {
        APIErrorCode.INVALID_REQUEST: 422,
        APIErrorCode.UNAUTHORIZED: 401,
        APIErrorCode.POLICY_REJECTED: 403,
        APIErrorCode.VERSION_CONFLICT: 409,
        APIErrorCode.IDEMPOTENCY_CONFLICT: 409,
        APIErrorCode.NOT_FOUND: 404,
        APIErrorCode.PARTIAL_RESULT: 200,
        APIErrorCode.SERVICE_UNAVAILABLE: 503,
        APIErrorCode.INTERNAL_ERROR: 500,
    }
    return mapping.get(code, 500)


@router.post("/events", response_model=WriteEventResponse)
async def write_canonical_events(
    req: WriteEventRequest,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> WriteEventResponse:
    """Single production write path for vNext events and task state.

    Each event is routed through ``CanonicalWriteService``; the response
    exposes the durable event/working/episode IDs produced by the same service.
    """
    tenant_id, user_id = identity
    service = _canonical_write_service(request)

    event_ids: list[str] = []
    working_versions: list[int] = []
    checkpoint_created = False
    episode_id: str | None = None
    candidate_ids: list[str] = []
    memory_ids: list[str] = []
    warnings: list[str] = []
    degraded = False
    last_trace_id = req.request_id
    for event_contract in req.events:
        if not isinstance(event_contract, MemoryEventContract):
            try:
                event_contract = MemoryEventContract.model_validate(
                    event_contract.model_dump(mode="json")
                )
            except ValidationError as exc:
                raise _canonical_error(
                    exc,
                    code=APIErrorCode.INVALID_REQUEST,
                    request_id=req.request_id,
                    trace_id=last_trace_id,
                ) from None

        # Bind request identity to the event if the caller did not provide it.
        event_data = event_contract.model_dump(mode="json")
        event_data.setdefault("tenant_id", tenant_id)
        event_data.setdefault("user_id", user_id)
        event_data.setdefault("idempotency_key", req.idempotency_key)
        event_data.setdefault("trace_id", req.request_id)
        if event_data.get("source_hash") in (None, ""):
            event_data["source_hash"] = _derive_source_hash(event_data)
        event_contract = MemoryEventContract.model_validate(event_data)
        last_trace_id = event_contract.trace_id

        # Optional working/episode/long-term payloads are carried in the event
        # payload under stable keys so a single endpoint can express the
        # canonical write without a separate DTO for every combination.
        working_snapshot = _pop_working_snapshot(event_data)
        working_patch = _pop_working_patch(event_data)
        episode_event = _pop_episode_event(event_data)
        episode_snapshot = _pop_episode_snapshot(event_data)
        checkpoint = _pop_checkpoint(event_data)
        long_term = _pop_long_term(event_data)

        # Re-validate after payload extraction so the event remains clean.
        event_contract = MemoryEventContract.model_validate(event_data)

        try:
            result = service.write(
                event_contract,
                working_snapshot=working_snapshot,
                working_patch=working_patch,
                working_state_id=working_snapshot.task_id if working_snapshot else None,
                episode_event=episode_event,
                episode_snapshot=episode_snapshot,
                checkpoint=checkpoint,
                long_term=long_term,
            )
        except Exception as exc:
            raise _canonical_error(
                exc,
                code=APIErrorCode.INTERNAL_ERROR,
                request_id=req.request_id,
                trace_id=req.trace_id,
            ) from None

        event_ids.append(result.event_id)
        last_trace_id = result.gateway.trace_id
        if result.working is not None:
            working_versions.append(result.working.version)
        if result.episode_snapshot is not None:
            checkpoint_created = True
            episode_id = result.episode_snapshot.snapshot.episode_id
        if result.episode_event is not None:
            episode_id = result.episode_event.episode_id
        if (
            result.episode_snapshot is None
            and result.episode_event is None
            and result.working is not None
        ):
            # Propagate the task_id for callers that only wrote working state.
            pass
        if result.long_term is not None:
            memory_ids.append(result.long_term.memory_id)

    if len(set(event_ids)) != len(event_ids):
        warnings.append("duplicate event ids collapsed by idempotency")

    return WriteEventResponse(
        request_id=req.request_id,
        trace_id=last_trace_id,
        event_ids=event_ids,
        working_state_version=max(working_versions) if working_versions else None,
        checkpoint_created=checkpoint_created,
        episode_id=episode_id,
        candidate_ids=candidate_ids,
        memory_ids=memory_ids,
        degraded=degraded,
        warnings=warnings,
    )


@router.get("/tasks/{task_id}/resume", response_model=ResumeTaskResponse)
async def resume_task(
    task_id: str,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
    resume_token: str = Header(default="", alias="X-MemoryHub-Resume-Token"),
    expected_snapshot_version: int | None = Header(
        default=None, alias="X-MemoryHub-Expected-Version"
    ),
) -> ResumeTaskResponse:
    """Resume a task by task_id, replaying events newer than the snapshot.

    The caller supplies the resume token from a previous checkpoint; stale
    resources and required revalidations are returned alongside the restored
    state.  Version conflicts are surfaced as 409 so the client can reconcile.
    """
    tenant_id, user_id = identity
    service = getattr(request.app.state, "episode_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "episode.service_unavailable"},
        )

    try:
        result = service.resume_by_task(
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            resume_token=resume_token,
            expected_snapshot_version=expected_snapshot_version,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "task.not_found", "message": str(exc)},
        ) from None
    except Exception as exc:
        from memoryhub.storage.vnext_repositories import VersionConflictError

        code = (
            APIErrorCode.VERSION_CONFLICT
            if isinstance(exc, VersionConflictError)
            else APIErrorCode.INTERNAL_ERROR
        )
        raise _canonical_error(
            exc,
            code=code,
            request_id=f"resume:{task_id}",
            trace_id=resume_token or "unknown",
        ) from None

    return ResumeTaskResponse(
        request_id=f"resume:{task_id}",
        trace_id=resume_token or result.resume_token,
        working_state=None,
        episode_snapshot=result.snapshot,
        restored_state=result.restored_state,
        stale_resources=result.stale_resources,
        required_revalidation=result.required_revalidation,
        resume_token=result.resume_token,
    )


def _derive_source_hash(event_data: dict[str, Any]) -> str:
    import hashlib
    import json

    payload = {
        "event_id": event_data.get("event_id", ""),
        "event_type": event_data.get("event_type", ""),
        "source_type": event_data.get("source_type", ""),
        "task_id": event_data.get("task_id", ""),
        "occurred_at": event_data.get("occurred_at", ""),
        "payload": event_data.get("payload", {}),
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _pop_working_snapshot(event_data: dict[str, Any]) -> WorkingSnapshot | None:
    raw = event_data.get("payload", {}).pop("_working_snapshot", None)
    if raw is None:
        return None
    try:
        return WorkingSnapshot.model_validate(raw)
    except ValidationError:
        return None


def _pop_working_patch(event_data: dict[str, Any]) -> WorkingPatch | None:
    raw = event_data.get("payload", {}).pop("_working_patch", None)
    if raw is None:
        return None
    try:
        return WorkingPatch.model_validate(raw)
    except ValidationError:
        return None


def _pop_episode_event(event_data: dict[str, Any]) -> EpisodeEventContract | None:
    raw = event_data.get("payload", {}).pop("_episode_event", None)
    if raw is None:
        return None
    try:
        return EpisodeEventContract.model_validate(raw)
    except ValidationError:
        return None


def _pop_episode_snapshot(event_data: dict[str, Any]) -> EpisodeSnapshot | None:
    raw = event_data.get("payload", {}).pop("_episode_snapshot", None)
    if raw is None:
        return None
    try:
        return EpisodeSnapshot.model_validate(raw)
    except ValidationError:
        return None


def _pop_checkpoint(event_data: dict[str, Any]) -> EpisodeSnapshot | None:
    raw = event_data.get("payload", {}).pop("_checkpoint", None)
    if raw is None:
        return None
    try:
        return EpisodeSnapshot.model_validate(raw)
    except ValidationError:
        return None


def _pop_long_term(event_data: dict[str, Any]) -> LongTermEnvelope | None:
    raw = event_data.get("payload", {}).pop("_long_term", None)
    if raw is None:
        return None
    try:
        return LongTermEnvelope.model_validate(raw)
    except ValidationError:
        return None


def _retrieval_service(request: Request) -> RetrievalService:
    service = getattr(request.app.state, "retrieval_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "retrieval.service_unavailable"},
        )
    return service


@router.post("/search", response_model=MemoryRetrievalResponse)
async def vnext_search(
    req: MemoryRetrievalRequest,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> MemoryRetrievalResponse:
    """Unified vNext search endpoint.

    All search entrypoints (legacy /search, /context, v2 search, MCP, CLI, SDK)
    eventually delegate to the same ``RetrievalService`` so results are identical.
    """
    tenant_id, user_id = identity
    service = _retrieval_service(request)
    vnext_request = req.model_copy(update={"tenant_id": tenant_id, "user_id": user_id})
    result = service.search(vnext_request)
    return result


@router.post("/context", response_model=ContextPayload)
async def vnext_context(
    req: MemoryRetrievalRequest,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> ContextPayload:
    """Unified vNext context endpoint returning the structured prompt payload."""
    tenant_id, user_id = identity
    service = _retrieval_service(request)
    vnext_request = req.model_copy(update={"tenant_id": tenant_id, "user_id": user_id})
    return service.context(vnext_request)


__all__ = ["router"]
