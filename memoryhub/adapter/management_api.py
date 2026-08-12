"""
REST API 路由定义 — 管理后台缺口补齐（供前端可视化后台使用）

在 ``memoryhub/adapter/api.py`` 既有接口之上，补齐前端页面规划（前端页面规划.md
第八节缺口清单）所需的接口：

- 记忆状态流转（单条 / 批量）、软删除（批量）、硬删除（回收站彻底删除）
- 知识版本历史
- 记忆健康度批量查询（健康度看板）
- 生命周期 / 自动遗忘触发与阈值展示
- 全量事件列表（分页）
- 安全审计日志列表 / 验链
- REVIEW 隔离区列表 / 查看 / 删除 / 放行
- 遗忘历史详情（被删记忆内容）
- 系统状态 / 参数（只读、不泄密）

本模块复用 ``app.state`` 上已装配的服务，不在模块层持有全局单例。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from memoryhub.adapter.schemas import ForgetRequest
from memoryhub.core.forget import MemoryForgetter
from memoryhub.core.forget.auto_forget import AutoForgetEngine
from memoryhub.core.forget.health import HealthCalculator
from memoryhub.core.lifecycle.manager import LifecycleManager

router = APIRouter(prefix="/api/memory", tags=["management"])

_MEMORY_STATUSES = frozenset({"active", "archived", "pending", "deleted"})


# ============================================================
# 请求/响应模型
# ============================================================


class MemoryStatusUpdate(BaseModel):
    """单条记忆状态流转。"""

    user_id: str = "default"
    status: str
    reason: str = ""


class BatchMemoryStatusUpdate(BaseModel):
    """批量记忆状态流转（待审队列"全部保持/全部归档"、回收站"批量恢复"等）。"""

    user_id: str = "default"
    memory_ids: list[str] = Field(min_length=1)
    status: str
    reason: str = ""


class BatchMemoryDelete(BaseModel):
    """批量软删除（列表页"勾选 → 删除"）。"""

    user_id: str = "default"
    memory_ids: list[str] = Field(min_length=1)
    cascade: bool = True


class QuarantineReleaseRequest(BaseModel):
    """隔离区放行/驳回。decision: "allow" 放行重新入管线；"reject" 仅丢弃。"""

    decision: str = "allow"
    user_id: str = "default"


# ============================================================
# 工具函数
# ============================================================


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _resolve_memory(state, memory_id: str, user_id: str):
    """跨偏好/知识/事实三类存储解析一条记忆，返回 (memory_type, memory) 或 (None, None)。"""
    pref_repo = getattr(state, "pref_repo", None)
    know_repo = getattr(state, "know_repo", None)
    fact_store = getattr(state, "fact_store", None)
    if pref_repo is not None:
        mem = pref_repo.get_by_id(memory_id)
        if mem is not None and mem.user_id == user_id:
            return "preference", mem
    if know_repo is not None:
        mem = know_repo.get_by_id(memory_id)
        if mem is not None and mem.user_id == user_id:
            return "knowledge", mem
    if fact_store is not None:
        fact = fact_store.get_fact(memory_id, user_id=user_id)
        if fact is not None:
            return "fact", fact
    return None, None


def _build_forgetter(state) -> MemoryForgetter:
    """按 app.state 装配完整遗忘执行器（与 api.py 的 _get_forgetter 一致）。"""
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


def _set_memory_status(state, memory_id: str, user_id: str, status: str) -> dict:
    """把一条记忆置为指定状态；deleted 走遗忘器级联软删除，其余同步检索索引。"""
    if status not in _MEMORY_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "memory.invalid_status", "status": status},
        )
    mtype, memory = _resolve_memory(state, memory_id, user_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")

    if status == "deleted":
        forgetter = _build_forgetter(state)
        count = forgetter.delete_memories([memory_id], cascade=True, user_id=user_id)
        return {"memory_id": memory_id, "status": "deleted", "deleted": count > 0}

    write_service = getattr(state, "memory_write_service", None)
    fact_index_service = getattr(state, "fact_index_service", None)

    if mtype == "fact":
        fact_store = getattr(state, "fact_store", None)
        if fact_store is None:
            raise HTTPException(status_code=503, detail="fact store not initialized")
        if not fact_store.update_fact_status(memory_id, status, user_id=user_id):
            raise HTTPException(status_code=409, detail="fact status update failed")
        current = fact_store.get_fact(memory_id, user_id=user_id)
        if current is not None and fact_index_service is not None:
            try:
                fact_index_service.sync_fact(current)
            except Exception:
                # 同步失败不影响 SQLite 事实源；补偿任务会重试 pending_index 记录
                pass
        return {"memory_id": memory_id, "status": status}

    repo = state.pref_repo if mtype == "preference" else state.know_repo
    if repo is None:
        raise HTTPException(status_code=503, detail="memory repository not initialized")
    if not repo.update_status(memory_id, status, user_id=user_id):
        raise HTTPException(status_code=409, detail="memory status update failed")
    current = repo.get_by_id(memory_id)
    if current is not None and write_service is not None:
        try:
            write_service.sync_memory(current)
        except Exception:
            pass
    return {"memory_id": memory_id, "status": status}


def _hard_delete_memory(state, memory_id: str, user_id: str) -> dict:
    """物理删除一条记忆（回收站"彻底删除"）：先清运行时索引，再删 SQLite 行。"""
    mtype, memory = _resolve_memory(state, memory_id, user_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")

    write_service = getattr(state, "memory_write_service", None)
    fact_index_service = getattr(state, "fact_index_service", None)
    forget_repo = getattr(state, "forget_repo", None)

    if mtype == "fact":
        fact_store = getattr(state, "fact_store", None)
        if fact_index_service is not None:
            try:
                fact_index_service.sync_fact(memory, remove=True)
            except Exception:
                pass
        if fact_store is not None:
            fact_store.delete_fact_artifacts([memory_id], user_id)
            conn = getattr(fact_store, "_conn", None)
            if conn is not None:
                conn.execute(
                    "DELETE FROM facts WHERE fact_id = ? AND user_id = ?",
                    (memory_id, user_id),
                )
                conn.commit()
            try:
                fact_store.prune_orphan_entities(user_id)
            except Exception:
                pass
    else:
        if write_service is not None:
            try:
                write_service.sync_memory(memory, remove=True)
            except Exception:
                pass
        if forget_repo is not None:
            table = "preferences" if mtype == "preference" else "knowledge"
            forget_repo.delete_memories([memory_id], table)

    cache = getattr(state, "search_cache", None)
    if cache is not None:
        cache.clear()
    return {"memory_id": memory_id, "deleted": True, "hard": True}


def _get_audit_log(request: Request):
    """解析已装配的安全审计日志；未启用/不可用时抛出稳定错误。"""
    gate = getattr(request.app.state, "safety_gate", None)
    if gate is None:
        code = getattr(request.app.state, "safety_gate_error", "") or "safety.gate_unavailable"
        raise HTTPException(status_code=503, detail={"code": code})
    audit_log = getattr(gate, "audit_log", None)
    if audit_log is None:
        raise HTTPException(status_code=503, detail={"code": "safety.audit_disabled"})
    return audit_log


def _get_quarantine_store(request: Request):
    """解析已装配的 REVIEW 隔离区；未启用/不可用时抛出稳定错误。"""
    gate = getattr(request.app.state, "safety_gate", None)
    if gate is None:
        code = getattr(request.app.state, "safety_gate_error", "") or "safety.gate_unavailable"
        raise HTTPException(status_code=503, detail={"code": code})
    store = getattr(gate, "quarantine", None)
    if store is None:
        raise HTTPException(status_code=503, detail={"code": "safety.quarantine_disabled"})
    return store


# ============================================================
# 记忆管理
# ============================================================


@router.patch("/memories/{memory_id}/status")
async def update_memory_status(
    memory_id: str,
    body: MemoryStatusUpdate,
    request: Request,
):
    """单条记忆状态流转（归档/保持/置 active/pending/deleted）。"""
    return _set_memory_status(request.app.state, memory_id, body.user_id, body.status)


@router.post("/memories/status")
async def batch_update_memory_status(body: BatchMemoryStatusUpdate, request: Request):
    """批量记忆状态流转；单条失败不影响其余，逐条给出结果。"""
    results: list[dict[str, Any]] = []
    for mid in body.memory_ids:
        try:
            results.append(_set_memory_status(request.app.state, mid, body.user_id, body.status))
        except HTTPException as exc:
            results.append(
                {
                    "memory_id": mid,
                    "error": {
                        "status_code": exc.status_code,
                        "code": exc.detail if isinstance(exc.detail, str) else exc.detail,
                    },
                }
            )
    applied = sum(1 for item in results if "status" in item)
    return {"results": results, "applied": applied, "total": len(body.memory_ids)}


@router.post("/memories/delete")
async def batch_delete_memories(body: BatchMemoryDelete, request: Request):
    """批量软删除（列表页"勾选 → 删除"），级联清理向量/证据/冲突并记录遗忘历史。"""
    forgetter = _build_forgetter(request.app.state)
    deleted = forgetter.delete_memories(
        body.memory_ids, cascade=body.cascade, user_id=body.user_id
    )
    deleted_ids = list(forgetter._last_deleted_ids)
    record = forgetter.create_audit_log(
        ForgetRequest(
            user_id=body.user_id,
            instruction="[batch delete]",
            target_memory_ids=body.memory_ids,
            cascade=body.cascade,
        ),
        deleted_ids,
    )
    return {
        "deleted_count": deleted,
        "deleted_ids": deleted_ids,
        "record_id": record.record_id,
    }


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    request: Request,
    hard: bool = False,
    user_id: str = "default",
):
    """删除一条记忆。

    hard=false（默认）为软删除（级联清理 + 记录遗忘历史）；
    hard=true 为物理删除（回收站"彻底删除"）。
    """
    if not hard:
        forgetter = _build_forgetter(request.app.state)
        count = forgetter.delete_memories([memory_id], cascade=True, user_id=user_id)
        if count == 0:
            raise HTTPException(status_code=404, detail="memory not found")
        return {"memory_id": memory_id, "deleted": True, "hard": False}
    return _hard_delete_memory(request.app.state, memory_id, user_id)


@router.get("/knowledge/{memory_id}/versions")
async def get_knowledge_versions(
    memory_id: str,
    request: Request,
    user_id: str = "default",
):
    """获取知识记忆的不可变版本历史（快照 + 当前版）。"""
    repo = getattr(request.app.state, "know_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="knowledge repository not initialized")
    return repo.get_version_history(memory_id, user_id=user_id)


@router.get("/memories/health")
async def list_memories_health(
    request: Request,
    user_id: str = "default",
    status: str = "active",
):
    """批量计算偏好/知识/事实记忆的健康度因子（健康度看板数据源）。"""
    state = request.app.state
    if status not in _MEMORY_STATUSES:
        status = "active"
    calc = HealthCalculator()
    items: list[dict[str, Any]] = []

    pref_repo = getattr(state, "pref_repo", None)
    if pref_repo is not None:
        for m in pref_repo.list_all(status=status, user_id=user_id):
            factors = calc.factors_for(m)
            items.append(
                {
                    "memory_id": m.memory_id,
                    "memory_type": "preference",
                    "health_score": round(calc.calculate(m), 4),
                    "time_decay": round(factors.time_decay, 4),
                    "usage_frequency": round(factors.usage_frequency, 4),
                    "stability": m.stability,
                    "access_count_30d": m.access_count_30d,
                    "last_accessed_at": _iso(m.last_accessed_at),
                    "confidence": m.confidence,
                    "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                    "level": m.level.value if hasattr(m.level, "value") else str(m.level),
                }
            )

    know_repo = getattr(state, "know_repo", None)
    if know_repo is not None:
        for m in know_repo.list_all(status=status, user_id=user_id):
            factors = calc.factors_for(m)
            items.append(
                {
                    "memory_id": m.memory_id,
                    "memory_type": "knowledge",
                    "health_score": round(calc.calculate(m), 4),
                    "time_decay": round(factors.time_decay, 4),
                    "usage_frequency": round(factors.usage_frequency, 4),
                    "stability": m.stability,
                    "access_count_30d": m.access_count_30d,
                    "last_accessed_at": _iso(m.last_accessed_at),
                    "confidence": m.confidence,
                    "status": m.status.value if hasattr(m.status, "value") else str(m.status),
                    "level": m.level.value if hasattr(m.level, "value") else str(m.level),
                }
            )

    fact_store = getattr(state, "fact_store", None)
    if fact_store is not None:
        try:
            facts = fact_store.list_facts(status=status, limit=100000, user_id=user_id)
        except (ValueError, TypeError):
            facts = []
        for f in facts:
            factors = calc.factors_for(f)
            items.append(
                {
                    "memory_id": f.fact_id,
                    "memory_type": "fact",
                    "health_score": round(calc.calculate_from_row(f), 4),
                    "time_decay": round(factors.time_decay, 4),
                    "usage_frequency": round(factors.usage_frequency, 4),
                    "stability": 1.0,
                    "access_count_30d": f.access_count_30d,
                    "last_accessed_at": _iso(f.last_accessed_at),
                    "confidence": f.confidence,
                    "status": f.status,
                    "level": None,
                }
            )

    return {"total": len(items), "items": items}


# ============================================================
# 生命周期 / 自动遗忘
# ============================================================


@router.post("/lifecycle/auto-forget")
async def run_auto_forget(request: Request):
    """立即执行一次自动遗忘扫描（按健康度归档/降级/标记待审）。"""
    state = request.app.state
    engine = AutoForgetEngine(
        pref_repo=getattr(state, "pref_repo", None),
        know_repo=getattr(state, "know_repo", None),
        db=getattr(state, "db", None),
        calculator=HealthCalculator(),
        fact_store=getattr(state, "fact_store", None),
        fact_index_service=getattr(state, "fact_index_service", None),
    )
    try:
        return engine.run()
    except Exception:
        raise HTTPException(status_code=503, detail="auto-forget scan failed") from None


@router.post("/lifecycle/check")
async def run_lifecycle_check(request: Request):
    """立即执行一次生命周期检查（晋升/归档）。"""
    state = request.app.state
    manager = LifecycleManager(
        pref_repo=getattr(state, "pref_repo", None),
        know_repo=getattr(state, "know_repo", None),
    )
    try:
        return manager.run_lifecycle_check()
    except Exception:
        raise HTTPException(status_code=503, detail="lifecycle check failed") from None


@router.get("/lifecycle/settings")
async def get_lifecycle_settings():
    """返回健康度权重、自动遗忘阈值、生命周期晋升阈值（只读展示）。"""
    return {
        "health_weights": {"time_decay": 0.6, "usage_frequency": 0.4},
        "auto_forget": {
            "archive_threshold": AutoForgetEngine.ARCHIVE_THRESHOLD,
            "demote_threshold": AutoForgetEngine.DEMOTE_THRESHOLD,
            "review_threshold": AutoForgetEngine.REVIEW_THRESHOLD,
        },
        "lifecycle": {
            "promote_thresholds": LifecycleManager.PROMOTE_THRESHOLDS,
            "demote_thresholds": LifecycleManager.DEMOTE_THRESHOLDS,
            "health_archive_threshold": LifecycleManager.HEALTH_ARCHIVE_THRESHOLD,
        },
    }


# ============================================================
# 事件列表
# ============================================================


@router.get("/events")
async def list_events(
    request: Request,
    user_id: str = "default",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """全量事件列表（分页，新的在前），供事件回放与总览最近事件流。"""
    repo = getattr(request.app.state, "event_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="event repository not initialized")
    total = repo.count(user_id)
    items = [event.model_dump(mode="json") for event in repo.get_recent(user_id, limit=limit, offset=offset)]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ============================================================
# 安全：审计日志 / 隔离区
# ============================================================


@router.get("/safety/audit-logs")
async def list_audit_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """安全处置审计记录分页列表（新的在前，仅含稳定投影，不含命中原文）。"""
    audit_log = _get_audit_log(request)
    try:
        page, total = audit_log.list_records(limit=limit, offset=offset)
    except Exception as exc:
        code = getattr(exc, "code", "audit.list_failed")
        raise HTTPException(status_code=503, detail={"code": code}) from None
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [record.model_dump(mode="json") for record in page],
    }


@router.get("/safety/audit-logs/verify")
async def verify_audit_logs(request: Request):
    """校验审计日志 HMAC 哈希链完整性，返回无敏感摘要。"""
    audit_log = _get_audit_log(request)
    try:
        verification = audit_log.verify()
        return {"valid": True, **verification.model_dump(mode="json")}
    except Exception as exc:
        code = getattr(exc, "code", "audit.verify_failed")
        return {"valid": False, "code": code}


@router.get("/safety/quarantine")
async def list_quarantine(request: Request):
    """REVIEW 隔离区列表（安全元数据，不解密正文）。"""
    store = _get_quarantine_store(request)
    try:
        items, total = store.list_records()
    except Exception as exc:
        code = getattr(exc, "code", "quarantine.list_failed")
        raise HTTPException(status_code=503, detail={"code": code}) from None
    return {"total": total, "items": items}


@router.get("/safety/quarantine/{review_id}")
async def get_quarantine(review_id: str, request: Request):
    """查看一条隔离事件原文（特权审查，解密返回完整事件）。"""
    store = _get_quarantine_store(request)
    try:
        event = store.load(review_id)
    except Exception as exc:
        code = getattr(exc, "code", "quarantine.read_failed")
        status_code = 404 if code == "quarantine.not_found" else 503
        raise HTTPException(status_code=status_code, detail={"code": code}) from None
    return event.model_dump(mode="json")


@router.delete("/safety/quarantine/{review_id}")
async def delete_quarantine(review_id: str, request: Request):
    """删除一条隔离记录。"""
    store = _get_quarantine_store(request)
    try:
        store.delete(review_id)
    except Exception as exc:
        code = getattr(exc, "code", "quarantine.delete_failed")
        status_code = 404 if code == "quarantine.not_found" else 503
        raise HTTPException(status_code=status_code, detail={"code": code}) from None
    return {"deleted": True, "review_id": review_id}


@router.post("/safety/quarantine/{review_id}/release")
async def release_quarantine(
    review_id: str,
    body: QuarantineReleaseRequest,
    request: Request,
):
    """人工裁决隔离事件。

    decision=allow：放行——保存事件并重新送入偏好/知识/事实处理管线，然后删除隔离记录；
    decision=reject：驳回——仅删除隔离记录。
    """
    store = _get_quarantine_store(request)
    try:
        event = store.load(review_id)
    except Exception as exc:
        code = getattr(exc, "code", "quarantine.read_failed")
        status_code = 404 if code == "quarantine.not_found" else 503
        raise HTTPException(status_code=status_code, detail={"code": code}) from None

    result: dict[str, Any] = {
        "review_id": review_id,
        "decision": body.decision,
        "event_id": event.event_id,
    }
    if body.decision == "allow":
        processor = getattr(request.app.state, "event_processor", None)
        event_repo = getattr(request.app.state, "event_repo", None)
        if processor is None or event_repo is None:
            raise HTTPException(status_code=503, detail="event processor not initialized")
        if event_repo.get_by_id(event.event_id) is None:
            event_repo.save(event)
            summary = processor.process([event])
            result["processing"] = summary.model_dump(mode="json")
        else:
            result["processing"] = {"warning": "event already stored, skipped"}

    try:
        store.delete(review_id)
    except Exception as exc:
        code = getattr(exc, "code", "quarantine.delete_failed")
        raise HTTPException(status_code=503, detail={"code": code}) from None
    return result


# ============================================================
# 遗忘历史详情
# ============================================================


@router.get("/forget/history/{record_id}")
async def get_forget_history_detail(
    record_id: str,
    request: Request,
    user_id: str = "default",
):
    """遗忘历史详情：返回遗忘记录 + 被删记忆的当前快照（软删除通常仍可查）。"""
    repo = getattr(request.app.state, "forget_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="forget repository not initialized")
    record = repo.get_by_id(record_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(status_code=404, detail="forget record not found")

    state = request.app.state
    fact_store = getattr(state, "fact_store", None)
    resolved: list[dict[str, Any]] = []
    for mid in record.target_memory_ids:
        mtype, mem = _resolve_memory(state, mid, user_id)
        if mem is None:
            resolved.append(
                {
                    "memory_id": mid,
                    "memory_type": None,
                    "content": None,
                    "note": "deleted permanently",
                }
            )
            continue
        if mtype == "fact":
            content = fact_store.render_fact(mem) if fact_store is not None else ""
            status_value = mem.status
        elif mtype == "preference":
            content = mem.text
            status_value = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
        else:
            content = mem.name
            status_value = mem.status.value if hasattr(mem.status, "value") else str(mem.status)
        resolved.append(
            {
                "memory_id": mid,
                "memory_type": mtype,
                "content": content,
                "status": status_value,
            }
        )

    return {
        "record": record.model_dump(mode="json"),
        "memories": resolved,
    }


# ============================================================
# 系统状态 / 参数（只读、不泄密）
# ============================================================


def _count(db, model, column: str) -> int:
    if db is None:
        return 0
    from sqlalchemy import func

    try:
        with db.session() as session:
            return session.query(func.count(getattr(model, column))).scalar() or 0
    except Exception:
        return 0


@router.get("/system/status")
async def system_status(request: Request):
    """运行态子系统状态总览（后端状态页）。"""
    state = request.app.state
    config = getattr(state, "config", None)
    db = getattr(state, "db", None)

    from memoryhub.storage.models import (
        ConflictRow,
        EventRow,
        ExtractionTaskRow,
        ForgetRow,
        KnowledgeRow,
        PreferenceRow,
    )

    fact_count = 0
    fact_store = getattr(state, "fact_store", None)
    if fact_store is not None:
        try:
            fact_count = len(fact_store.list_facts(status=None, limit=100000))
        except Exception:
            fact_count = 0

    vector_engine = getattr(state, "vector_engine", None)
    vector_store = getattr(state, "vector_store", None)
    retriever = getattr(state, "retriever", None)
    compensation = getattr(state, "compensation_task", None)
    comp_metrics = None
    if compensation is not None:
        metrics = getattr(compensation, "metrics", None)
        if metrics is not None:
            comp_metrics = {
                "total_runs": metrics.total_runs,
                "total_succeeded": metrics.total_succeeded,
                "total_failed": metrics.total_failed,
                "last_run_at": metrics.last_run_at,
                "last_duration_ms": metrics.last_duration_ms,
            }

    return {
        "service": "Kylin-MemoryHub",
        "version": getattr(request.app, "version", "0.1.0"),
        "runtime_mode": config.runtime.mode if config is not None else "unknown",
        "storage": {
            "engine": "sqlite",
            "db_path": config.storage.db_path if config is not None else "",
            "event_count": _count(db, EventRow, "event_id"),
            "preference_count": _count(db, PreferenceRow, "memory_id"),
            "knowledge_count": _count(db, KnowledgeRow, "memory_id"),
            "fact_count": fact_count,
            "conflict_count": _count(db, ConflictRow, "conflict_id"),
            "forget_count": _count(db, ForgetRow, "record_id"),
            "extraction_task_count": _count(db, ExtractionTaskRow, "task_id"),
        },
        "embedding": {
            "provider": config.embedding.provider if config is not None else None,
            "dimension": config.embedding.dimension if config is not None else None,
            "model_name": config.embedding.model_name if config is not None else "",
        },
        "llm": {
            "provider": config.llm.provider if config is not None else None,
            "model": config.llm.model if config is not None else "",
        },
        "vector_engine": {
            "provider": config.vector_engine.provider if config is not None else None,
            "collection": config.vector_engine.collection if config is not None else "",
            "connected": getattr(vector_engine, "_connected", None) if vector_engine is not None else None,
            "vector_count": vector_store.size() if vector_store is not None and hasattr(vector_store, "size") else None,
        },
        "retrieval": {
            "type": type(retriever).__name__ if retriever is not None else None,
            "default_top_k": config.retrieval.default_top_k if config is not None else None,
            "weights": {
                "vector": config.retrieval.vector_weight if config is not None else None,
                "keyword": config.retrieval.keyword_weight if config is not None else None,
                "metadata": config.retrieval.metadata_weight if config is not None else None,
            },
            "cache_ttl_seconds": config.retrieval.cache_ttl_seconds if config is not None else None,
            "compensation": comp_metrics,
        },
        "safety": {
            "gate_available": getattr(state, "safety_gate", None) is not None,
            "gate_error": getattr(state, "safety_gate_error", "") or "",
            "user_rule_service_available": getattr(state, "user_rule_service", None) is not None,
            "rule_set_id": config.safety.rule_set_id if config is not None else None,
            "rule_set_version": config.safety.rule_set_version if config is not None else None,
            "audit_enabled": config.safety.audit.enabled if config is not None else None,
            "quarantine_enabled": config.safety.quarantine.enabled if config is not None else None,
        },
    }


@router.get("/system/config")
async def system_config(request: Request):
    """只读展示非敏感配置（参数查看页）；不暴露 api_key / 密钥。"""
    config = getattr(request.app.state, "config", None)
    if config is None:
        raise HTTPException(status_code=503, detail="config not initialized")

    safety = config.safety
    return {
        "runtime": {
            "mode": config.runtime.mode,
            "allow_fallback": config.runtime.allow_fallback,
        },
        "storage": {
            "db_path": config.storage.db_path,
            "vector_index_path": config.storage.vector_index_path,
            "evidence_path": config.storage.evidence_path,
            "cache_max_size": config.storage.cache_max_size,
        },
        "retrieval": {
            "default_top_k": config.retrieval.default_top_k,
            "candidate_multiplier": config.retrieval.candidate_multiplier,
            "vector_weight": config.retrieval.vector_weight,
            "keyword_weight": config.retrieval.keyword_weight,
            "metadata_weight": config.retrieval.metadata_weight,
            "rerank_enabled": config.retrieval.rerank_enabled,
            "cache_ttl_seconds": config.retrieval.cache_ttl_seconds,
            "target_p95_ms": config.retrieval.target_p95_ms,
            "target_p99_ms": config.retrieval.target_p99_ms,
        },
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "api_base": config.llm.api_base,
        },
        "embedding": {
            "provider": config.embedding.provider,
            "dimension": config.embedding.dimension,
            "model_name": config.embedding.model_name,
        },
        "vector_engine": {
            "provider": config.vector_engine.provider,
            "host": config.vector_engine.host,
            "port": config.vector_engine.port,
            "collection": config.vector_engine.collection,
            "dimension": config.vector_engine.dimension,
            "search_timeout_ms": config.vector_engine.search_timeout_ms,
        },
        "extraction_retry": {
            "enabled": config.extraction_retry.enabled,
            "interval_seconds": config.extraction_retry.interval_seconds,
            "batch_size": config.extraction_retry.batch_size,
        },
        "knowledge_merge": {
            "equivalent_threshold": config.knowledge_merge.equivalent_threshold,
            "conflict_threshold": config.knowledge_merge.conflict_threshold,
        },
        "safety": {
            "rule_set_id": safety.rule_set_id,
            "rule_set_version": safety.rule_set_version,
            "auto_mask": safety.auto_mask,
            "policy": {
                "policy_id": safety.policy.policy_id,
                "version": safety.policy.version,
                "fallback_action": safety.policy.fallback_action.value,
                "on_scan_error": safety.policy.on_scan_error.value,
                "on_unmaskable": safety.policy.on_unmaskable.value,
                "fail_closed": safety.policy.fail_closed,
            },
            "audit": {
                "enabled": safety.audit.enabled,
                "directory": safety.audit.directory,
                "retention_days": safety.audit.retention_days,
            },
            "quarantine": {
                "enabled": safety.quarantine.enabled,
                "directory": safety.quarantine.directory,
                "retention_days": safety.quarantine.retention_days,
            },
            "user_rules": {
                "enabled": safety.user_rules.enabled,
                "max_rules_per_user": safety.user_rules.max_rules_per_user,
                "allow_advanced_regex": safety.user_rules.allow_advanced_regex,
            },
        },
        "debug": config.debug,
    }
