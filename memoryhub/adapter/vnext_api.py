"""vNext canonical write and task-resume REST entry points.

These endpoints are the single production write path for events, working
state, episode snapshots and long-term Authority.  All other adapters
(MCP, CLI, SDK, agent replay) delegate to this contract rather than writing
repositories or indexes directly.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from memoryhub.adapter.schemas import ExtractionTask
from memoryhub.adapter.vnext_schemas import (
    APIError,
    APIErrorCode,
    ContextPayload,
    DashboardRequest,
    DashboardResponse,
    DiagnosticRequest,
    DiagnosticResponse,
    ForgetRequest,
    ForgetResponse,
    FormationResponseStatus,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    ResumeTaskResponse,
    WriteEventRequest,
    WriteEventResponse,
)
from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.feedback_service import FeedbackEvent
from memoryhub.application.forget_service import ForgetService
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.application.rollout_service import RolloutGateError
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


class RolloutAdvanceRequest(BaseModel):
    level: int = Field(ge=0, le=100)


class RolloutObserveRequest(BaseModel):
    level: int = Field(ge=1, le=100)
    request_count: int = Field(ge=0)
    policy_leak_count: int = Field(default=0, ge=0)
    cross_tenant_count: int = Field(default=0, ge=0)
    forget_residual_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    window_id: str | None = Field(default=None, min_length=1, max_length=128)


class RolloutRollbackRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=256)
    target_level: int = Field(default=0, ge=0, le=100)


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
            )
        except Exception as exc:
            raise _canonical_error(
                exc,
                code=APIErrorCode.INTERNAL_ERROR,
                request_id=req.request_id,
                trace_id=last_trace_id,
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
        # The /events endpoint is the Formation path; Authority mutations are not
        # accepted here.  Long-term memory_ids only come from reflected/promoted
        # Candidates in authority mode, never from a hidden payload field.
        if result.reflection_task is not None:
            candidate_ids.extend(result.reflection_task.candidate_ids)
            memory_ids.extend(result.reflection_task.memory_ids)

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
        formation_status=(
            FormationResponseStatus.AUTHORITY_PROMOTED
            if memory_ids
            else FormationResponseStatus.CANDIDATE_STAGED
            if candidate_ids
            else FormationResponseStatus.REFLECTION_PENDING
        ),
    )


@router.get("/tasks/{task_id}", response_model=ExtractionTask)
async def formation_task_status(
    task_id: str,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> ExtractionTask:
    """Return the owner-bound Formation result of an extraction task."""

    tenant_id, user_id = identity
    repository = getattr(request.app.state, "extraction_task_repo", None)
    if repository is None:
        raise HTTPException(status_code=503, detail={"code": "formation.task_unavailable"})
    task = repository.get(task_id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"code": "formation.task_not_found"})
    if task.tenant_id and task.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail={"code": "formation.task_not_found"})
    return task


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
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
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


def _forget_service(request: Request) -> ForgetService:
    service = getattr(request.app.state, "forget_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "forget.service_unavailable"})
    return service


def _admin_authorized(request: Request, admin: str | None) -> bool:
    authorizer = getattr(request.app.state, "management_authorizer", None)
    if callable(authorizer):
        return bool(authorizer(request))
    return str(admin or "").strip().lower() in {"1", "true", "admin", "diagnostic"}


@router.post("/forget", response_model=ForgetResponse)
async def vnext_forget(
    req: ForgetRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
) -> ForgetResponse:
    tenant_id, user_id = _tenant_user(request, tenant_id=req.tenant_id, user_id=req.user_id)
    if tenant_id != req.tenant_id or user_id != req.user_id:
        raise HTTPException(status_code=401, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    try:
        result = _forget_service(request).execute(
            req,
            actor_id=user_id,
            high_risk_authorized=_admin_authorized(request, x_memoryhub_admin),
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": APIErrorCode.UNAUTHORIZED.value, "message": str(exc)},
        ) from exc
    return result.response


@router.get("/forget/{record_id}", response_model=ForgetResponse)
async def vnext_forget_status(
    record_id: str, request: Request, identity: tuple[str, str] = Depends(_tenant_user)
) -> ForgetResponse:
    found = _forget_service(request).get(record_id, tenant_id=identity[0], user_id=identity[1])
    if found is None:
        raise HTTPException(status_code=404, detail={"code": APIErrorCode.NOT_FOUND.value})
    return found.response


@router.get("/forget", response_model=list[ForgetResponse])
async def vnext_forget_history(
    request: Request, identity: tuple[str, str] = Depends(_tenant_user)
) -> list[ForgetResponse]:
    return [
        item.response
        for item in _forget_service(request).list(tenant_id=identity[0], user_id=identity[1])
    ]


@router.post("/diagnostics", response_model=DiagnosticResponse)
async def vnext_diagnostics(
    req: DiagnosticRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
) -> DiagnosticResponse:
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    tenant_id, user_id = _tenant_user(request, tenant_id=req.tenant_id, user_id=req.user_id)
    if (tenant_id, user_id) != (req.tenant_id, req.user_id):
        raise HTTPException(status_code=401, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    service = getattr(request.app.state, "diagnostic_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail={"code": APIErrorCode.SERVICE_UNAVAILABLE.value}
        )
    items = service.inspect(
        target_type=req.target_type,
        target_id=req.target_id,
        tenant_id=req.tenant_id,
        user_id=req.user_id,
        include_sensitive=req.include_sensitive,
        actor_id=x_memoryhub_admin or req.user_id,
    )
    return DiagnosticResponse(
        request_id=req.request_id,
        trace_id=req.request_id,
        target_type=req.target_type,
        target_id=req.target_id,
        items=items,
        redacted=True,
    )


@router.post("/dashboard/{view}", response_model=DashboardResponse)
async def vnext_dashboard(
    view: str,
    req: DashboardRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
) -> DashboardResponse:
    """Return a management-audited, default-redacted dashboard projection."""
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    tenant_id, user_id = _tenant_user(request, tenant_id=req.tenant_id, user_id=req.user_id)
    if (tenant_id, user_id) != (req.tenant_id, req.user_id):
        raise HTTPException(status_code=401, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail={"code": APIErrorCode.SERVICE_UNAVAILABLE.value}
        )
    try:
        data = service.view(
            view,
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=user_id,
            audit_actor_id=x_memoryhub_admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": str(exc)}) from exc
    return DashboardResponse(
        request_id=req.request_id, trace_id=req.request_id, view=view, data=data, redacted=True
    )


@router.get("/rollout")
async def rollout_status(
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
):
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    controller = getattr(request.app.state, "rollout_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    return controller.snapshot()


@router.post("/rollout/advance")
async def advance_rollout(
    body: RolloutAdvanceRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
):
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    controller = getattr(request.app.state, "rollout_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    try:
        return asdict(controller.advance(body.level))
    except RolloutGateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "rollout.gate_failed", "message": str(exc)},
        ) from exc


@router.post("/rollout/observe")
async def observe_rollout(
    body: RolloutObserveRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
):
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    controller = getattr(request.app.state, "rollout_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    try:
        return asdict(
            controller.observe(
                body.level,
                request_count=body.request_count,
                policy_leak_count=body.policy_leak_count,
                cross_tenant_count=body.cross_tenant_count,
                forget_residual_count=body.forget_residual_count,
                error_count=body.error_count,
                window_id=body.window_id,
            )
        )
    except RolloutGateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "rollout.observation_rejected", "message": str(exc)},
        ) from exc


@router.post("/rollout/rollback")
async def rollback_rollout(
    body: RolloutRollbackRequest,
    request: Request,
    x_memoryhub_admin: str | None = Header(default=None, alias="X-MemoryHub-Admin"),
):
    if not _admin_authorized(request, x_memoryhub_admin):
        raise HTTPException(status_code=403, detail={"code": APIErrorCode.UNAUTHORIZED.value})
    controller = getattr(request.app.state, "rollout_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    try:
        return asdict(
            controller.rollback(reason=body.reason, target_level=body.target_level)
        )
    except RolloutGateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "rollout.rollback_failed", "message": str(exc)},
        ) from exc


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
    rollout = getattr(request.app.state, "rollout_read_service", None)
    if rollout is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    vnext_request = req.model_copy(update={"tenant_id": tenant_id, "user_id": user_id})
    from memoryhub.adapter.api import _legacy_search_response

    selected = rollout.read(
        vnext_request,
        legacy_reader=lambda _request: _legacy_search_response(
            _legacy_request(vnext_request), request
        ),
        vnext_reader=lambda value: service.search(value),
    )
    if isinstance(selected.response, MemoryRetrievalResponse):
        return selected.response
    return MemoryRetrievalResponse.from_legacy_search_response(
        selected.response, request_id=vnext_request.request_id,
        tenant_id=tenant_id, user_id=user_id,
    )


@router.post("/context", response_model=ContextPayload)
async def vnext_context(
    req: MemoryRetrievalRequest,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> ContextPayload:
    """Unified vNext context endpoint returning the structured prompt payload."""
    tenant_id, user_id = identity
    service = _retrieval_service(request)
    rollout = getattr(request.app.state, "rollout_read_service", None)
    if rollout is None:
        raise HTTPException(status_code=503, detail={"code": "rollout.service_unavailable"})
    vnext_request = req.model_copy(update={"tenant_id": tenant_id, "user_id": user_id})
    from memoryhub.adapter.api import _legacy_context_response

    selected = rollout.read(
        vnext_request,
        legacy_reader=lambda _request: _legacy_context_response(
            _legacy_request(vnext_request), request
        ),
        vnext_reader=lambda value: service.context(value),
    )
    if isinstance(selected.response, ContextPayload):
        return selected.response
    context_text, _search = selected.response
    return ContextPayload(rendered_context=context_text)


@router.post("/feedback")
async def vnext_feedback(
    req: FeedbackEvent,
    request: Request,
    identity: tuple[str, str] = Depends(_tenant_user),
) -> dict[str, object]:
    """Record attributed usage/outcome feedback through the vNext service."""
    tenant_id, user_id = identity
    service = _retrieval_service(request)
    event = req.model_copy(update={"tenant_id": tenant_id, "user_id": user_id})
    return service.record_feedback_event(event)


def _legacy_request(request: MemoryRetrievalRequest):
    from memoryhub.adapter.vnext_schemas import legacy_search_request_from_vnext

    return legacy_search_request_from_vnext(request)


__all__ = ["router"]
