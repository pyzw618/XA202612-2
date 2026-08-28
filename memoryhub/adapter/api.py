"""
REST API 路由定义 — Memory Adapter 标准接口

所有接口均通过 FastAPI 路由暴露，供 OS Agent 或前端调用。
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from memoryhub.adapter import agent_api as _agent_api
from memoryhub.adapter.schemas import (
    ConflictRecord,
    EvalReport,
    ExtractionTask,
    ExtractionTaskRunRequest,
    ExtractionTaskRunResponse,
    ExtractionTaskStatus,
    EventQuality,
    FeedbackRequest,
    ForgetRecord,
    ForgetRequest,
    ForgetResponse,
    KnowledgeMemory,
    MemoryEvent,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    SafetyAction,
    SearchRequest,
    SearchResponse,
    SourceType,
    WriteEventRequest,
    WriteEventResponse,
    canonical_sha256,
)
from memoryhub.adapter.user_rule_schemas import (
    CreateUserRuleRequest,
    UpdateUserRuleRequest,
    UserRuleErrorResponse,
    UserRuleResponse,
)
from memoryhub.core.fact.models import (
    EntityType,
    FactCandidate,
    FactDecisionMode,
    FactDecisionRequired,
    FactProposalStatus,
    MemoryScope,
    RawTriple,
    Resolution,
)
from memoryhub.core.forget import MemoryForgetter
from memoryhub.core.safety.gate import SafetyGateError
from memoryhub.core.safety.memory_write import (
    GuardedMemoryWriteResult,
    MemoryWriteSafetyError,
    guard_memory_write,
)
from memoryhub.embedding import KylinEmbeddingError
from memoryhub.storage.vector_engine import MilvusEngineError

router = APIRouter(prefix="/api/memory", tags=["memory"])


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

    数据流: OS Agent → write_events → Ingestion.clean → Ingestion.normalize
            → 存入事件库 → 触发偏好/知识抽取

    参数:
        req.events: MemoryEvent 列表

    返回:
        accepted: 成功接收的事件数
        rejected: 被拒绝的事件数（质量/安全过滤）
        event_ids: 接受的事件 ID 列表
    """
    service = getattr(request.app.state, "event_ingestion_service", None)
    if service is None:
        memory = _memory_service(request)
        try:
            result = memory.write_events(req)
            return WriteEventResponse(
                accepted=result.accepted,
                rejected=result.rejected,
                event_ids=result.event_ids,
            )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="event ingestion failed") from None
    try:
        result = service.ingest(req.events)
        return WriteEventResponse(
            accepted=result.accepted,
            rejected=result.rejected,
            event_ids=result.event_ids,
            extraction_failures=result.extraction_failures,
            retry_tasks_enqueued=result.retry_tasks_enqueued,
            retry_queue_failures=result.retry_queue_failures,
            fact_proposal_ids=result.fact_proposal_ids,
            facts_committed=result.facts_committed,
            facts_awaiting_decision=result.facts_awaiting_decision,
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="event ingestion failed") from None


# ============================================================
# 抽取任务与死信管理
# ============================================================



# ============================================================
# Facts management
# ============================================================

@router.get("/facts")
async def list_facts(request: Request, user_id: str = "default", status: str | None = "active", limit: int = Query(default=100, ge=1, le=500)):
    store = getattr(request.app.state, "fact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="fact store not initialized")
    return store.list_facts(status=status, user_id=user_id, limit=limit)

@router.get("/facts/conflicts")
async def list_fact_conflicts(request: Request, user_id: str = "default", limit: int = Query(default=100, ge=1, le=500)):
    store = getattr(request.app.state, "fact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="fact store not initialized")
    return store.list_fact_conflicts(user_id=user_id, limit=limit)

@router.get("/facts/{fact_id}")
async def get_fact(fact_id: str, request: Request, user_id: str = "default"):
    store = getattr(request.app.state, "fact_store", None)
    fact = store.get_fact(fact_id, user_id=user_id) if store is not None else None
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return fact

@router.get("/facts/{fact_id}/evidence")
async def get_fact_evidence(fact_id: str, request: Request, user_id: str = "default"):
    store = getattr(request.app.state, "fact_store", None)
    fact = store.get_fact(fact_id, user_id=user_id) if store is not None else None
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    return store.list_fact_evidence(fact_id, user_id)

@router.delete("/facts/{fact_id}")
async def delete_fact(fact_id: str, request: Request, user_id: str = "default"):
    store = getattr(request.app.state, "fact_store", None)
    index_service = getattr(request.app.state, "fact_index_service", None)
    fact = store.get_fact(fact_id, user_id=user_id) if store is not None else None
    if fact is None:
        raise HTTPException(status_code=404, detail="fact not found")
    if not store.update_fact_status(fact_id, "deleted", user_id=user_id):
        raise HTTPException(status_code=409, detail="fact delete failed")
    fact.status = "deleted"
    fact.pending_index = True
    if index_service is not None:
        try:
            index_service.sync_fact(fact, remove=True)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="fact projection delete pending") from exc
    store.delete_fact_artifacts([fact_id], user_id)
    store.prune_orphan_entities(user_id)
    return {"deleted": True, "fact_id": fact_id}
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
    fact_store = getattr(state, "fact_store", None)
    if fact_store is not None:
        for fact in response.facts:
            if fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            fact_store.record_access(fact.fact_id, user_id=fact.user_id)


@router.post("/search", response_model=SearchResponse)
async def search_memory(req: SearchRequest, request: Request):
    """
    混合检索偏好与知识记忆

    数据流: OS Agent → search_memory → HybridRetriever.search
            → (vector_recall + keyword_recall + metadata_filter)
            → rerank → 返回 Top-K

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
    retriever = getattr(request.app.state, "retriever", None)
    if retriever is None:
        memory = getattr(request.app.state, "memory_service", None)
        if memory is None:
            raise HTTPException(
                status_code=503, detail="retrieval service not initialized"
            )
        try:
            response = memory.search(req)
            _record_search_access(request, response)
            return response
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=500, detail="internal retrieval error"
            ) from None
    try:
        response = retriever.search(req)
        if response.total_count == 0:
            memory = getattr(request.app.state, "memory_service", None)
            if memory is not None:
                fallback = memory.search(req)
                if fallback.total_count:
                    response = fallback
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

    数据流: OS Agent → get_memory_context → search_memory
            → 格式化为上下文文本 → 返回
    """
    retriever = getattr(request.app.state, "retriever", None)
    memory = getattr(request.app.state, "memory_service", None)

    def _format_context(context_text: str) -> dict[str, str]:
        # 同时兼容本地集成（context）与 MCP 集成（context_text）两种消费方
        return {"context": context_text, "context_text": context_text}

    if retriever is None:
        if memory is None:
            raise HTTPException(
                status_code=503, detail="retrieval service not initialized"
            )
        try:
            context_text, search = memory.context(req)
            _record_search_access(request, search)
            return _format_context(context_text)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=500, detail="internal retrieval error"
            ) from None
    try:
        response = retriever.search(req)
        if response.total_count == 0 and memory is not None:
            context_text, search = memory.context(req)
            _record_search_access(request, search)
            return _format_context(context_text)
    except (KylinEmbeddingError, MilvusEngineError) as exc:
        raise _retrieval_http_error(exc) from None
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid search request") from None
    except Exception:
        raise HTTPException(status_code=500, detail="internal retrieval error") from None

    _record_search_access(request, response)

    # 格式化为可注入 prompt 的文本
    lines = []
    if response.preferences:
        lines.append("## 用户偏好")
        for p in response.preferences:
            lines.append(f"- {p.text} (置信度: {p.confidence:.2f})")
    if response.knowledge:
        lines.append("## 相关知识")
        for k in response.knowledge:
            lines.append(f"- {k.name}: {k.content}")
    return _format_context("\n".join(lines))


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
    repo = pref_repo
    if memory is None and know_repo is not None:
        memory = know_repo.get_by_id(req.memory_id)
        repo = know_repo
    if memory is None or memory.user_id != req.user_id:
        raise HTTPException(status_code=404, detail="memory not found")

    content_update = req.action == "update" and bool(req.feedback_text)
    if content_update:
        if memory.memory_type == "knowledge":
            memory.content = req.feedback_text
            memory.version = max(1, memory.version) + 1
        else:
            memory.text = req.feedback_text
    elif req.action == "reject":
        memory.status = MemoryStatus.ARCHIVED
    elif req.action == "confirm" and memory.memory_type == "knowledge":
        memory.total_count += 1
        memory.success_count += 1

    write_service = getattr(request.app.state, "memory_write_service", None)

    def persist(selected_memory):
        if write_service is not None:
            write_service.upsert_memory(selected_memory)
        else:
            repo.save(selected_memory)
            _sync_memory_index(
                request,
                selected_memory,
                remove=selected_memory.status == MemoryStatus.ARCHIVED,
            )
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
        fact_store=getattr(state, "fact_store", None),
        fact_index_service=getattr(state, "fact_index_service", None),
    )


class ForgetPreviewResponse(BaseModel):
    """精准遗忘预览结果：只定位候选，不执行删除。"""

    user_id: str = "default"
    instruction: str = ""
    candidate_ids: list[str] = Field(default_factory=list)
    deleted_count: int = 0
    memory_type: str = "all"
    target_topic: str = ""


EntityTypeValue = Literal[
    "Person", "Organization", "Location", "Device", "Software",
    "File", "Account", "Date", "Other",
]


class FactTripleInput(BaseModel):
    """Agent-supplied fact triple; no extraction LLM is called for this input."""

    subject_text: str = Field(min_length=1, max_length=500)
    subject_type: EntityTypeValue = EntityType.OTHER.value
    predicate_text: str = Field(min_length=1, max_length=200)
    object_text: str = Field(min_length=1, max_length=2000)
    object_type: EntityTypeValue = EntityType.OTHER.value
    evidence: str = Field(default="", max_length=4000)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class FactProposeRequest(BaseModel):
    """Submit structured fact candidates from an Agent or review UI."""

    user_id: str = Field(default="default", min_length=1, max_length=128)
    decision_mode: Literal["user_review", "agent_autonomous"] | None = None
    conflict_decision_mode: Literal["user_review", "agent_autonomous"] | None = None
    source_id: str = Field(default="", max_length=500)
    scope_hint: Literal["global", "project"] | None = "global"
    project_id: str | None = Field(default=None, max_length=256)
    triples: list[FactTripleInput] = Field(default_factory=list, min_length=1, max_length=100)


class FactDecisionInput(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    action: Literal["commit", "reject"]
    scope: Literal["global", "project"] | None = None
    project_id: str | None = Field(default=None, max_length=256)
    resolution: Literal["replace", "keep_old", "merge", "coexist", "escalate"] | None = None
    conflict_decision_mode: Literal["user_review", "agent_autonomous"] | None = None
    subject_entity_id: str | None = Field(default=None, max_length=256)
    object_entity_id: str | None = Field(default=None, max_length=256)
    predicate_id: str | None = Field(default=None, max_length=256)
    force: bool = False


class FactDecideRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    decisions: list[FactDecisionInput] = Field(min_length=1, max_length=100)


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
    """Stage Agent-supplied triples or autonomously commit admitted facts."""
    pipeline = getattr(request.app.state, "fact_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="fact pipeline not initialized")
    mode = req.decision_mode or getattr(
        getattr(request.app.state, "config", None),
        "fact",
        None,
    )
    if not isinstance(mode, str):
        mode = getattr(mode, "decision_mode", FactDecisionMode.USER_REVIEW.value)
    conflict_mode = req.conflict_decision_mode or getattr(
        getattr(request.app.state, "config", None),
        "fact",
        None,
    )
    if not isinstance(conflict_mode, str):
        conflict_mode = getattr(
            conflict_mode,
            "conflict_decision_mode",
            FactDecisionMode.USER_REVIEW.value,
        )
    if req.scope_hint == MemoryScope.PROJECT.value and not req.project_id:
        raise HTTPException(status_code=422, detail="project scope requires project_id")
    if req.scope_hint == MemoryScope.GLOBAL.value and req.project_id:
        raise HTTPException(status_code=422, detail="global scope cannot include project_id")

    def persist_safe_request(safe_req: FactProposeRequest):
        return _persist_fact_proposals(
            pipeline,
            safe_req,
            decision_mode=mode,
            conflict_decision_mode=conflict_mode,
        )

    proposals, safety_action, audit_id = _guard_fact_proposals(
        request, req, persist_safe_request
    )
    for item in proposals:
        item["safety_action"] = safety_action
        item["audit_id"] = audit_id
    return proposals


@router.post("/facts/decide")
async def decide_facts(req: FactDecideRequest, request: Request):
    """Apply a user or Agent decision to a batch of durable fact proposals."""
    pipeline = getattr(request.app.state, "fact_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="fact pipeline not initialized")
    return [
        _decide_fact_proposal(pipeline, req.user_id, decision)
        for decision in req.decisions
    ]


def _guard_fact_proposals(request: Request, req: FactProposeRequest, sink):
    """Fail closed and persist only the gate-approved, possibly masked request."""
    gate = _get_safety_gate(request)
    content = req.model_dump(mode="json", exclude={"user_id"})
    source_hash = canonical_sha256(
        {"operation": "explicit_fact_propose", "user_id": req.user_id, "content": content}
    )
    event = MemoryEvent(
        event_id=f"fact_propose_{source_hash[:24]}",
        source_type=SourceType.MANUAL_CONFIG,
        event_type="explicit_fact_propose",
        user_id=req.user_id,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        payload={"operation": "explicit_fact_propose", "request": content},
        source_hash=source_hash,
        quality=EventQuality(
            score=1.0,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )
    try:
        outcome = gate.route(event)
    except SafetyGateError:
        raise HTTPException(status_code=503, detail="memory safety gate failed") from None
    if outcome.approved is None:
        _raise_fact_safety_outcome(outcome.action, outcome.audit_id)

    def guarded_sink(approved):
        verified = gate.verify_approved(approved)
        safe_event = verified.safe_event
        try:
            if safe_event.user_id != req.user_id:
                raise ValueError("owner mismatch")
            payload = safe_event.payload
            if payload.get("operation") != "explicit_fact_propose":
                raise ValueError("operation mismatch")
            safe_data = dict(payload["request"])
            safe_data["user_id"] = req.user_id
            safe_req = FactProposeRequest.model_validate(safe_data)
        except Exception:
            raise HTTPException(
                status_code=503, detail="invalid safe fact projection"
            ) from None
        return sink(safe_req)

    try:
        result = gate.guarded_call(outcome.approved, guarded_sink)
    except HTTPException:
        raise
    except SafetyGateError:
        raise HTTPException(status_code=503, detail="memory safety gate failed") from None
    return result, outcome.action.value, outcome.audit_id


def _raise_fact_safety_outcome(action: SafetyAction, audit_id: str) -> None:
    if action is SafetyAction.REVIEW:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "memory.safety.review_required",
                "status": "review_required",
                "safety_action": action.value,
                "audit_id": audit_id,
            },
        )
    raise HTTPException(
        status_code=403,
        detail={
            "code": "memory.safety.rejected",
            "status": "rejected",
            "safety_action": action.value,
            "audit_id": audit_id,
        },
    )


def _persist_fact_proposals(
    pipeline,
    req: FactProposeRequest,
    *,
    decision_mode: str,
    conflict_decision_mode: str = FactDecisionMode.USER_REVIEW.value,
):
    results = []
    for raw in req.triples:
        triple = RawTriple(**raw.model_dump())
        admission = pipeline.admission.evaluate(
            triple, project_id=req.project_id, scope_hint=req.scope_hint
        )
        proposal = FactCandidate(
            candidate_id=FactCandidate.make_id(),
            raw_triple=triple,
            admission=admission,
            source_id=req.source_id,
            project_id_hint=req.project_id,
            scope_hint=req.scope_hint,
            metadata={
                "user_id": req.user_id,
                "decision_mode": decision_mode,
                "conflict_decision_mode": conflict_decision_mode,
            },
        )
        item = _agent_api._candidate_to_json(proposal)
        if (
            decision_mode == FactDecisionMode.AGENT_AUTONOMOUS.value
            and not admission.should_remember
        ):
            item["status"] = FactProposalStatus.REJECTED.value
            results.append(item)
            continue

        pipeline.store.save_fact_proposal(
            proposal,
            user_id=req.user_id,
            decision_mode=decision_mode,
            conflict_decision_mode=conflict_decision_mode,
        )
        if decision_mode == FactDecisionMode.AGENT_AUTONOMOUS.value:
            decision = FactDecisionInput(
                proposal_id=proposal.proposal_id,
                action="commit",
                scope=req.scope_hint,
                project_id=req.project_id,
                conflict_decision_mode=conflict_decision_mode,
            )
            item.update(_decide_fact_proposal(pipeline, req.user_id, decision))
        results.append(item)
    return results


def _decide_fact_proposal(pipeline, user_id: str, decision: FactDecisionInput) -> dict:
    stored = pipeline.store.get_fact_proposal(
        decision.proposal_id, user_id=user_id
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="fact proposal not found")
    proposal = stored["candidate"]
    if decision.action == "reject":
        pipeline.store.update_fact_proposal_status(
            proposal.proposal_id,
            user_id=user_id,
            status=FactProposalStatus.REJECTED.value,
        )
        return {"proposal_id": proposal.proposal_id, "status": "rejected"}

    if stored["status"] == FactProposalStatus.COMMITTED.value:
        return {
            "proposal_id": proposal.proposal_id,
            "status": "committed",
            "fact_id": stored["committed_fact_id"],
            "idempotent": True,
        }
    conflict_decision_mode = (
        decision.conflict_decision_mode
        or stored.get("conflict_decision_mode")
        or FactDecisionMode.USER_REVIEW.value
    )
    scope = decision.scope or proposal.scope_hint
    if scope is None:
        pipeline.store.update_fact_proposal_status(
            proposal.proposal_id,
            user_id=user_id,
            status=FactProposalStatus.AWAITING_DECISION.value,
        )
        return {
            "proposal_id": proposal.proposal_id,
            "status": "awaiting_decision",
            "requires_decision": True,
            "reason": "scope is required",
            "decision_task": {
                "decision_type": "scope_resolution",
                "input_text": proposal.raw_triple.evidence,
                "candidates": [{"scope": "global"}, {"scope": "project"}],
                "allowed_actions": ["select_scope"],
                "reason": "事实作用域不明确，需要主 Agent 结合当前项目上下文裁决",
            },
        }
    project_id = decision.project_id or proposal.project_id_hint
    try:
        result = pipeline.commit(
            proposal,
            scope=scope,
            project_id=project_id,
            resolution=decision.resolution,
            force=decision.force,
            auto_resolve=(
                conflict_decision_mode
                == FactDecisionMode.AGENT_AUTONOMOUS.value
            ),
            user_id=user_id,
            subject_entity_id=decision.subject_entity_id,
            object_entity_id=decision.object_entity_id,
            predicate_id=decision.predicate_id,
        )
    except FactDecisionRequired as exc:
        proposal.metadata["pending_decision"] = exc.to_dict()
        pipeline.store.save_fact_proposal(
            proposal,
            user_id=user_id,
            decision_mode=stored.get("decision_mode", FactDecisionMode.USER_REVIEW.value),
            conflict_decision_mode=conflict_decision_mode,
        )
        pipeline.store.update_fact_proposal_status(
            proposal.proposal_id,
            user_id=user_id,
            status=FactProposalStatus.AWAITING_DECISION.value,
        )
        return {
            "proposal_id": proposal.proposal_id,
            "status": FactProposalStatus.AWAITING_DECISION.value,
            "requires_decision": True,
            "decision_task": exc.to_dict(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    requires_decision = (
        result.relation == "CONFLICT"
        and result.resolution == Resolution.ESCALATE.value
    )
    proposal_status = (
        FactProposalStatus.AWAITING_DECISION.value
        if requires_decision
        else FactProposalStatus.COMMITTED.value
    )
    stored_fact = (
        result.existing_fact
        if result.relation == "DUPLICATE"
        or (
            result.relation == "CONFLICT"
            and result.resolution == Resolution.KEEP_OLD.value
        )
        else result.new_fact
    )
    pipeline.store.update_fact_proposal_status(
        proposal.proposal_id,
        user_id=user_id,
        status=proposal_status,
        committed_fact_id=(
            stored_fact.fact_id if stored_fact is not None and not requires_decision else None
        ),
    )
    decision_task = None
    if requires_decision:
        decision_task = {
            "decision_type": "fact_conflict",
            "input_text": proposal.raw_triple.evidence,
            "candidates": [
                {
                    "role": "existing",
                    "fact_id": result.existing_fact.fact_id,
                    "object_value": result.existing_fact.object_value,
                    "observed_at": result.existing_fact.observed_at,
                    "confidence": result.existing_fact.confidence,
                } if result.existing_fact is not None else {},
                {
                    "role": "proposed",
                    "object_value": result.new_fact.object_value,
                    "observed_at": result.new_fact.observed_at,
                    "confidence": result.new_fact.confidence,
                },
            ],
            "allowed_actions": ["replace", "keep_old", "merge", "coexist"],
            "reason": result.reason,
        }
    return {
        "proposal_id": proposal.proposal_id,
        "status": proposal_status,
        "requires_decision": requires_decision,
        "relation": result.relation,
        "resolution": result.resolution,
        "reason": result.reason,
        "conflict_decision_mode": conflict_decision_mode,
        "fact_id": (
            stored_fact.fact_id
            if stored_fact is not None and not requires_decision
            else None
        ),
        "decision_task": decision_task,
    }


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


# ============================================================
# 评测
# ============================================================


@router.post("/evaluate/{task_name}")
async def run_evaluation(task_name: str, dataset_path: str = "", request: Request = None):
    """
    运行指定任务的评测

    task_name: "retrieval" | "latency"（preference / conflict 后端尚未实现）

    数据流: 触发评测 → 加载数据集 → 批量执行 → 计算指标 → 生成报告

    retrieval: dataset_path 指向服务器上的评测数据集 JSON（queries[].query_text/relevant_ids）
    latency:   dataset_path 指向含 queries[].query_text 的数据集，跑检索延迟基准
    """
    state = request.app.state if request is not None else None
    retriever = getattr(state, "retriever", None) if state is not None else None
    task = (task_name or "").lower()

    if task == "retrieval":
        if not dataset_path:
            raise HTTPException(status_code=400, detail="dataset_path is required for retrieval evaluation")
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
            raise HTTPException(status_code=400, detail="dataset_path is required for latency benchmark")
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

    # preference / conflict 评测框架已定义、实现未落地
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={"code": "evaluation.not_implemented", "task_name": task_name},
    )


@router.get("/evaluate/reports", response_model=list[EvalReport])
async def list_eval_reports():
    """列出历史评测报告"""
    return []
