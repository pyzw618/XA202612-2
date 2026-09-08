"""
REST API 路由定义 — Memory Adapter 标准接口

所有接口均通过 FastAPI 路由暴露，供 OS Agent 或前端调用。
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from memoryhub.adapter.schemas import (
    EvalReport,
    EventProcessingSummary,
    ExtractionTask,
    ExtractionTaskRunRequest,
    ExtractionTaskRunResponse,
    ExtractionTaskStatus,
    FeedbackRequest,
    ForgetRecord,
    ForgetRequest,
    ForgetResponse,
    KnowledgeMemory,
    Evidence,
    ManualConfig,
    MemoryEvent,
    MemoryStatus,
    PreferenceMemory,
    SafetyAction,
    SceneScope,
    SearchRequest,
    SearchResponse,
    SearchResult,
    WriteEventRequest,
    WriteEventResponse,
)
from memoryhub.adapter.user_rule_schemas import (
    CreateUserRuleRequest,
    UpdateUserRuleRequest,
    UserRuleErrorResponse,
    UserRuleResponse,
)
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.core.forget import MemoryForgetter
from memoryhub.core.forget.health import HealthCalculator
from memoryhub.core.safety.gate import SafetyGateError
from memoryhub.core.safety.memory_write import (
    GuardedMemoryWriteResult,
    MemoryWriteSafetyError,
    guard_memory_write,
)
from memoryhub.application.event_gateway import GatewayStatus
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.embedding import KylinEmbeddingError
from memoryhub.storage.vector_engine import MilvusEngineError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])
logger = logging.getLogger("uvicorn.error")


def _memory_service(request: Request) -> Any:
    service = getattr(request.app.state, "memory_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="memory service not initialized")
    return service


@router.get("/health")
async def health(request: Request):
    """检查 API 和 SQLite 存储是否可用。"""
    return _memory_service(request).health()


_USER_RULE_CODE = re.compile(r"^user_rule\.[a-z0-9_.-]+$")
_USER_RULE_RESPONSE_FIELDS = (
    "rule_id",
    "label",
    "kind",
    "effect",
    "case_sensitive",
    "replacement",
    "revision",
    "enabled",
    "deleted",
    "created_at",
    "updated_at",
)
_USER_RULE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": UserRuleErrorResponse},
    404: {"model": UserRuleErrorResponse},
    409: {"model": UserRuleErrorResponse},
    422: {"model": UserRuleErrorResponse},
    500: {"model": UserRuleErrorResponse},
    503: {"model": UserRuleErrorResponse},
}
MemoryHubUserHeader = Annotated[
    str,
    Header(
        alias="X-MemoryHub-User",
        min_length=1,
        max_length=128,
    ),
]


def _user_rule_http_error(code: str, status_code: int) -> HTTPException:
    """Build a stable error without retaining service exception context."""
    return HTTPException(status_code=status_code, detail={"code": code})


def _retrieval_http_error(exc: Exception) -> HTTPException:
    """把 Embedding/Milvus 超时或不可用异常映射为稳定的 HTTP 503/504。"""
    code = getattr(exc, "code", "retrieval.error")
    if not isinstance(code, str):
        code = "retrieval.error"

    is_timeout = isinstance(code, str) and (
        code in {"embedding.timeout", "milvus.timeout"}
        or code.startswith("embedding.timeout:")
        or code.startswith("milvus.timeout:")
    )
    # 其余 embedding./milvus. 开头的稳定错误统一视为后端不可用
    is_backend_error = isinstance(code, str) and (
        code.startswith("embedding.") or code.startswith("milvus.")
    )

    if is_timeout:
        return HTTPException(status_code=504, detail={"code": code})
    if is_backend_error:
        return HTTPException(status_code=503, detail={"code": code})
    return HTTPException(status_code=500, detail={"code": code})


def _user_rule_service(request: Request) -> Any:
    """Resolve the application-scoped service without a module-global singleton."""
    service = getattr(request.app.state, "user_rule_service", None)
    if service is None:
        code = getattr(
            request.app.state,
            "user_rule_service_error",
            "user_rule.service_unavailable",
        )
        if not isinstance(code, str) or _USER_RULE_CODE.fullmatch(code) is None:
            code = "user_rule.service_unavailable"
        raise _user_rule_http_error(code or "user_rule.service_unavailable", 503)
    return service


def _authenticated_user_id(request: Request, claimed_user_id: str) -> str:
    """Bind the caller-supplied header to an application authentication boundary."""
    resolver = getattr(request.app.state, "user_rule_identity_resolver", None)
    if not callable(resolver):
        raise _user_rule_http_error("user_rule.identity_unavailable", 503)
    try:
        authenticated_user_id = resolver(request)
        if (
            not isinstance(authenticated_user_id, str)
            or not authenticated_user_id.strip()
            or len(authenticated_user_id) > 128
        ):
            raise ValueError
        authenticated = authenticated_user_id.encode("utf-8")
        claimed = claimed_user_id.encode("utf-8")
    except Exception:
        raise _user_rule_http_error("user_rule.identity_unavailable", 503) from None
    if not hmac.compare_digest(authenticated, claimed):
        raise _user_rule_http_error("user_rule.identity_mismatch", 403)
    return authenticated_user_id


def _raise_user_rule_service_error(exc: Exception) -> None:
    """Translate only stable domain codes and never expose exception text."""
    candidate = getattr(exc, "code", "")
    code = (
        candidate
        if isinstance(candidate, str) and _USER_RULE_CODE.fullmatch(candidate)
        else "user_rule.internal_error"
    )
    if code == "user_rule.not_found":
        status_code = 404
    elif code in {"user_rule.conflict", "user_rule.limit_exceeded"}:
        status_code = 409
    elif code in {
        "user_rule.invalid_user_id",
        "user_rule.invalid_rule_id",
        "user_rule.invalid_matcher",
        "user_rule.invalid_label",
        "user_rule.invalid_case_sensitive",
        "user_rule.invalid_enabled",
        "user_rule.unsafe_regex",
        "user_rule.advanced_regex_disabled",
        "user_rule.invalid_kind",
        "user_rule.invalid_effect",
        "user_rule.invalid_revision",
        "user_rule.invalid_update",
        "user_rule.invalid_query",
    }:
        status_code = 422
    elif code in {
        "user_rule.service_unavailable",
        "user_rule.storage_error",
        "user_rule.key_unavailable",
        "user_rule.corrupt_record",
        "user_rule.integrity_error",
        "user_rule.key_mismatch",
        "user_rule.encryption_error",
        "user_rule.compile_error",
        "user_rule.detector_error",
    }:
        status_code = 503
    else:
        status_code = 500
    raise _user_rule_http_error(code, status_code) from None


def _user_rule_response(value: Any) -> UserRuleResponse:
    """Whitelist the safe view fields so matcher material can never be serialized."""
    try:
        if isinstance(value, Mapping):
            payload = {field: value[field] for field in _USER_RULE_RESPONSE_FIELDS}
        else:
            payload = {
                field: getattr(value, field) for field in _USER_RULE_RESPONSE_FIELDS
            }
        return UserRuleResponse.model_validate(payload)
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")


# ============================================================
# 用户自定义敏感信息规则
# ============================================================


@router.post(
    "/safety/user-rules",
    response_model=UserRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_USER_RULE_ERROR_RESPONSES,
    tags=["safety"],
)
def create_user_rule(
    req: CreateUserRuleRequest,
    request: Request,
    user_id: MemoryHubUserHeader,
) -> UserRuleResponse:
    """Create a write-only matcher for the authenticated local user."""
    user_id = _authenticated_user_id(request, user_id)
    service = _user_rule_service(request)
    try:
        value = service.create_rule(
            user_id,
            label=req.label,
            kind=req.kind.value,
            effect=req.effect.value,
            matcher=req.matcher.get_secret_value(),
            case_sensitive=req.case_sensitive,
            enabled=req.enabled,
        )
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")
    return _user_rule_response(value)


@router.get(
    "/safety/user-rules",
    response_model=list[UserRuleResponse],
    responses=_USER_RULE_ERROR_RESPONSES,
    tags=["safety"],
)
def list_user_rules(
    request: Request,
    user_id: MemoryHubUserHeader,
    include_deleted: bool = False,
) -> list[UserRuleResponse]:
    """List safe rule metadata; matchers are never returned."""
    user_id = _authenticated_user_id(request, user_id)
    service = _user_rule_service(request)
    try:
        values = service.list_rules(user_id, include_deleted=include_deleted)
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")
    return [_user_rule_response(value) for value in values]


@router.get(
    "/safety/user-rules/{rule_id}",
    response_model=UserRuleResponse,
    responses=_USER_RULE_ERROR_RESPONSES,
    tags=["safety"],
)
def get_user_rule(
    rule_id: str,
    request: Request,
    user_id: MemoryHubUserHeader,
) -> UserRuleResponse:
    """Return one rule only when it belongs to the header identity."""
    user_id = _authenticated_user_id(request, user_id)
    service = _user_rule_service(request)
    try:
        value = service.get_rule(user_id, rule_id)
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")
    return _user_rule_response(value)


@router.patch(
    "/safety/user-rules/{rule_id}",
    response_model=UserRuleResponse,
    responses=_USER_RULE_ERROR_RESPONSES,
    tags=["safety"],
)
def update_user_rule(
    rule_id: str,
    req: UpdateUserRuleRequest,
    request: Request,
    user_id: MemoryHubUserHeader,
) -> UserRuleResponse:
    """Update one rule with an expected revision to prevent lost updates."""
    user_id = _authenticated_user_id(request, user_id)
    updates: dict[str, object] = {}
    if req.label is not None:
        updates["label"] = req.label
    if req.kind is not None:
        updates["kind"] = req.kind.value
    if req.effect is not None:
        updates["effect"] = req.effect.value
    if req.matcher is not None:
        updates["matcher"] = req.matcher.get_secret_value()
    if req.case_sensitive is not None:
        updates["case_sensitive"] = req.case_sensitive
    if req.enabled is not None:
        updates["enabled"] = req.enabled

    service = _user_rule_service(request)
    try:
        value = service.update_rule(
            user_id,
            rule_id,
            expected_revision=req.expected_revision,
            **updates,
        )
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")
    return _user_rule_response(value)


@router.delete(
    "/safety/user-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_USER_RULE_ERROR_RESPONSES,
    tags=["safety"],
)
def delete_user_rule(
    rule_id: str,
    request: Request,
    user_id: MemoryHubUserHeader,
    expected_revision: Annotated[int, Query(ge=1)],
) -> Response:
    """Soft-delete one rule using optimistic concurrency."""
    user_id = _authenticated_user_id(request, user_id)
    service = _user_rule_service(request)
    try:
        service.delete_rule(
            user_id,
            rule_id,
            expected_revision=expected_revision,
        )
    except Exception as exc:
        _raise_user_rule_service_error(exc)
        raise AssertionError("unreachable")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 事件写入
# ============================================================


def _should_use_canonical_write(request: Request) -> bool:
    """Return True when legacy write entrypoints should route to vNext canonical write."""
    config = getattr(request.app.state, "config", None)
    canonical = getattr(request.app.state, "canonical_write_service", None)
    if canonical is None:
        return False
    if config is None:
        return True
    return getattr(config.vnext, "events_default", True)


def _to_memory_event_contract(
    event: MemoryEvent,
    *,
    tenant_id: str = "default",
    project_id: str = "",
    task_id: str = "",
    session_id: str = "",
) -> MemoryEventContract:
    """Build a vNext canonical event from a sanitized legacy MemoryEvent."""
    from datetime import datetime

    from memoryhub.adapter.schemas import _deep_thaw_json

    occurred = event.occurred_at or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(occurred, str):
        try:
            occurred = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        except ValueError:
            occurred = datetime.utcnow()

    payload = _deep_thaw_json(dict(event.payload or {}))
    if project_id:
        payload["project_id"] = project_id
    payload["text"] = event.text or payload.get("text", "")
    if event.tool_calls:
        payload["tool_calls"] = [tc.model_dump(mode="json") for tc in event.tool_calls]
    if event.quality is not None:
        payload["quality"] = event.quality.model_dump(mode="json")
    if event.turn_id:
        payload["turn_id"] = event.turn_id
    if event.scene or event.task_type:
        payload["scope"] = {
            "scene": event.scene or "",
            "task_type": event.task_type or "",
        }
    if event.redactions:
        payload["redactions"] = [str(r) for r in event.redactions]

    return MemoryEventContract(
        tenant_id=tenant_id,
        user_id=event.user_id or "default",
        event_id=event.event_id,
        event_type=event.event_type,
        source_type=(
            event.source_type.value
            if hasattr(event.source_type, "value")
            else str(event.source_type)
        ),
        task_id=task_id or str(payload.get("task_id") or "") or event.session_id or "default-task",
        session_id=session_id or event.session_id or "default-session",
        occurred_at=occurred,
        payload=payload,
        policy_action="ALLOW",
        source_hash=event.source_hash or "0" * 64,
        idempotency_key=event.event_id,
        trace_id=event.event_id,
    )


def _canonical_write_result_to_legacy(
    results: list,
) -> WriteEventResponse:
    """Adapt a list of CanonicalWriteResult to the legacy WriteEventResponse.

    Legacy semantics treat duplicate/idempotent events as rejected, while vNext
    CanonicalWriteService returns ``IDEMPOTENT``. Map IDEMPOTENT to rejected here
    so that existing REST contract tests remain stable.
    """
    accepted = 0
    rejected = 0
    event_ids: list[str] = []
    for result in results:
        status = getattr(result, "status", None)
        if status == GatewayStatus.COMMITTED:
            accepted += 1
            event_ids.append(getattr(result, "event_id", ""))
        else:
            rejected += 1
    return WriteEventResponse(
        accepted=accepted,
        rejected=rejected,
        event_ids=event_ids,
        extraction_failures=0,
        retry_tasks_enqueued=0,
        retry_queue_failures=0,
    )


def _buffer_short_term(st_repo, events: list[MemoryEvent], ttl_hours: float = 24.0) -> None:
    """Keep committed events in the short-term session buffer for tiered search."""
    from datetime import datetime, timedelta, timezone

    ttl = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    for event in events:
        st_repo.add(
            user_id=event.user_id or "default",
            session_id=event.session_id or "",
            event_id=event.event_id,
            source_type=(
                event.source_type.value
                if hasattr(event.source_type, "value")
                else str(event.source_type or "")
            ),
            text=event.text or "",
            payload=dict(event.payload or {}),
            scene=event.scene or "",
            task_type=event.task_type or "",
            ttl_until=ttl,
        )


def _canonical_write_events(
    events: list[MemoryEvent],
    request: Request,
) -> WriteEventResponse:
    """Route legacy events through vNext CanonicalWriteService and adapt the response.

    Committed events are also fed to the legacy event processor so that preference,
    knowledge and FACT extraction continue to populate the legacy memory stores
    visible to ``/api/memory/search`` and ``/api/memory/preferences``.
    """
    canonical = getattr(request.app.state, "canonical_write_service", None)
    if canonical is None:
        raise HTTPException(status_code=503, detail="canonical write service not initialized")
    results: list[Any] = []
    committed_events: list[MemoryEvent] = []
    for event in events:
        tenant_id = request.headers.get("X-MemoryHub-Tenant", event.user_id or "default")
        contract = _to_memory_event_contract(event, tenant_id=tenant_id)
        result = canonical.write(contract)
        results.append(result)
        if getattr(result, "status", None) == GatewayStatus.COMMITTED:
            committed_events.append(event)
    response = _canonical_write_result_to_legacy(results)

    # Mirror the legacy ingestion side-effects: keep committed events in the
    # short-term session buffer and trigger preference/knowledge extraction.
    st_repo = getattr(request.app.state, "short_term_repo", None)
    if st_repo is not None and committed_events:
        try:
            _buffer_short_term(st_repo, committed_events)
        except Exception:
            pass
    processor = getattr(request.app.state, "event_processor", None)
    if processor is not None and committed_events:
        try:
            processor.process(committed_events)
        except Exception:
            # Extraction failures must not break the event-write contract.
            pass
    return response


def _memory_index_text(memory: PreferenceMemory | KnowledgeMemory) -> str:
    """Build index text using the same contract as application startup."""
    if memory.memory_type == "knowledge":
        from memoryhub.core.memory_write import MemoryWriteService

        return MemoryWriteService.index_text(memory)
    return memory.text


def _memory_index_metadata(memory: PreferenceMemory | KnowledgeMemory) -> dict[str, Any]:
    scope = memory.scope.model_dump() if hasattr(memory.scope, "model_dump") else {}
    return {
        "memory_type": memory.memory_type,
        "user_id": memory.user_id,
        "content": _memory_index_text(memory),
        "confidence": memory.confidence,
        "status": (
            memory.status.value if hasattr(memory.status, "value") else str(memory.status)
        ),
        "scope": scope,
    }


def _sync_memory_index(request: Request, memory, *, remove: bool = False) -> None:
    """Synchronize runtime lookup, vector index, BM25 index, and search cache."""
    state = request.app.state
    write_service = getattr(state, "memory_write_service", None)
    if write_service is not None:
        write_service.sync_memory(memory, remove=remove)
        return
    memory_id = memory.memory_id
    vector_store = getattr(state, "vector_store", None)
    vector_engine = getattr(state, "vector_engine", None)
    keyword_search = getattr(state, "keyword_search", None)
    memory_lookup = getattr(state, "memory_lookup", None)
    cache = getattr(state, "search_cache", None)

    if remove:
        if vector_store is not None:
            vector_store.delete(memory_id)
            vector_store.save()
        if vector_engine is not None:
            vector_engine.delete(memory_id)
        if keyword_search is not None:
            keyword_search.delete(memory_id)
        if memory_lookup is not None:
            memory_lookup.pop(memory_id, None)
    else:
        text = _memory_index_text(memory)
        metadata = _memory_index_metadata(memory)
        embedding_client = getattr(state, "embedding_client", None)
        if (vector_store is not None or vector_engine is not None) and embedding_client is None:
            raise RuntimeError("embedding client not initialized")
        if vector_store is not None:
            vector_store.update(memory_id, embedding_client.embed(text))
            vector_store.save()
        if vector_engine is not None:
            vector_engine.insert(
                memory_id, text, embedding_client.embed(text), metadata=metadata
            )
        if keyword_search is not None:
            keyword_search.update(
                memory_id, text, json.dumps(metadata, ensure_ascii=False)
            )
        if memory_lookup is not None:
            memory_lookup[memory_id] = memory

    # A write can turn a prior cache miss into a hit, so clear all query entries.
    if cache is not None:
        cache.clear()


@router.post("/events", response_model=WriteEventResponse)
async def write_events(req: WriteEventRequest, request: Request):
    """
    写入多源事件数据

    数据流: OS Agent → write_events → vNext CanonicalWriteService (默认)
            → EventGateway → 事件库 → Formation Worker

    参数:
        req.events: MemoryEvent 列表

    返回:
        accepted: 成功接收的事件数
        rejected: 被拒绝的事件数（质量/安全过滤）
        event_ids: 接受的事件 ID 列表
    """
    try:
        return _canonical_write_events(req.events, request)
    except HTTPException:
        raise
    except Exception:
        logger.exception("event ingestion failed")
        raise HTTPException(status_code=503, detail="event ingestion failed") from None


# ============================================================
# 多源接入（REFACTOR_PLAN_V2 §4.1 赛题要求 1）
# ============================================================


class ToolResultSourceRequest(BaseModel):
    """工具执行结果源接入请求（原始结果 → 结构化 MemoryEvent）。"""

    tool_name: str
    result: dict


@router.post("/sources/tool_result", status_code=200)
async def ingest_tool_result(req: ToolResultSourceRequest, request: Request):
    """把一次工具执行结果经源适配层结构化为 MemoryEvent 并进入统一接收链。

    Data flow: OS Agent 工具轨迹 → /sources/tool_result → ToolResultAdapter
            → MemoryEvent(TOOL_RESULT) → event_ingestion_service.ingest
            → Cleaner/Normalizer/QualityScorer/SafetyGate → 偏好/知识/FACT 抽取
    """
    from memoryhub.core.ingestion.adapters import ToolResultAdapter

    try:
        event = ToolResultAdapter().to_event(req.tool_name, req.result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid tool result: {exc}") from None

    response = _canonical_write_events([event], request)
    return {
        "accepted": response.accepted,
        "rejected": response.rejected,
        "event_ids": response.event_ids,
        "event_id": event.event_id,
    }


class BehaviorSourceRequest(BaseModel):
    """用户行为源接入请求（行为记录 → USER_BEHAVIOR MemoryEvent）。"""

    user_id: str = "default"
    behavior_type: str = "message"  # selection / correction / confirm / message / cancel
    behavior: dict


class ConfigSourceRequest(BaseModel):
    """手动配置源接入请求（配置修改 → 版本化 ManualConfig + MANUAL_CONFIG 事件）。"""

    user_id: str = "default"
    config_id: str = ""  # 缺省时首次生成；再次提交沿用同一 config_id 形成版本链
    config_type: str = "general"  # output_style / safety_policy / general
    payload: dict
    scope: SceneScope = SceneScope()
    previous: ManualConfig | None = None  # 同 config 上一版本，用于构建版本链


@router.post("/sources/behavior", status_code=200)
async def ingest_behavior(req: BehaviorSourceRequest, request: Request):
    """把一次用户行为（选中项/纠错/确认/消息）经行为适配器进入统一接收链。

    Data flow: 用户行为序列 → /sources/behavior → BehaviorAdapter
            → MemoryEvent(USER_BEHAVIOR, behavior_type=...) → event_ingestion_service.ingest
    """
    from memoryhub.core.ingestion.adapters import BehaviorAdapter

    try:
        event = BehaviorAdapter().to_event(
            req.behavior, behavior_type=req.behavior_type, user_id=req.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid behavior: {exc}") from None

    response = _canonical_write_events([event], request)
    return {
        "accepted": response.accepted,
        "rejected": response.rejected,
        "event_ids": response.event_ids,
        "event_id": event.event_id,
    }


@router.post("/sources/config", status_code=200)
async def ingest_manual_config(req: ConfigSourceRequest, request: Request):
    """把一次手动配置修改经配置适配器版本化后进入统一接收链。

    Data flow: 手动配置 → /sources/config → ConfigAdapter
            → ManualConfig（config_id 不变，version 递增）→ MANUAL_CONFIG 事件
            → event_ingestion_service.ingest → 偏好抽取（source 强因子 0.95）
    返回 ``manual_config``（含 config_id/version/版本链），供"配置版本混乱"回溯。
    """
    from memoryhub.core.ingestion.adapters import ConfigAdapter

    try:
        adapter = ConfigAdapter()
        config = adapter.to_manual_config(
            user_id=req.user_id,
            config_type=req.config_type,
            payload=req.payload,
            previous=req.previous,
            scope=req.scope,
            config_id=req.config_id,
        )
        event = adapter.to_event(config, previous=req.previous)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid config: {exc}") from None

    response = _canonical_write_events([event], request)
    return {
        "accepted": response.accepted,
        "rejected": response.rejected,
        "event_ids": response.event_ids,
        "event_id": event.event_id,
        "manual_config": config.model_dump(mode="json"),
    }


# ============================================================
# 抽取任务与死信管理
# ============================================================



# ============================================================
# Facts management
# ============================================================

def _fact_memory_to_dict(memory: KnowledgeMemory) -> dict:
    """knowledge(FACT) → fact 风格响应（/facts 兼容转发，REFACTOR_PLAN_V2 §4.8.8）。"""
    scope = getattr(memory, "scope", None)
    project_id = getattr(memory, "project_id", "") or ""
    scope_name = "project" if project_id else "global"
    return {
        "fact_id": memory.memory_id,
        "memory_id": memory.memory_id,
        "user_id": memory.user_id,
        "subject": memory.subject,
        "predicate": memory.predicate,
        "object_value": memory.object_value,
        "object_type": memory.object_type,
        "source_text": memory.content,
        "source_id": "",
        "scope": scope_name,
        "project_id": project_id or None,
        "access_count_30d": memory.access_count_30d,
        "confidence": memory.confidence,
        "status": (
            memory.status.value if hasattr(memory.status, "value") else str(memory.status)
        ),
        "version": memory.version,
        "memory_type": "fact",
    }


def _fact_knowledge_lookup(request: Request, fact_id: str, user_id: str, project_id: str = ""):
    """knowledge(FACT) 单一来源定位（legacy Fact 体系已删除，REFACTOR_PLAN_V2 §4.8.8）。"""
    know_repo = getattr(request.app.state, "know_repo", None)
    if know_repo is None:
        return None
    memory = know_repo.get_by_id(fact_id)
    if memory is not None and memory.user_id == user_id and (not project_id or memory.project_id == project_id) and (
        getattr(memory.knowledge_type, "value", str(memory.knowledge_type)) == "fact"
    ):
        return memory
    return None


@router.get("/facts")
async def list_facts(
    request: Request,
    user_id: str = "default",
    status: str | None = "active",
    limit: int = Query(default=100, ge=1, le=500),
    project_id: str = "",
):
    """FACT 列表：纯 knowledge(FACT) 单一来源（legacy facts 已并入知识，§4.8.8）。

    status 约定：空/"active" → 仅活跃；"all" → 全部状态（前端"全部"筛选用）。
    """
    know_repo = getattr(request.app.state, "know_repo", None)
    if know_repo is None:
        return []
    if status == "all":
        rows: list[KnowledgeMemory] = []
        for s in ("active", "pending", "archived", "deleted"):
            rows.extend(know_repo.get_by_type(user_id, knowledge_type="fact", status=s))
    else:
        rows = know_repo.get_by_type(user_id, knowledge_type="fact", status=status or "active")
    if project_id:
        rows = [m for m in rows if m.project_id == project_id]
    return [_fact_memory_to_dict(m) for m in rows][:limit]

@router.get("/facts/conflicts")
async def list_fact_conflicts(
    request: Request,
    user_id: str = "default",
    limit: int = Query(default=100, ge=1, le=500),
):
    """FACT 冲突：knowledge 冲突（legacy fact 冲突已并入知识冲突链，§4.8.5）。"""
    out: list[dict] = []
    conflict_repo = getattr(request.app.state, "conflict_repo", None)
    if conflict_repo is not None:
        out.extend(
            r for r in conflict_repo.list_all(user_id=user_id)
            if getattr(r, "memory_type", "") == "knowledge"
        )
    return out[:limit]

@router.get("/facts/{fact_id}")
async def get_fact(fact_id: str, request: Request, user_id: str = "default", project_id: str = ""):
    memory = _fact_knowledge_lookup(request, fact_id, user_id, project_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return _fact_memory_to_dict(memory)

@router.get("/facts/{fact_id}/evidence")
async def get_fact_evidence(fact_id: str, request: Request, user_id: str = "default", project_id: str = ""):
    memory = _fact_knowledge_lookup(request, fact_id, user_id, project_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return [e.model_dump(mode="json") for e in memory.evidences]

@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request, user_id: str = "default", project_id: str = ""):
    memory = _fact_knowledge_lookup(request, fact_id, user_id, project_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="fact not found")
    write_service = getattr(request.app.state, "memory_write_service", None)
    if write_service is None:
        raise HTTPException(status_code=503, detail="memory write service not initialized")
    memory.status = MemoryStatus.DELETED
    write_service.sync_memory(memory, remove=True)
    return {"deleted": True, "fact_id": fact_id}
@router.post("/admin/reconcile")
async def reconcile_memory_indexes(request: Request):
    """
    SQLite ↔ Milvus 漂移对账（手动触发）。

    正向补写 pending 的 active 记录，反向删除 pending 的非 active 向量。
    """
    service = getattr(request.app.state, "sync_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="memory sync service not initialized")
    return service.reconcile()


@router.get("/extraction/tasks/metrics")
async def extraction_retry_metrics(request: Request):
    task = getattr(request.app.state, "extraction_retry_task", None)
    if task is None:
        raise HTTPException(status_code=503, detail="extraction retry task not initialized")
    metrics = task.metrics
    return {
        "total_runs": metrics.total_runs,
        "total_claimed": metrics.total_claimed,
        "total_succeeded": metrics.total_succeeded,
        "total_retried": metrics.total_retried,
        "total_dead_lettered": metrics.total_dead_lettered,
        "last_run_at": metrics.last_run_at,
        "last_duration_ms": metrics.last_duration_ms,
        "last_error_code": metrics.last_error_code,
    }

@router.get("/extraction/tasks", response_model=list[ExtractionTask])
async def list_extraction_tasks(
    request: Request,
    user_id: str = "default",
    status: ExtractionTaskStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    """按 owner 查看抽取重试、成功和死信状态。"""
    repo = getattr(request.app.state, "extraction_task_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="extraction task repository not initialized")
    return repo.list(
        user_id=user_id,
        status=status.value if status is not None else None,
        limit=limit,
    )


@router.post("/extraction/tasks/run", response_model=ExtractionTaskRunResponse)
async def run_extraction_tasks(req: ExtractionTaskRunRequest, request: Request):
    """显式执行当前用户到期任务；不启动测试外的隐式后台线程。"""
    service = getattr(request.app.state, "extraction_retry_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="extraction retry service not initialized")
    result = service.run_due(user_id=req.user_id, limit=req.limit)
    return ExtractionTaskRunResponse(
        claimed=result.claimed,
        succeeded=result.succeeded,
        retried=result.retried,
        dead_lettered=result.dead_lettered,
    )


@router.post("/extraction/tasks/{task_id}/retry", response_model=ExtractionTask)
async def retry_dead_extraction_task(
    task_id: str, request: Request, user_id: str = "default"
):
    """由 owner 将一条死信重置为到期重试任务。"""
    repo = getattr(request.app.state, "extraction_task_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="extraction task repository not initialized")
    task = repo.retry_dead(task_id, user_id=user_id)
    if task is None:
        raise HTTPException(status_code=404, detail="extraction task not found")
    return task


# ============================================================
# 记忆检索
# ============================================================


def _search_request_to_vnext(
    req: SearchRequest,
    *,
    tenant_id: str = "default",
    request_id: str = "",
) -> MemoryRetrievalRequest:
    """Convert a legacy SearchRequest to the vNext retrieval contract."""
    return MemoryRetrievalRequest.from_legacy_search_request(
        req,
        tenant_id=tenant_id,
        request_id=request_id,
    )


def _record_search_access(request: Request, response: SearchResponse) -> None:
    """Feed successful retrievals back into lifecycle access statistics."""
    state = request.app.state
    pref_repo = getattr(state, "pref_repo", None)
    know_repo = getattr(state, "know_repo", None)
    seen: set[str] = set()
    for memory in [*response.preferences, *response.knowledge]:
        if memory.memory_id in seen:
            continue
        seen.add(memory.memory_id)
        repo = know_repo if memory.memory_type == "knowledge" else pref_repo
        if repo is not None:
            repo.record_access(memory.memory_id, user_id=memory.user_id)


def _apply_tiered_cascade(
    request: Request, req: SearchRequest, response: SearchResponse
) -> SearchResponse:
    """记忆分层检索级联（REFACTOR_PLAN_V2 §4.4.3 / I-4）。

    带 ``session_id`` 时，先在会话短期工作记忆（short_term_memory）注入当前会话
    上下文，再取近期中期情景（mid_term_memory），最后与长期混合检索结果一起按
    level 加权融合；每条结果标注 ``memory_level``，让 Agent 知道"这是本会话刚发生
    的，还是历史沉淀的"。纯短期/中期结果不出现在全局长期检索中（level=long 过滤）。

    ``req.level`` 显式指定时只返回该层记忆（short / mid / long）：long 为纯长期
    混合检索结果；short 仅会话工作记忆；mid 仅中期情景。
    """
    level = (req.level or "").strip().lower()
    state = request.app.state
    st_repo = getattr(state, "short_term_repo", None)
    mt_repo = getattr(state, "mid_term_repo", None)

    # ① 会话短期工作记忆
    short_results: list[SearchResult] = []
    if level in ("", "short") and st_repo and req.session_id:
        short_rows = st_repo.list_by_session(req.user_id, req.session_id)
        short_results = [
            SearchResult(
                memory_id=row["id"],
                memory_type=str(row.get("source_type", "")),
                content=row.get("text") or "",
                score=0.9,  # 工作记忆与当前会话直接相关，短档相对高权重
                source="short-term",
                metadata={
                    "session_id": row.get("session_id", ""),
                    "scene": row.get("scene", ""),
                    "task_type": row.get("task_type", ""),
                    "user_id": row.get("user_id", ""),
                },
                memory_level="short",
            )
            for row in short_rows
            if row.get("text")
        ]

    # ② 近期中期情景
    mid_results: list[SearchResult] = []
    if level in ("", "mid") and mt_repo:
        mid_rows = mt_repo.list_active(user_id=req.user_id)
        mid_results = [
            SearchResult(
                memory_id=row["episode_id"],
                memory_type="episode",
                content=row.get("trajectory_summary") or row.get("summary") or "",
                score=0.7,  # 中期情景为近期相关经验，中档权重
                source="mid-term",
                metadata={
                    "scene": row.get("scene", ""),
                    "task_type": row.get("task_type", ""),
                    "user_id": row.get("user_id", ""),
                    "outcome": row.get("outcome", ""),
                },
                memory_level="mid",
            )
            for row in mid_rows
            if (row.get("trajectory_summary") or row.get("summary"))
        ]

    # ③ 长期记忆已由 retriever 标注 memory_level=long；按 level 过滤后合并。
    #    level=short/mid 时只返回该层（不掺入长期）；level=long/空 时合并长期。
    if level in ("short", "mid"):
        long_results: list[SearchResult] = []
    else:
        long_results = [
            r for r in response.results
            if r.memory_id not in {
                s.memory_id for s in [*short_results, *mid_results]
            }
        ]

    merged = [*short_results, *mid_results, *long_results]
    if merged:
        merged.sort(key=lambda r: (r.score, -len(r.memory_id)), reverse=True)
        merged = merged[: req.top_k]

    response.results = merged
    response.total_count = len(merged)
    # 保持偏好/知识列表：仅当来自长期记忆时归入（短期/中期已作为纯内容注入）
    if short_results or mid_results:
        response.preferences = [
            p for p in response.preferences
            if p.memory_id not in {s.memory_id for s in [*short_results, *mid_results]}
        ]
        response.knowledge = [
            k for k in response.knowledge
            if k.memory_id not in {s.memory_id for s in [*short_results, *mid_results]}
        ]
    return response


def _legacy_search_response(req: SearchRequest, request: Request) -> SearchResponse:
    """Execute the pre-vNext reader; rollout code decides if it is returned."""
    retriever = getattr(request.app.state, "retriever", None)
    memory = getattr(request.app.state, "memory_service", None)
    if retriever is None:
        if memory is None:
            raise HTTPException(status_code=503, detail="retrieval service not initialized")
        return memory.search(req)
    response = retriever.search(req)
    if response.total_count == 0 and memory is not None:
        fallback = memory.search(req)
        if fallback.total_count:
            response = fallback
    return response


def _legacy_context_response(req: SearchRequest, request: Request) -> tuple[str, SearchResponse]:
    """Render context from the same legacy search result used by dual-read."""
    memory = getattr(request.app.state, "memory_service", None)
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None and memory is not None:
        return memory.context(req)
    response = _legacy_search_response(req, request)
    if not response.preferences and not response.knowledge:
        return "", response
    lines: list[str] = []
    if response.preferences:
        lines.append("## 用户偏好")
        lines.extend(
            f"- {item.text} (置信度: {item.confidence:.2f})"
            for item in response.preferences
        )
    if response.knowledge:
        lines.append("## 相关知识")
        lines.extend(f"- {item.name}: {item.content}" for item in response.knowledge)
    return "\n".join(lines), response


@router.post("/search", response_model=SearchResponse)
async def search_memory(req: SearchRequest, request: Request):
    """
    混合检索偏好与知识记忆

    数据流: OS Agent → search_memory → vNext RetrievalService
            → (intent router → planner → channels → fusion → rerank → scope → budget)
            → 返回 Top-K

    参数:
        req.query: 检索查询文本
        req.context: 场景作用域过滤
        req.top_k: 返回结果数
        req.memory_types: 过滤记忆类型 ["preference", "knowledge"]
        req.min_confidence: 最低置信度阈值

    返回:
        preferences: 匹配的偏好记忆列表
        knowledge: 匹配的知识记忆列表
        latency_ms: 检索耗时
    """
    retrieval_service = getattr(request.app.state, "retrieval_service", None)
    rollout = getattr(request.app.state, "rollout_read_service", None)
    if retrieval_service is None or rollout is None:
        raise HTTPException(status_code=503, detail="retrieval service not initialized")
    try:
        vnext_req = _search_request_to_vnext(
            req,
            tenant_id=request.headers.get("X-MemoryHub-Tenant", req.user_id or "default"),
            request_id=f"legacy-search-{req.user_id}-{hash(req.query) & 0xFFFFFFFF:08x}",
        )
        selected = rollout.read(
            vnext_req,
            legacy_reader=lambda _request: _legacy_search_response(req, request),
            vnext_reader=lambda vnext_request: retrieval_service.search(vnext_request),
        )
        response = selected.response
        if hasattr(response, "to_legacy_search_response"):
            response = response.to_legacy_search_response()
        response.served = selected.served_by
        response = _apply_tiered_cascade(request, req, response)
        _record_search_access(request, response)
        return response
    except (KylinEmbeddingError, MilvusEngineError) as exc:
        raise _retrieval_http_error(exc) from None
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid search request") from None
    except Exception:
        # 不回显内部异常细节，避免泄露输入内容或实现信息
        raise HTTPException(status_code=500, detail="internal retrieval error") from None


@router.post("/context")
async def get_memory_context(req: SearchRequest, request: Request):
    """
    获取可直接拼接进 Agent 上下文的记忆摘要

    与 search_memory 类似，但返回格式为可直接注入 prompt 的文本。

    数据流: OS Agent → get_memory_context → vNext RetrievalService.context
            → 返回结构化 ContextPayload 的文本渲染
    """
    retrieval_service = getattr(request.app.state, "retrieval_service", None)
    rollout = getattr(request.app.state, "rollout_read_service", None)
    if retrieval_service is None or rollout is None:
        raise HTTPException(status_code=503, detail="retrieval service not initialized")

    def _format_context(context_text: str) -> dict[str, str]:
        # 同时兼容本地集成（context）与 MCP 集成（context_text）两种消费方
        return {"context": context_text, "context_text": context_text}

    try:
        vnext_req = _search_request_to_vnext(
            req,
            tenant_id=request.headers.get("X-MemoryHub-Tenant", req.user_id or "default"),
            request_id=f"legacy-context-{req.user_id}-{hash(req.query) & 0xFFFFFFFF:08x}",
        )
        selected = rollout.read(
            vnext_req,
            legacy_reader=lambda _request: _legacy_context_response(req, request),
            vnext_reader=lambda vnext_request: retrieval_service.context(vnext_request),
        )
        if hasattr(selected.response, "rendered_context"):
            result = _format_context(selected.response.rendered_context)
            result["served"] = selected.served_by
            return result
        context_text, search = selected.response
        _record_search_access(request, search)
        result = _format_context(context_text)
        result["served"] = selected.served_by
        return result
    except (KylinEmbeddingError, MilvusEngineError) as exc:
        raise _retrieval_http_error(exc) from None
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid search request") from None
    except Exception:
        raise HTTPException(status_code=500, detail="internal retrieval error") from None

# ============================================================
# 偏好管理
# ============================================================


@router.get("/preferences", response_model=list[PreferenceMemory])
async def list_preferences(
    request: Request,
    user_id: str = "default",
    scene: str = "",
    status: str = "active",
):
    """列出偏好记忆，支持按场景和状态过滤"""
    repo = getattr(request.app.state, "pref_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="preference repository not initialized")
    if scene:
        values = repo.get_by_scope(user_id, scene, "")
    else:
        values = repo.list_all(status=status, user_id=user_id)
    return values


@router.get("/preferences/{memory_id}", response_model=PreferenceMemory)
async def get_preference(memory_id: str, request: Request, user_id: str = "default"):
    """获取单条偏好记忆详情"""
    repo = getattr(request.app.state, "pref_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="preference repository not initialized")
    result = repo.get_by_id(memory_id)
    if result is None or result.user_id != user_id:
        raise HTTPException(status_code=404, detail="preference not found")
    return result


@router.get("/preferences/{memory_id}/versions", response_model=list[PreferenceMemory])
async def get_preference_versions(memory_id: str, request: Request):
    """获取偏好记忆的版本历史链"""
    repo = getattr(request.app.state, "pref_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="preference repository not initialized")
    return repo.get_version_chain(memory_id)


# ============================================================
# 知识管理
# ============================================================


@router.get("/knowledge", response_model=list[KnowledgeMemory])
async def list_knowledge(
    request: Request,
    user_id: str = "default",
    scene: str = "",
    knowledge_type: str = "",
    status: str = "active",
):
    """列出知识记忆，支持按类型、场景和状态过滤（状态过滤对前端待审查/归档/回收站页必需）"""
    repo = getattr(request.app.state, "know_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="knowledge repository not initialized")
    # 空串视为 active，保持向后兼容（避免 list_all 匹配到空状态返回空）
    status = status or "active"
    if scene:
        values = repo.get_by_scope(user_id, scene, "", status)
    elif knowledge_type:
        values = repo.get_by_type(user_id, knowledge_type, status)
    else:
        values = repo.list_all(status=status, user_id=user_id)
    return values


@router.get("/knowledge/{memory_id}", response_model=KnowledgeMemory)
async def get_knowledge(memory_id: str, request: Request, user_id: str = "default"):
    """获取单条知识记忆详情"""
    repo = getattr(request.app.state, "know_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="knowledge repository not initialized")
    result = repo.get_by_id(memory_id)
    if result is None or result.user_id != user_id:
        raise HTTPException(status_code=404, detail="knowledge not found")
    return result


# ============================================================
# 冲突管理
# ============================================================


@router.get("/conflicts")
async def list_conflicts(
    status: str = "pending",
    user_id: str = "default",
    page: int | None = Query(default=None, ge=1),
    size: int = Query(default=10, ge=1, le=200),
    request: Request = None,
):
    """列出冲突记录，支持按状态过滤。

    向后兼容：不传 page 时返回全部列表；传 page 时返回分页结构
    {"items": [...], "total": N, "page": P, "size": S}。
    """
    # 尝试访问冲突仓储，若不可用则返回空
    repo = getattr(request.app.state, "conflict_repo", None) if request else None
    if repo is None:
        return [] if page is None else {"items": [], "total": 0, "page": page, "size": size}
    values = repo.list_all(status, user_id=user_id)
    if page is None:
        return values
    total = len(values)
    start = (page - 1) * size
    return {
        "items": values[start : start + size],
        "total": total,
        "page": page,
        "size": size,
    }


class ResolveConflictRequest(BaseModel):
    user_id: str = "default"
    decision: str
    reason: str = ""
    result_id: str = ""


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, body: ResolveConflictRequest, request: Request):
    """
    手动解决待确认冲突

    数据流: 用户确认 → resolve_conflict → ConflictResolver.resolve
            → 更新记忆 → 记录 ConflictRecord
    """
    repo = getattr(request.app.state, "conflict_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="conflict repository not initialized")
    try:
        resolved = repo.resolve(
            conflict_id, body.decision, body.reason, body.result_id, user_id=body.user_id
        )
        if not resolved:
            raise HTTPException(status_code=404, detail="conflict not found")
        return {
            "status": "resolved",
            "conflict_id": conflict_id,
            "decision": body.decision,
            "result_id": body.result_id,
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(
            status_code=400, detail="invalid conflict resolution"
        ) from None


# ============================================================
# 用户反馈
# ============================================================


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request):
    """Apply feedback; free-text updates must pass the mandatory safety write gate."""
    pref_repo = getattr(request.app.state, "pref_repo", None)
    know_repo = getattr(request.app.state, "know_repo", None)
    if pref_repo is None and know_repo is None:
        raise HTTPException(status_code=503, detail="memory repository not initialized")

    memory = pref_repo.get_by_id(req.memory_id) if pref_repo is not None else None
    if memory is None and know_repo is not None:
        memory = know_repo.get_by_id(req.memory_id)
    if memory is None or memory.user_id != req.user_id:
        raise HTTPException(status_code=404, detail="memory not found")

    content_update = req.action == "update" and bool(req.feedback_text)
    if content_update:
        if memory.memory_type == "knowledge":
            memory.content = req.feedback_text
            memory.version = max(1, memory.version) + 1
        else:
            memory.text = req.feedback_text
    elif req.action == "confirm":
        # §4.9.2 反馈闭环：艾宾浩斯"复习强化"——刷新访问锚点、递增使用次数，
        # 使时间衰减曲线反弹并提升健康度；记忆越被使用越稳固。
        memory.access_count_30d = int(getattr(memory, "access_count_30d", 0) or 0) + 1
        memory.last_accessed_at = datetime.now(timezone.utc)
        if memory.memory_type == "knowledge":
            memory.total_count = int(getattr(memory, "total_count", 0) or 0) + 1
            memory.success_count = int(getattr(memory, "success_count", 0) or 0) + 1
        memory.health_score = HealthCalculator().calculate(memory)
    elif req.action == "reject":
        memory.status = MemoryStatus.ARCHIVED
        memory.health_score = 0.0

    write_service = getattr(request.app.state, "memory_write_service", None)

    def persist(selected_memory):
        nonlocal write_service
        if write_service is None:
            from memoryhub.core.memory_write import MemoryWriteService

            write_service = MemoryWriteService(
                pref_repo=pref_repo,
                know_repo=know_repo,
                vector_store=getattr(request.app.state, "vector_store", None),
                vector_engine=getattr(request.app.state, "vector_engine", None),
                keyword_search=getattr(request.app.state, "keyword_search", None),
                memory_lookup=getattr(request.app.state, "memory_lookup", None),
                search_cache=getattr(request.app.state, "search_cache", None),
                embedding_client=getattr(request.app.state, "embedding_client", None),
                # submit_feedback already passed its content mutation through
                # _guarded_memory_write before this fallback writer is invoked.
                safety_gate=None,
            )
        write_service.upsert_memory(selected_memory)
        return selected_memory.memory_id

    if content_update:
        result = _guarded_memory_write(
            request,
            memory,
            persist,
            operation="feedback_update",
        )
        return {
            "status": "ok",
            "action": req.action,
            "safety_action": result.action.value,
            "audit_id": result.audit_id,
        }

    persist(memory)
    return {"status": "ok", "action": req.action}


# ============================================================
# 记忆写入（显式写入入口）
# ============================================================

def _get_sync_service(request: Request):
    """从应用状态获取 MemorySyncService 实例。"""
    service = getattr(request.app.state, "sync_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="memory sync service not initialized")
    return service


def _get_safety_gate(request: Request):
    """Return the mandatory write gate; explicit writes fail closed without it."""
    gate = getattr(request.app.state, "safety_gate", None)
    if gate is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory safety gate unavailable",
        )
    return gate


def _guarded_memory_write(
    request: Request,
    memory: PreferenceMemory | KnowledgeMemory,
    sink,
    *,
    operation: str,
) -> GuardedMemoryWriteResult:
    """Run one content mutation through SafetyWriteGate before invoking its sink."""
    try:
        result = guard_memory_write(
            _get_safety_gate(request),
            memory,
            sink,
            operation=operation,
        )
    except HTTPException:
        raise
    except (MemoryWriteSafetyError, SafetyGateError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory safety gate failed",
        ) from None

    if result.action is SafetyAction.REVIEW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "memory.safety.review_required",
                "message": "Memory write requires safety review",
                "status": "review_required",
                "safety_action": result.action.value,
                "audit_id": result.audit_id,
            },
        )
    if result.action is SafetyAction.REJECT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "memory.safety.rejected",
                "message": "Memory write rejected by safety policy",
                "status": "rejected",
                "safety_action": result.action.value,
                "audit_id": result.audit_id,
            },
        )
    if result.memory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="memory safety gate failed",
        )
    return result


def _write_through_sync_service(sync_service, memory):
    sqlite_ok, memory_id = sync_service.index_memory(memory)
    if not sqlite_ok:
        raise RuntimeError("memory write failed")
    return memory_id


@router.post("/memories/preference")
async def write_preference_memory(
    req: PreferenceMemory,
    request: Request,
    sync_service=Depends(_get_sync_service),
):
    """
    显式写入/更新偏好记忆，并同步到 Milvus。

    数据流: PreferenceMemory → SafetyWriteGate → 安全副本 → SQLite → Embedding → Milvus
            → 标记 index_version → 失效检索缓存
    """
    result = _guarded_memory_write(
        request,
        req,
        lambda safe_memory: _write_through_sync_service(sync_service, safe_memory),
        operation="explicit_write",
    )
    return {
        "status": "ok",
        "memory_id": result.sink_result,
        "safety_action": result.action.value,
        "audit_id": result.audit_id,
    }


@router.post("/memories/knowledge")
async def write_knowledge_memory(
    req: KnowledgeMemory,
    request: Request,
    sync_service=Depends(_get_sync_service),
):
    """
    显式写入/更新知识记忆，并同步到 Milvus。

    数据流: KnowledgeMemory → SafetyWriteGate → 安全副本 → SQLite → Embedding → Milvus
            → 标记 index_version → 失效检索缓存
    """
    result = _guarded_memory_write(
        request,
        req,
        lambda safe_memory: _write_through_sync_service(sync_service, safe_memory),
        operation="explicit_write",
    )
    return {
        "status": "ok",
        "memory_id": result.sink_result,
        "safety_action": result.action.value,
        "audit_id": result.audit_id,
    }


# ============================================================
# 精准遗忘
# ============================================================


def _get_forgetter(request: Request) -> MemoryForgetter:
    """Build a forgetter with all currently initialized persistence and indexes."""
    state = request.app.state
    return MemoryForgetter(
        llm_client=getattr(state, "llm_client", None),
        storage=getattr(state, "db", None),
        vector_store=getattr(state, "vector_store", None),
        vector_engine=getattr(state, "vector_engine", None),
        cache=getattr(state, "search_cache", None),
        pref_repo=getattr(state, "pref_repo", None),
        know_repo=getattr(state, "know_repo", None),
        keyword_search=getattr(state, "keyword_search", None),
        memory_lookup=getattr(state, "memory_lookup", None),
        evidence_store=getattr(state, "evidence_store", None),
        conflict_repo=getattr(state, "conflict_repo", None),
        embedding_client=getattr(state, "embedding_client", None),
        short_term_repo=getattr(state, "short_term_repo", None),
        mid_term_repo=getattr(state, "mid_term_repo", None),
        forget_rule_service=getattr(state, "forget_rule_service", None),
    )


class ForgetPreviewResponse(BaseModel):
    """精准遗忘预览结果：只定位候选，不执行删除。"""

    user_id: str = "default"
    instruction: str = ""
    candidate_ids: list[str] = Field(default_factory=list)
    deleted_count: int = 0
    memory_type: str = "all"
    target_topic: str = ""


class FactProposeRequest(BaseModel):
    """手工提交事实候选（前端 demo / 竞争测试使用）。"""

    user_id: str = "default"
    source_id: str = ""
    scope_hint: str = "global"
    project_id: str | None = None
    evidence: str = ""
    triples: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/forget/preview", response_model=ForgetPreviewResponse)
async def preview_forget(
    req: ForgetRequest,
    request: Request,
    forgetter: MemoryForgetter = Depends(_get_forgetter),
) -> ForgetPreviewResponse:
    """预览精准遗忘：只定位候选记忆，不执行任何删除。"""
    intent = forgetter.parse_intent(req)
    candidate_ids = forgetter.locate_memories(intent, req)
    return ForgetPreviewResponse(
        user_id=req.user_id,
        instruction=req.instruction,
        candidate_ids=candidate_ids,
        deleted_count=0,
        memory_type=str(intent.get("memory_type", "all")),
        target_topic=str(intent.get("target_topic", "")),
    )


@router.get("/events/session/{session_id}")
async def list_session_events(session_id: str, request: Request):
    """列出指定会话的全部事件（供前端回放/会话历史使用）。"""
    repo = getattr(request.app.state, "event_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="event repository not initialized")
    events = repo.get_by_session(session_id)
    return [event.model_dump(mode="json") for event in events]


@router.post("/facts/propose")
async def propose_facts(req: FactProposeRequest, request: Request):
    """提交手工三元组，直接写入 knowledge(FACT)（legacy Fact 管线已删除，§4.8.8）。

    结构化确定性映射（不经 LLM）：subject/predicate/object → KnowledgeMemory(FACT)。
    返回 {"created": [...], "failed": [...]}：单条失败（校验不通过/写库异常/回读缺失）
    不影响其它条，failed 中逐条标注原因，不再静默假成功。
    """
    write_service = getattr(request.app.state, "memory_write_service", None)
    if write_service is None:
        raise HTTPException(status_code=503, detail="memory write service not initialized")
    from memoryhub.adapter.schemas import KnowledgeType, SceneScope, SourceType

    project_id = str(req.project_id or "").strip()
    if req.scope_hint not in {"global", "project"}:
        raise HTTPException(status_code=422, detail="scope_hint must be global or project")
    if req.scope_hint == "project" and not project_id:
        raise HTTPException(status_code=422, detail="project_id is required for project scope")
    if req.scope_hint == "global" and project_id:
        raise HTTPException(status_code=422, detail="project_id is only valid for project scope")

    know_repo = getattr(request.app.state, "know_repo", None)
    created: list[dict] = []
    failed: list[dict] = []
    for raw in req.triples:
        triple_data = dict(raw)
        subject = str(triple_data.get("subject_text") or triple_data.get("subject") or "").strip()
        predicate = str(
            triple_data.get("predicate_text") or triple_data.get("predicate") or ""
        ).strip()
        obj = str(triple_data.get("object_text") or triple_data.get("object") or "").strip()
        entry = {"subject": subject, "predicate": predicate, "object": obj}
        if not subject or not predicate or not obj:
            failed.append({**entry, "reason": "empty subject/predicate/object"})
            continue
        scope = SceneScope(
            scene="*" if req.scope_hint == "global" else "",
            task_type="",
            app="",
        )
        evidence_text = str(triple_data.get("evidence") or triple_data.get("source_text") or req.evidence or "").strip()
        source_id = str(triple_data.get("source_id") or req.source_id or "").strip()
        if not evidence_text:
            failed.append({**entry, "reason": "evidence is required"})
            continue
        memory_id = f"know_fact_{_fact_sha256(req.user_id, project_id, subject, predicate, obj)[:24]}"
        existing = know_repo.get_by_id(memory_id) if know_repo is not None else None
        new_evidence = Evidence(
            event_id=source_id or f"fact-proposal:{req.user_id}:{project_id}",
            content=evidence_text,
            source_type=SourceType.MANUAL_CONFIG,
        )
        evidences = list(existing.evidences) if existing is not None else []
        if not any(item.content == new_evidence.content and item.event_id == new_evidence.event_id for item in evidences):
            evidences.append(new_evidence)
        memory = KnowledgeMemory(
            memory_id=memory_id,
            user_id=req.user_id,
            project_id=project_id,
            knowledge_type=KnowledgeType.FACT,
            name=subject,
            content=f"{subject} {predicate} {obj}",
            subject=subject,
            predicate=predicate,
            object_value=obj,
            object_type=str(triple_data.get("object_type") or "Other"),
            scope=scope,
            confidence=float(triple_data.get("confidence") or 0.9),
            version=(existing.version + 1) if existing is not None else 1,
            evidences=evidences,
        )
        try:
            # upsert_memory 经 Domain Writer 事务写入；失败以抛异常或回读缺失呈现
            # （无 domain_writer 时 receipt 为 None，repo.save 已执行，故以回读为准）
            write_service.upsert_memory(memory, skip_write_gate=True)
            stored = (
                know_repo.get_by_id(memory.memory_id)
                if know_repo is not None
                else memory
            )
            if stored is None:
                failed.append({**entry, "reason": "write not persisted (read-back miss)"})
                continue
            created.append(
                _fact_memory_to_dict(
                    stored if isinstance(stored, KnowledgeMemory) else memory
                )
            )
        except Exception as exc:  # noqa: BLE001 —— 单条失败不阻断其余三元组
            logger.warning(
                "facts/propose: upsert failed for triple %s %s %s: %s",
                subject,
                predicate,
                obj,
                exc,
            )
            failed.append(
                {**entry, "reason": f"{type(exc).__name__}: {exc}"}
            )
    return {"created": created, "failed": failed}


def _fact_sha256(*parts: str) -> str:
    import hashlib

    return hashlib.sha256(
        "|".join(parts).encode("utf-8")
    ).hexdigest()


@router.post("/forget", response_model=ForgetResponse)
async def forget_memory(
    req: ForgetRequest,
    request: Request,
    forgetter: MemoryForgetter = Depends(_get_forgetter),
) -> ForgetResponse:
    """
    自然语言驱动的精准遗忘

    数据流: 用户指令 → forget_memory → LLM 解析意图
            → 定位记忆 → 删除 SQLite + FAISS + 缓存
            → 生成审计日志

    参数:
        req.instruction: 自然语言指令，如 "忘掉我关于周报格式的偏好"
        req.target_memory_ids: 精确记忆 ID 列表（与自然语言互斥或组合使用）
        req.target_scope: 可选的场景范围限制
        req.cascade: 是否级联删除关联数据

    返回:
        ForgetResponse: 遗忘结果，包含删除数量和审计记录 ID
    """
    return forgetter.execute(req)


@router.get("/forget/history", response_model=list[ForgetRecord])
async def list_forget_history(
    user_id: str = "default", request: Request = None
) -> list[ForgetRecord]:
    """
    列出指定用户的遗忘操作历史

    参数:
        user_id: 用户 ID

    返回:
        遗忘记录列表
    """
    repo = getattr(request.app.state, "forget_repo", None) if request else None
    if repo is not None:
        return repo.get_history(user_id)
    return []


@router.get("/forget/history/{record_id}", response_model=ForgetRecord)
async def get_forget_history_record(
    record_id: str, request: Request
) -> ForgetRecord:
    """
    获取单条遗忘记录详情

    参数:
        record_id: 遗忘记录 ID

    返回:
        遗忘记录对象；记录不存在时返回 404
    """
    repo = getattr(request.app.state, "forget_repo", None) if request else None
    if repo is None:
        raise HTTPException(status_code=503, detail="forget repository not initialized")
    record = repo.get_by_id(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="forget record not found")
    return record


class ForgetRuleRequest(BaseModel):
    """用户遗忘规则创建请求（I-13）。"""

    user_id: str = "default"
    topic: str  # 规则主题，如 "周报"
    keywords: list[str] = Field(default_factory=list)  # 命中主题后并入的关键词
    enabled: bool = True


@router.get("/forget/rules")
async def list_forget_rules(
    user_id: str = "default", request: Request = None
) -> list[dict]:
    """列出指定用户的遗忘规则。"""
    service = getattr(request.app.state, "forget_rule_service", None) if request else None
    if service is None:
        raise HTTPException(status_code=503, detail="forget rule service not initialized")
    return service.list(user_id)


@router.post("/forget/rules", status_code=201)
async def create_forget_rule(req: ForgetRuleRequest, request: Request):
    """创建一条用户遗忘规则（如"删除所有涉及 X 的记忆"）。

    之后遗忘指令若命中该规则 topic，其 keywords 会被并入意图关键词，实现
    用户自定义的语义规则遗忘（REFACTOR_PLAN_V2 §4.5.2 / I-13）。
    """
    service = getattr(request.app.state, "forget_rule_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="forget rule service not initialized")
    try:
        rule = service.create(
            user_id=req.user_id, topic=req.topic, keywords=req.keywords,
            enabled=req.enabled,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="invalid forget rule") from None
    return rule


@router.delete("/forget/rules/{rule_id}", status_code=200)
async def delete_forget_rule(rule_id: str, request: Request, user_id: str = "default"):
    """删除一条用户遗忘规则。"""
    service = getattr(request.app.state, "forget_rule_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="forget rule service not initialized")
    if not service.delete(user_id, rule_id):
        raise HTTPException(status_code=404, detail="forget rule not found")
    return {"deleted": True, "rule_id": rule_id}


@router.post("/evaluate/{task_name}")
async def run_evaluation(task_name: str, dataset_path: str = "", request: Request = None):
    """
    运行指定任务的评测

    task_name: "retrieval" | "latency" | "preference" | "conflict"

    数据流: 触发评测 → 加载数据集 → 批量执行 → 计算指标 → 生成报告

    retrieval: dataset_path 指向服务器上的评测数据集 JSON（queries[].query_text/relevant_ids）
    latency:   dataset_path 指向含 queries[].query_text 的数据集，跑检索延迟基准
    """
    state = request.app.state if request is not None else None
    retriever = getattr(state, "retriever", None) if state is not None else None
    task = (task_name or "").lower()

    if task == "retrieval":
        if not dataset_path:
            raise HTTPException(
                status_code=400,
                detail="dataset_path is required for retrieval evaluation",
            )
        if retriever is None:
            raise HTTPException(status_code=503, detail="retriever not initialized")
        try:
            from evaluation.metrics.retrieval_eval import RetrievalEvaluator
        except ImportError:
            raise HTTPException(status_code=503, detail="evaluation module unavailable")
        try:
            report = RetrievalEvaluator(retriever, top_k=10).run(dataset_path)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="dataset file not found")
        except (ValueError, KeyError, TypeError):
            raise HTTPException(status_code=400, detail="invalid dataset file")
        return report

    if task == "latency":
        if not dataset_path:
            raise HTTPException(
                status_code=400,
                detail="dataset_path is required for latency benchmark",
            )
        if retriever is None:
            raise HTTPException(status_code=503, detail="retriever not initialized")
        try:
            import json

            from evaluation.metrics.latency_benchmark import LatencyBenchmark
        except ImportError:
            raise HTTPException(status_code=503, detail="evaluation module unavailable")
        try:
            with open(dataset_path, "r", encoding="utf-8") as f:
                queries = [item["query_text"] for item in json.load(f)["queries"]]
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=400, detail="invalid dataset file")
        if not queries:
            raise HTTPException(status_code=400, detail="dataset has no queries")
        from memoryhub.adapter.schemas import SearchRequest

        bench = LatencyBenchmark(
            search_fn=lambda q: retriever.search(SearchRequest(query=q, top_k=5))
        )
        try:
            result = bench.benchmark_search(queries, iterations=20)
        except Exception:
            raise HTTPException(status_code=503, detail="latency benchmark failed") from None
        return result.to_dict()

    if task in ("preference", "conflict"):
        if not dataset_path:
            raise HTTPException(
                status_code=400,
                detail=f"dataset_path is required for {task} evaluation",
            )
        try:
            if task == "preference":
                from evaluation.metrics.preference_eval import PreferenceEvaluator

                evaluator = PreferenceEvaluator()
            else:
                from evaluation.metrics.conflict_eval import ConflictEvaluator

                evaluator = ConflictEvaluator()
        except ImportError:
            raise HTTPException(status_code=503, detail="evaluation module unavailable")
        try:
            report = evaluator.run(dataset_path)
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="dataset file not found")
        except (ValueError, KeyError, TypeError):
            raise HTTPException(status_code=400, detail="invalid dataset file")
        return report

    # preference / conflict 评测框架已定义、实现已落地（Phase F / I-10）；仅未知任务返回 501
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={"code": "evaluation.not_implemented", "task_name": task_name},
    )


@router.get("/evaluate/reports", response_model=list[EvalReport])
async def list_eval_reports():
    """列出历史评测报告"""
    return []
