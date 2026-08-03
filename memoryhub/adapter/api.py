"""
REST API 路由定义 — Memory Adapter 标准接口

所有接口均通过 FastAPI 路由暴露，供 OS Agent 或前端调用。
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from memoryhub.adapter.schemas import (
    ConflictRecord,
    EvalReport,
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
    repo = getattr(request.app.state, "event_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="event repository not initialized")
    try:
        accepted = repo.batch_save(req.events)
        event_ids = [e.event_id for e in req.events]
        return WriteEventResponse(
            accepted=accepted,
            rejected=len(req.events) - accepted,
            event_ids=event_ids,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to write events: {str(e)}") from None


# ============================================================
# 记忆检索
# ============================================================


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
        raise HTTPException(status_code=503, detail="retrieval service not initialized")
    try:
        return retriever.search(req)
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
    if retriever is None:
        raise HTTPException(status_code=503, detail="retrieval service not initialized")
    try:
        response = retriever.search(req)
    except (KylinEmbeddingError, MilvusEngineError) as exc:
        raise _retrieval_http_error(exc) from None
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid search request") from None
    except Exception:
        raise HTTPException(status_code=500, detail="internal retrieval error") from None

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
    return {"context_text": "\n".join(lines)}


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
        return repo.get_by_scope(user_id, scene, "")
    return repo.get_active(user_id)


@router.get("/preferences/{memory_id}", response_model=PreferenceMemory)
async def get_preference(memory_id: str, request: Request):
    """获取单条偏好记忆详情"""
    repo = getattr(request.app.state, "pref_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="preference repository not initialized")
    result = repo.get_by_id(memory_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"preference {memory_id} not found")
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
    return repo.list_all(status="active")


@router.get("/knowledge/{memory_id}", response_model=KnowledgeMemory)
async def get_knowledge(memory_id: str, request: Request):
    """获取单条知识记忆详情"""
    repo = getattr(request.app.state, "know_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="knowledge repository not initialized")
    result = repo.get_by_id(memory_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"knowledge {memory_id} not found")
    return result


# ============================================================
# 冲突管理
# ============================================================


@router.get("/conflicts", response_model=list[ConflictRecord])
async def list_conflicts(status: str = "pending", request: Request = None):
    """列出冲突记录，支持按状态过滤"""
    # 尝试访问冲突仓储，若不可用则返回空列表
    repo = getattr(request.app.state, "conflict_repo", None) if request else None
    if repo is not None:
        return repo.list_all(status)
    return []


class ResolveConflictRequest(BaseModel):
    decision: str
    reason: str = ""


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
        result = repo.resolve(conflict_id, body.decision, body.reason)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


# ============================================================
# 用户反馈
# ============================================================


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, request: Request):
    """
    提交用户反馈，触发偏好更新并同步到向量索引

    数据流: 用户反馈 → submit_feedback → 更新 SQLite → 同步 Milvus
            → 失效检索缓存

    参数:
        req.memory_id: 关联的记忆 ID
        req.feedback_text: 反馈文本
        req.action: "update" | "confirm" | "reject"
    """
    pref_repo = getattr(request.app.state, "pref_repo", None)
    sync_service = getattr(request.app.state, "sync_service", None)
    if pref_repo is None:
        raise HTTPException(status_code=503, detail="preference repository not initialized")
    # 根据反馈更新偏好记忆
    memory = pref_repo.get_by_id(req.memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail=f"memory {req.memory_id} not found")
    # 简单实现：更新文本并保存
    if req.action == "update" and req.feedback_text:
        memory.text = req.feedback_text
    elif req.action == "reject":
        memory.status = MemoryStatus.ARCHIVED
    # confirm 无需操作，仅记录
    pref_repo.save(memory)

    # 通过同步服务保持 SQLite 与 Milvus 一致
    if sync_service is not None:
        if memory.status in (MemoryStatus.ARCHIVED, MemoryStatus.DELETED):
            sync_service.delete_memory(memory.memory_id)
        else:
            sync_service.index_memory(memory)

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
    """
    从应用状态获取 MemoryForgetter 实例

    注入真实的 db / vector_engine(Milvus) / vector_store(FAISS 降级) / cache / repositories。
    """
    return MemoryForgetter(
        llm_client=getattr(request.app.state, "llm_client", None),
        storage=getattr(request.app.state, "db", None),
        vector_store=getattr(request.app.state, "vector_store", None),
        vector_engine=getattr(request.app.state, "vector_engine", None),
        cache=getattr(request.app.state, "retriever", None),
        pref_repo=getattr(request.app.state, "pref_repo", None),
        know_repo=getattr(request.app.state, "know_repo", None),
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
