"""竞赛演示用 Agent 适配层（临时重建，贴合 main 稳定后端）。

前端只把回放和用户裁决交给这里；真正的 MemoryHub 写操作由本层执行。
本文件是便于前端联调重建的临时适配层，复用 memoryhub 的 app.state 服务。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from memoryhub.adapter.api import _to_memory_event_contract
from memoryhub.adapter.schemas import (
    EventProcessingSummary,
    ForgetRequest,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    SceneScope,
    SearchRequest,
)
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.event_gateway import GatewayStatus
from memoryhub.core.forget import MemoryForgetter
from memoryhub.domain.contracts import MemoryScope

router = APIRouter(prefix="/api/agent", tags=["agent-adapter"])

# 根路径健康检查：React 前端 api.ts 探测 `/api/health`（不带 /agent 前缀）
root_router = APIRouter(prefix="/api", tags=["agent-adapter"])


@router.get("/health")
async def health_check():
    """临时健康检查：供前端探测后端在线状态。"""
    return {"status": "ok"}


@root_router.get("/health")
async def root_health_check():
    """根路径健康检查别名：供 React 前端探测后端在线状态。"""
    return {
        "status": "ok",
        "service": "Kylin-MemoryHub",
        "version": "0.1.0",
    }


@router.delete("/preferences")
async def clear_preferences(request: Request, user_id: str = "default"):
    """清空指定用户的偏好记忆（演示用：前端“清空演示数据”/载入演示时调用）。

    只清 preferences 表，不影响知识/事实等其他记忆。
    同时清理向量索引中这些偏好的条目，避免检索返回已删除的“幽灵”结果。
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="backend database not initialized")
    from memoryhub.storage.database import PreferenceRow

    with db.session() as s:
        deleted = (
            s.query(PreferenceRow)
            .filter(PreferenceRow.user_id == user_id)
            .delete(synchronize_session=False)
        )

    # 同步清理向量索引：演示适配层会把偏好写入向量库，仅删当前偏好 ID
    # 无法清掉历史轮次的“幽灵”，因此直接清空整个向量库（演示数据，安全）。
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is not None:
        try:
            all_ids = list(getattr(vector_store, "reverse_map", {}).keys())
            if all_ids:
                vector_store.batch_delete(all_ids)
        except Exception:
            pass
    return {"deleted": deleted, "user_id": user_id}


@router.delete("/demo-data")
async def clear_demo_data(request: Request, user_id: str = "default"):
    """清空指定用户的全部演示数据（偏好/知识/事实/事件/冲突/遗忘记录/向量索引）。

    前端“载入全新演示会话”时调用，避免上一轮演示提交的事实、沉淀的知识
    残留在 SQLite / 向量库中，导致 facts 页出现“幽灵”事实。
    """
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="backend database not initialized")
    from memoryhub.storage.models import (
        ConflictRow,
        EventRow,
        ExtractionTaskRow,
        ForgetRow,
        KnowledgeRow,
        KnowledgeVersionRow,
        PreferenceRow,
    )

    counts: dict[str, int] = {}
    with db.session() as s:
        for name, model in [
            ("preferences", PreferenceRow),
            ("knowledge", KnowledgeRow),
            ("knowledge_versions", KnowledgeVersionRow),
            ("events", EventRow),
            ("conflicts", ConflictRow),
            ("forget_history", ForgetRow),
            ("extraction_tasks", ExtractionTaskRow),
        ]:
            counts[name] = s.query(model).filter(model.user_id == user_id).delete(
                synchronize_session=False
            )

    # 清空向量索引与进程内检索投影，避免检索返回已删除的“幽灵”记忆
    vector_store = getattr(request.app.state, "vector_store", None)
    if vector_store is not None:
        try:
            all_ids = list(getattr(vector_store, "reverse_map", {}).keys())
            if all_ids:
                vector_store.batch_delete(all_ids)
                vector_store.save()
        except Exception:
            pass
    memory_lookup = getattr(request.app.state, "memory_lookup", None)
    if memory_lookup is not None:
        try:
            memory_lookup.clear()
        except Exception:
            pass
    keyword_search = getattr(request.app.state, "keyword_search", None)
    if keyword_search is not None:
        try:
            keyword_search.build_index([])
        except Exception:
            pass
    search_cache = getattr(request.app.state, "search_cache", None)
    if search_cache is not None:
        try:
            search_cache.clear()
        except Exception:
            pass

    return {"deleted": counts, "user_id": user_id}


class ReplayRequest(BaseModel):
    schema_version: str = "conversation-replay/1.0"
    session_id: str = ""
    turns: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    execute: bool = False
    used_memory_ids: list[str] = Field(default_factory=list)


class AgentDecisionRequest(BaseModel):
    action_type: Literal[
        "fact_commit",
        "fact_reject",
        "conflict_resolve",
        "forget_commit",
    ]
    decision: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentStepRequest(BaseModel):
    session_id: str
    turn_id: str
    user_message: str
    retrieval_query: str = ""
    project_id: str = ""
    task_id: str = ""
    scene: str = "chat"
    task_type: str = "memory_demo"
    # 用 dict 而非 MemoryEvent，以便在构造时归一化旧演示数据的 source_type 枚举
    events: list[dict[str, Any]] = Field(default_factory=list)
    used_memory_ids: list[str] = Field(default_factory=list)


_SOURCE_TYPE_ALIASES = {
    "chat": "user_behavior",
    "user": "user_behavior",
    "manual": "manual_config",
}


def _normalize_event(raw: dict[str, Any]) -> MemoryEvent:
    """把演示事件 dict 归一化为 main 后端接受的 MemoryEvent。"""
    data = dict(raw or {})
    st = str(data.get("source_type") or "")
    mapped = _SOURCE_TYPE_ALIASES.get(st, st)
    if mapped:
        data["source_type"] = mapped
    if not data.get("user_id"):
        data["user_id"] = "default"
    if not data.get("occurred_at"):
        data["occurred_at"] = ""
    try:
        return MemoryEvent.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"event {data.get('event_id', '?')} invalid: "
                f"{exc.error_count()} validation error(s)"
            ),
        ) from exc


def _events_from_replay(body: ReplayRequest) -> list[MemoryEvent]:
    events = [_normalize_event(ev) for ev in body.events]
    for turn in body.turns:
        for raw_event in turn.get("events", []):
            events.append(_normalize_event(raw_event))
    return events


@router.post("/replay")
async def replay_conversation(body: ReplayRequest, request: Request):
    if body.schema_version != "conversation-replay/1.0":
        raise HTTPException(status_code=422, detail="unsupported replay schema_version")
    events = _events_from_replay(body)
    processor = getattr(request.app.state, "event_processor", None)
    canonical = getattr(request.app.state, "canonical_write_service", None)
    if canonical is None:
        raise HTTPException(status_code=503, detail="canonical write service not initialized")
    if processor is not None:
        safe_events, warnings = processor.sanitize(events)
    else:
        safe_events = events
        warnings = []

    written_event_ids: list[str] = []
    committed_events: list[MemoryEvent] = []
    processing: EventProcessingSummary | None = None
    replay_tenant_id = request.headers.get("X-MemoryHub-Tenant", "default")
    if body.execute:
        for event in safe_events:
            result = canonical.write(_to_memory_event_contract(event, tenant_id=replay_tenant_id))
            if result.status == GatewayStatus.COMMITTED:
                written_event_ids.append(event.event_id)
                committed_events.append(event)
        if processor is not None and committed_events:
            processing = processor.process(committed_events)

    session_id = body.session_id or (safe_events[0].session_id if safe_events else "")
    retrieval_results: dict[str, Any] | None = None
    retrieval_service = getattr(request.app.state, "retrieval_service", None)
    rollout = getattr(request.app.state, "rollout_read_service", None)
    query = next(
        (
            str(turn.get("retrieval_query") or turn.get("user_message") or "")
            for turn in reversed(body.turns)
            if turn.get("retrieval_query") or turn.get("user_message")
        ),
        safe_events[-1].text if safe_events else "",
    )
    if retrieval_service is not None and rollout is not None and query:
        tenant_id = request.headers.get("X-MemoryHub-Tenant", "default")
        retrieval_request = MemoryRetrievalRequest(
            request_id=f"agent-replay-{session_id or 'session'}-{hash(query) & 0xFFFFFFFF:08x}",
            tenant_id=tenant_id,
            user_id=safe_events[-1].user_id if safe_events else "default",
            query=query,
            session_id=session_id,
            page_size=8,
        )
        selected = rollout.read(
            retrieval_request,
            legacy_reader=lambda _request: None,
            vnext_reader=lambda value: retrieval_service.search(value),
        )
        retrieval_results = {
            "response": selected.response.model_dump(mode="json")
            if hasattr(selected.response, "model_dump")
            else selected.response,
            "served": getattr(selected, "served_by", "vnext"),
        }
    return {
        "schema_version": body.schema_version,
        "session_id": session_id,
        "read_only": not body.execute,
        "events": [event.model_dump(mode="json") for event in safe_events],
        "written_event_ids": written_event_ids,
        "used_memory_ids": body.used_memory_ids,
        "processing": processing.model_dump(mode="json") if processing else None,
        "retrieval": retrieval_results,
        "served": retrieval_results["served"] if retrieval_results else "vnext",
        "warnings": warnings,
    }


@router.post("/step")
async def execute_agent_step(body: AgentStepRequest, request: Request):
    """Execute one scripted turn against the real event and retrieval pipeline."""
    processor = getattr(request.app.state, "event_processor", None)
    canonical = getattr(request.app.state, "canonical_write_service", None)
    legacy_retriever = getattr(request.app.state, "retriever", None)
    retrieval_service = getattr(request.app.state, "retrieval_service", None)
    rollout = getattr(request.app.state, "rollout_read_service", None)
    if canonical is None:
        raise HTTPException(status_code=503, detail="canonical write service not initialized")
    if retrieval_service is None or rollout is None:
        raise HTTPException(status_code=503, detail="retrieval service not initialized")

    events = [_normalize_event(ev) for ev in body.events]
    if processor is not None:
        safe_events, warnings = processor.sanitize(events)
    else:
        safe_events = events
        warnings = []

    if canonical is None:
        raise HTTPException(status_code=503, detail="canonical write service not initialized")
    user_id = safe_events[0].user_id if safe_events else "demo_user"
    step_tenant_id = request.headers.get("X-MemoryHub-Tenant", "default")
    written_event_ids: list[str] = []
    committed_events: list[MemoryEvent] = []
    processing: EventProcessingSummary | None = None
    for event in safe_events:
        result = canonical.write(
            _to_memory_event_contract(
                event,
                tenant_id=step_tenant_id,
                project_id=body.project_id,
                task_id=body.task_id,
                session_id=body.session_id,
            )
        )
        if result.status == GatewayStatus.COMMITTED:
            written_event_ids.append(event.event_id)
            committed_events.append(event)
    if processor is not None and committed_events:
        processing = processor.process(committed_events)
    legacy_request = SearchRequest(
        user_id=user_id,
        query=body.retrieval_query or body.user_message,
        context=SceneScope(scene=body.scene, task_type=body.task_type),
        project_id=body.project_id,
        session_id=body.session_id,
        top_k=8,
        memory_types=["preference", "knowledge"],
    )
    vnext_request = MemoryRetrievalRequest(
        request_id=f"agent-step-{user_id}-{hash(legacy_request.query) & 0xFFFFFFFF:08x}",
        tenant_id=step_tenant_id,
        user_id=user_id,
        query=legacy_request.query,
        task_id=body.task_id,
        session_id=body.session_id,
        scope_level=(MemoryScope.PROJECT if body.project_id else None),
        scope=(f"PROJECT:{body.project_id}" if body.project_id else ""),
        page_size=legacy_request.top_k,
    )
    selected = rollout.read(
        vnext_request,
        legacy_reader=lambda _request: (
            legacy_retriever.search(legacy_request)
            if legacy_retriever is not None
            else None
        ),
        vnext_reader=lambda value: retrieval_service.search(value),
    )
    vnext_search_response = selected.response
    retrieval_log_id = getattr(vnext_search_response, "retrieval_log_id", "")
    if hasattr(vnext_search_response, "to_legacy_search_response"):
        search_response = vnext_search_response.to_legacy_search_response()
        selected_memories = vnext_search_response.selected_memories
    else:
        # Small compatibility surface for adapter-level test doubles and
        # explicit legacy rollback modes; production vNext returns the DTO
        # above and never enters this branch.
        search_response = vnext_search_response
        selected_memories = []
    cards = []
    for item in selected_memories:
        content = dict(item.content or {})
        memory_type = getattr(item.memory_type, "value", str(item.memory_type)).lower()
        is_preference = memory_type == "preference"
        title = content.get("name", item.memory_id) if not is_preference else content.get("text", "")
        summary = content.get("text", "") if is_preference else content.get("content", "")
        if not summary:
            summary = content.get("object_value", "") or content.get("source_text", "")
        scope_json = {"scope": item.scope, "scope_level": item.scope_level.value}
        level = getattr(item.layer, "value", str(item.layer)).lower()
        knowledge_type = content.get("knowledge_type", "")
        cards.append(
            {
                "memory_id": item.memory_id,
                "memory_type": "preference" if is_preference else "knowledge",
                "knowledge_type": knowledge_type or None,
                "title": title or "记忆",
                "summary": summary or "",
                "relevance": item.score,
                "source": "+".join(item.source_ids) or "MemoryHub",
                "level": level or "long",
                "scope": scope_json,
                "tags": list(content.get("tags", [])),
            }
        )
    # Missing explicit usage evidence must remain IN_CONTEXT, not be guessed
    # from ranking position.
    used_ids = list(body.used_memory_ids)

    if retrieval_service is not None and retrieval_log_id and used_ids:
        retrieval_service.record_usage_feedback(
            retrieval_id=retrieval_log_id,
            memory_ids=used_ids,
            tenant_id=step_tenant_id,
            user_id=user_id,
            task_id=body.task_id,
            session_id=body.session_id,
            usage_source="agent.step",
            confidence=1.0 if body.used_memory_ids else 0.5,
        )

    summary_lines = []
    summary_lines.append(f"实际检索到 {len(cards)} 条记忆，使用 {len(used_ids)} 条")

    fact_proposals = []

    generated_tool_calls = [
        {
            "call_id": f"{body.turn_id}_memory_search",
            "tool_name": "memory_search",
            "arguments": {"query": body.retrieval_query or body.user_message, "top_k": 8},
            "result": {
                "candidate_ids": [card["memory_id"] for card in cards],
                "used_ids": used_ids,
            },
            "status": "success",
            "sequence": 900,
            "latency_ms": int(search_response.latency_ms),
        }
    ]

    return {
        "session_id": body.session_id,
        "turn_id": body.turn_id,
        "executed": True,
        "written_event_ids": written_event_ids,
        "processing": processing.model_dump(mode="json") if processing else None,
        "candidate_memories": cards,
        "used_memory_ids": used_ids,
        "fact_proposals": fact_proposals,
        "tool_calls": generated_tool_calls,
        "write_summary": summary_lines,
        "retrieval_latency_ms": int(search_response.latency_ms),
        "served": getattr(selected, "served_by", "vnext"),
        "warnings": warnings,
    }


@router.post("/actions/{action_id}/decision")
async def decide_agent_action(
    action_id: str,
    body: AgentDecisionRequest,
    request: Request,
):
    """接收用户裁决，由 Agent 适配层执行相应 MemoryHub 操作。"""
    if body.action_type == "fact_reject":
        return {"action_id": action_id, "status": "rejected"}

    if body.action_type == "fact_commit":
        write_service = getattr(request.app.state, "memory_write_service", None)
        if write_service is None:
            raise HTTPException(status_code=503, detail="memory write service not initialized")
        payload = body.payload or {}
        user_id = str(payload.get("user_id", "default"))
        memory = KnowledgeMemory(
            user_id=user_id,
            knowledge_type=KnowledgeType.FACT,
            subject=str(payload.get("subject") or payload.get("subject_text") or ""),
            predicate=str(payload.get("predicate") or payload.get("predicate_text") or ""),
            object_value=str(payload.get("object") or payload.get("object_text") or ""),
            object_type=str(payload.get("object_type") or ""),
        )
        write_service.upsert_memory(memory, skip_write_gate=True)
        return {
            "action_id": action_id,
            "status": "committed",
            "fact": memory.model_dump(mode="json"),
        }

    if body.action_type == "conflict_resolve":
        repo = getattr(request.app.state, "conflict_repo", None)
        if repo is None:
            raise HTTPException(status_code=503, detail="conflict repository not initialized")
        try:
            result = repo.resolve(
                action_id,
                body.decision,
                body.payload.get("reason", ""),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        return {"action_id": action_id, "status": "resolved", "result": result}

    forgetter = MemoryForgetter(
        llm_client=getattr(request.app.state, "llm_client", None),
        storage=getattr(request.app.state, "db", None),
        vector_store=getattr(request.app.state, "vector_store", None),
        cache=getattr(request.app.state, "retriever", None),
        pref_repo=getattr(request.app.state, "pref_repo", None),
        know_repo=getattr(request.app.state, "know_repo", None),
    )
    scope_data = body.payload.get("target_scope")
    forget_request = ForgetRequest(
        user_id=body.payload.get("user_id", "default"),
        instruction=body.payload.get("instruction", ""),
        target_memory_ids=body.payload.get("target_memory_ids", []),
        target_scope=SceneScope(**scope_data) if scope_data else None,
        cascade=body.payload.get("cascade", True),
    )
    result = forgetter.execute(forget_request)
    return {
        "action_id": action_id,
        "status": "committed",
        "result": result.model_dump(mode="json"),
    }
