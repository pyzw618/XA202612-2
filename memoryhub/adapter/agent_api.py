"""竞赛演示用 Agent 适配层（临时重建，贴合 main 稳定后端）。

前端只把回放和用户裁决交给这里；真正的 MemoryHub 写操作由本层执行。
本文件是便于前端联调重建的临时适配层，复用 memoryhub 的 app.state 服务。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from memoryhub.adapter.schemas import (
    ForgetRequest,
    MemoryEvent,
    SceneScope,
    SearchRequest,
)
from memoryhub.core.forget import MemoryForgetter

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
        ids = [
            row.memory_id
            for row in s.query(PreferenceRow).filter(PreferenceRow.user_id == user_id).all()
        ]
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

    # 事实（含事实冲突/证据），演示用户的相关记录一并清掉
    fact_store = getattr(request.app.state, "fact_store", None)
    if fact_store is not None:
        try:
            facts = fact_store.list_facts(status=None, limit=100000, user_id=user_id)
            fact_ids = [fact.fact_id for fact in facts]
            counts["facts"] = len(fact_ids)
            fact_store.delete_fact_artifacts(fact_ids, user_id)
            conn = getattr(fact_store, "_conn", None)
            if conn is not None:
                if fact_ids:
                    placeholders = ",".join("?" for _ in fact_ids)
                    conn.execute(
                        f"DELETE FROM facts WHERE user_id = ? AND fact_id IN ({placeholders})",
                        [user_id, *fact_ids],
                    )
                    conn.commit()
                conn.execute(
                    "DELETE FROM fact_conflicts WHERE user_id = ?", (user_id,)
                )
                conn.commit()
        except Exception:
            counts["facts"] = 0

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

    # 清理进程内的事实候选裁决暂存区
    _FACT_PENDING.clear()
    return {"deleted": counts, "user_id": user_id}

# 进程内 fact 候选暂存区：proposal_id -> {"json": <dict>, "candidate": <FactCandidate>}
# 便于前端 FactDialog 裁决（main 后端本身是自动 commit，无候选存储）
_FACT_PENDING: dict[str, dict[str, Any]] = {}


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
    scene: str = "chat"
    task_type: str = "memory_demo"
    # 用 dict 而非 MemoryEvent，以便在构造时归一化旧演示数据的 source_type 枚举
    events: list[dict[str, Any]] = Field(default_factory=list)


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
            detail=f"event {data.get('event_id', '?')} invalid: {exc.error_count()} validation error(s)",
        ) from exc


def _events_from_replay(body: ReplayRequest) -> list[MemoryEvent]:
    events = [_normalize_event(ev) for ev in body.events]
    for turn in body.turns:
        for raw_event in turn.get("events", []):
            events.append(_normalize_event(raw_event))
    return events


def _candidate_to_json(proposal: Any) -> dict[str, Any]:
    """把 FactCandidate 序列化为前端 FactCard 需要的结构。"""
    raw = proposal.raw_triple
    admission = proposal.admission
    return {
        "proposal_id": proposal.proposal_id,
        "subject": getattr(raw, "subject_text", ""),
        "predicate": getattr(raw, "predicate_text", ""),
        "object": getattr(raw, "object_text", ""),
        "evidence": getattr(raw, "evidence", ""),
        "confidence": float(getattr(raw, "confidence", 0) or 0),
        "admission_reason": admission.reason if hasattr(admission, "reason") else "",
        "suggested_scope": proposal.scope_hint or "project",
        "status": "proposed",
        "source_id": proposal.source_id,
        "metadata": dict(proposal.metadata or {}),
    }


@router.post("/replay")
async def replay_conversation(body: ReplayRequest, request: Request):
    if body.schema_version != "conversation-replay/1.0":
        raise HTTPException(status_code=422, detail="unsupported replay schema_version")
    events = _events_from_replay(body)
    processor = getattr(request.app.state, "event_processor", None)
    if processor is None:
        raise HTTPException(status_code=503, detail="event processor not initialized")
    safe_events, warnings = processor.sanitize(events)

    processing = None
    written_event_ids: list[str] = []
    if body.execute:
        repo = getattr(request.app.state, "event_repo", None)
        if repo is None:
            raise HTTPException(status_code=503, detail="event repository not initialized")
        new_events = [event for event in safe_events if repo.get_by_id(event.event_id) is None]
        repo.batch_save(safe_events)
        processing = processor.process(new_events)
        processing.warnings = [*warnings, *processing.warnings]
        written_event_ids = [event.event_id for event in new_events]

    session_id = body.session_id or (safe_events[0].session_id if safe_events else "")
    return {
        "schema_version": body.schema_version,
        "session_id": session_id,
        "read_only": not body.execute,
        "events": [event.model_dump(mode="json") for event in safe_events],
        "written_event_ids": written_event_ids,
        "used_memory_ids": body.used_memory_ids,
        "processing": processing.model_dump(mode="json") if processing else None,
        "warnings": warnings if processing is None else processing.warnings,
    }


@router.post("/step")
async def execute_agent_step(body: AgentStepRequest, request: Request):
    """Execute one scripted turn against the real event and retrieval pipeline."""
    processor = getattr(request.app.state, "event_processor", None)
    repo = getattr(request.app.state, "event_repo", None)
    retriever = getattr(request.app.state, "retriever", None)
    if processor is None or repo is None or retriever is None:
        raise HTTPException(status_code=503, detail="agent runtime not initialized")

    events = [_normalize_event(ev) for ev in body.events]
    safe_events, warnings = processor.sanitize(events)
    new_events = [event for event in safe_events if repo.get_by_id(event.event_id) is None]
    repo.batch_save(safe_events)
    processing = processor.process(new_events)
    processing.warnings = [*warnings, *processing.warnings]

    user_id = safe_events[0].user_id if safe_events else "demo_user"
    search_response = retriever.search(
        SearchRequest(
            user_id=user_id,
            query=body.retrieval_query or body.user_message,
            context=SceneScope(scene=body.scene, task_type=body.task_type),
            top_k=8,
            memory_types=["preference", "knowledge"],
        )
    )
    cards = []
    for result in search_response.results:
        memory = getattr(retriever, "memory_lookup", {}).get(result.memory_id)
        if memory is None:
            continue
        is_preference = getattr(memory, "memory_type", "") == "preference"
        title = getattr(memory, "text", "") if is_preference else getattr(memory, "name", "")
        summary = getattr(memory, "text", "") if is_preference else getattr(memory, "content", "")
        scope = getattr(memory, "scope", SceneScope())
        scope_json = scope.model_dump(mode="json") if hasattr(scope, "model_dump") else {"scope": str(scope)}
        level = getattr(getattr(memory, "level", ""), "value", getattr(memory, "level", ""))
        knowledge_type = getattr(
            getattr(memory, "knowledge_type", ""), "value", getattr(memory, "knowledge_type", "")
        )
        cards.append(
            {
                "memory_id": result.memory_id,
                "memory_type": "preference" if is_preference else "knowledge",
                "knowledge_type": knowledge_type or None,
                "title": title or "记忆",
                "summary": summary or result.content,
                "relevance": result.score,
                "source": result.source or "MemoryHub",
                "level": level or "long",
                "scope": scope_json,
                "tags": list(getattr(memory, "tags", [])),
            }
        )
    used_ids = [card["memory_id"] for card in cards[:3]]

    summary_lines = []
    if processing.preferences_written:
        summary_lines.append(f"写入 {len(processing.preferences_written)} 条偏好记忆")
    if processing.knowledge_written:
        summary_lines.append(f"写入 {len(processing.knowledge_written)} 条知识记忆")
    if processing.fact_proposal_ids:
        summary_lines.append(f"生成 {len(processing.fact_proposal_ids)} 条事实候选")
    summary_lines.append(f"实际检索到 {len(cards)} 条记忆，使用 {len(used_ids)} 条")

    # fact 候选：把 processing 暂存的候选注册到进程内裁决暂存区
    fact_proposals = []
    cached_candidates = getattr(processor, "_fact_candidates", None) or []
    for proposal in cached_candidates:
        if proposal.proposal_id in processing.fact_proposal_ids:
            json_repr = _candidate_to_json(proposal)
            _FACT_PENDING[proposal.proposal_id] = {"json": json_repr, "candidate": proposal}
            fact_proposals.append(json_repr)

    generated_tool_calls = [
        {
            "call_id": f"{body.turn_id}_memory_search",
            "tool_name": "memory_search",
            "arguments": {"query": body.retrieval_query or body.user_message, "top_k": 8},
            "result": {"candidate_ids": [card["memory_id"] for card in cards], "used_ids": used_ids},
            "status": "success",
            "sequence": 900,
            "latency_ms": int(search_response.latency_ms),
        }
    ]
    if processing.preferences_written or processing.knowledge_written:
        generated_tool_calls.insert(0, {
            "call_id": f"{body.turn_id}_memory_extract",
            "tool_name": "memory_extract",
            "arguments": {"event_ids": [event.event_id for event in new_events]},
            "result": {
                "preference_ids": processing.preferences_written,
                "knowledge_ids": processing.knowledge_written,
            },
            "status": "success",
            "sequence": 899,
            "latency_ms": 0,
        })
    if fact_proposals:
        generated_tool_calls.append({
            "call_id": f"{body.turn_id}_fact_propose",
            "tool_name": "fact_propose",
            "arguments": {"source_event_ids": [event.event_id for event in new_events]},
            "result": {"proposal_ids": processing.fact_proposal_ids},
            "status": "success",
            "sequence": 901,
            "latency_ms": 0,
        })

    return {
        "session_id": body.session_id,
        "turn_id": body.turn_id,
        "executed": True,
        "written_event_ids": [event.event_id for event in new_events],
        "processing": processing.model_dump(mode="json"),
        "candidate_memories": cards,
        "used_memory_ids": used_ids,
        "fact_proposals": fact_proposals,
        "tool_calls": generated_tool_calls,
        "write_summary": summary_lines,
        "retrieval_latency_ms": int(search_response.latency_ms),
        "warnings": processing.warnings,
    }


@router.post("/actions/{action_id}/decision")
async def decide_agent_action(
    action_id: str,
    body: AgentDecisionRequest,
    request: Request,
):
    """接收用户裁决，由 Agent 适配层执行相应 MemoryHub 操作。"""
    if body.action_type in {"fact_commit", "fact_reject"}:
        staged = _FACT_PENDING.get(action_id)
        pipeline = getattr(request.app.state, "fact_pipeline", None)
        if pipeline is None:
            raise HTTPException(status_code=503, detail="fact pipeline not initialized")

        # 从暂存区取回候选（含 FactCandidate 对象）
        if staged is None:
            raise HTTPException(status_code=404, detail="fact proposal not found")
        proposal = staged["candidate"]

        if body.action_type == "fact_reject":
            staged["json"]["status"] = "rejected"
            return {"action_id": action_id, "status": "rejected"}

        try:
            result = pipeline.commit(
                proposal,
                scope=body.payload.get("scope") or proposal.scope_hint or "global",
                project_id=body.payload.get("project_id") or proposal.project_id_hint,
                resolution=body.payload.get("resolution") or None,
                force=bool(body.payload.get("force", False)),
                auto_resolve=False,
                user_id=body.payload.get("user_id", "default"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        requires_decision = result.relation == "CONFLICT" and result.resolution == "escalate"
        # 幂等：重复提交同一候选时（DUPLICATE）返回已存储的事实，而不是新构建的临时 fact
        duplicate = result.relation == "DUPLICATE"
        stored_fact = (
            result.existing_fact if duplicate and result.existing_fact else result.new_fact
        )
        response = {
            "proposal_id": action_id,
            "status": "awaiting_decision" if requires_decision else "committed",
            "requires_decision": requires_decision,
            "relation": result.relation,
            "resolution": result.resolution,
            "reason": result.reason,
            "fact": asdict(stored_fact) if stored_fact is not None else None,
            "existing_fact": asdict(result.existing_fact) if getattr(result, "existing_fact", None) else None,
        }
        _FACT_PENDING[action_id]["json"]["status"] = response["status"]
        return response

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