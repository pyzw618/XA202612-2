"""
REST API 路由定义 — Memory Adapter 标准接口

所有接口均通过 FastAPI 路由暴露，供 OS Agent 或前端调用。
"""

from __future__ import annotations

import hmac
import json
import re
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from memoryhub.adapter.schemas import (
    ConflictRecord,
    EvalReport,
    ExtractionTask,
    ExtractionTaskRunRequest,
    ExtractionTaskRunResponse,
    ExtractionTaskStatus,
    FeedbackRequest,
    ForgetRecord,
    ForgetRequest,
    ForgetResponse,
    KnowledgeMemory,
    MemoryStatus,
    PreferenceMemory,
    SearchRequest,
    SearchResponse,
    WriteEventRequest,
    WriteEventResponse,
)
from memoryhub.adapter.user_rule_schemas import (
    CreateUserRuleRequest,
    UpdateUserRuleRequest,
    UserRuleErrorResponse,
    UserRuleResponse,
)
from memoryhub.core.forget import MemoryForgetter
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
):
    """列出知识记忆，支持按类型和场景过滤"""
    repo = getattr(request.app.state, "know_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="knowledge repository not initialized")
    if scene:
        values = repo.get_by_scope(user_id, scene, "")
    elif knowledge_type:
        values = repo.get_by_type(user_id, knowledge_type)
    else:
        values = repo.list_all(status="active", user_id=user_id)
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


@router.get("/conflicts", response_model=list[ConflictRecord])
async def list_conflicts(
    status: str = "pending", user_id: str = "default", request: Request = None
):
    """列出冲突记录，支持按状态过滤"""
    # 尝试访问冲突仓储，若不可用则返回空列表
    repo = getattr(request.app.state, "conflict_repo", None) if request else None
    if repo is not None:
        return repo.list_all(status, user_id=user_id)
    return []


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
    """Apply feedback to preference or knowledge without changing the API contract."""
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

    if req.action == "update" and req.feedback_text:
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
    if write_service is not None:
        write_service.upsert_memory(memory)
    else:
        repo.save(memory)
        _sync_memory_index(
            request, memory, remove=memory.status == MemoryStatus.ARCHIVED
        )
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


@router.post("/memories/preference")
async def write_preference_memory(
    req: PreferenceMemory,
    request: Request,
    sync_service=Depends(_get_sync_service),
):
    """
    显式写入/更新偏好记忆，并同步到 Milvus。

    数据流: PreferenceMemory → SQLite 事务写入 → Embedding → Milvus upsert
            → 标记 index_version → 失效检索缓存
    """
    sqlite_ok, memory_id = sync_service.index_memory(req)
    if not sqlite_ok:
        raise HTTPException(status_code=503, detail="memory write failed")
    return {"status": "ok", "memory_id": memory_id}


@router.post("/memories/knowledge")
async def write_knowledge_memory(
    req: KnowledgeMemory,
    request: Request,
    sync_service=Depends(_get_sync_service),
):
    """
    显式写入/更新知识记忆，并同步到 Milvus。

    数据流: KnowledgeMemory → SQLite 事务写入 → Embedding → Milvus upsert
            → 标记 index_version → 失效检索缓存
    """
    sqlite_ok, memory_id = sync_service.index_memory(req)
    if not sqlite_ok:
        raise HTTPException(status_code=503, detail="memory write failed")
    return {"status": "ok", "memory_id": memory_id}


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


@router.post("/evaluate/{task_name}", response_model=EvalReport)
async def run_evaluation(task_name: str, dataset_path: str = "", request: Request = None):
    """
    运行指定任务的评测

    task_name: "preference" | "retrieval" | "conflict" | "latency"

    数据流: 触发评测 → 加载数据集 → 批量执行 → 计算指标 → 生成报告
    """
    # 最小实现：返回基本评测报告
    return EvalReport(task_name=task_name)


@router.get("/evaluate/reports", response_model=list[EvalReport])
async def list_eval_reports():
    """列出历史评测报告"""
    return []
