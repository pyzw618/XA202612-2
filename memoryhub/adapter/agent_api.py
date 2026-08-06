"""竞赛演示用 Agent 适配层。

前端只把回放和用户裁决交给这里；真正的 MemoryHub 写操作由本层执行。
后续接入真实 Agent 时可保持同一前端 transport。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from memoryhub.adapter.schemas import (
    ForgetRequest,
    MemoryEvent,
    SceneScope,
    SearchRequest,
)
from memoryhub.core.forget import MemoryForgetter

router = APIRouter(prefix="/api/agent", tags=["agent-adapter"])


class ReplayRequest(BaseModel):
    schema_version: str = "conversation-replay/1.0"
    session_id: str = ""
    turns: list[dict[str, Any]] = Field(default_factory=list)
    events: list[MemoryEvent] = Field(default_factory=list)
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
    events: list[MemoryEvent] = Field(default_factory=list)


def _events_from_replay(body: ReplayRequest) -> list[MemoryEvent]:
    events = list(body.events)
    for turn in body.turns:
        for raw_event in turn.get("events", []):
            events.append(MemoryEvent.model_validate(raw_event))
    return events


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

    safe_events, warnings = processor.sanitize(body.events)
    new_events = [event for event in safe_events if repo.get_by_id(event.event_id) is None]
    repo.batch_save(safe_events)
    processing = processor.process(new_events)
    processing.warnings = [*warnings, *processing.warnings]

    user_id = safe_events[0].user_id if safe_events else "demo_user"
    response = retriever.search(
        SearchRequest(
            user_id=user_id,
            query=body.retrieval_query or body.user_message,
            context=SceneScope(scene=body.scene, task_type=body.task_type),
            top_k=8,
            memory_types=["preference", "knowledge"],
        )
    )
    cards = []
    for result in response.results:
        memory = retriever.memory_lookup.get(result.memory_id)
        if memory is None:
            continue
        is_preference = getattr(memory, "memory_type", "") == "preference"
        title = getattr(memory, "text", "") if is_preference else getattr(memory, "name", "")
        summary = getattr(memory, "text", "") if is_preference else getattr(memory, "content", "")
        scope = getattr(memory, "scope", SceneScope()).model_dump(mode="json")
        level = getattr(getattr(memory, "level", ""), "value", getattr(memory, "level", ""))
        knowledge_type = getattr(getattr(memory, "knowledge_type", ""), "value", getattr(memory, "knowledge_type", ""))
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
                "scope": scope,
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
    fact_proposals = []
    fact_pipeline = getattr(request.app.state, "fact_pipeline", None)
    if fact_pipeline is not None:
        fact_proposals = [
            record
            for proposal_id in processing.fact_proposal_ids
            if (record := fact_pipeline.store.get_proposal(proposal_id)) is not None
        ]
    generated_tool_calls = [
        {
            "call_id": f"{body.turn_id}_memory_search",
            "tool_name": "memory_search",
            "arguments": {"query": body.retrieval_query or body.user_message, "top_k": 8},
            "result": {"candidate_ids": [card["memory_id"] for card in cards], "used_ids": used_ids},
            "status": "success",
            "sequence": 900,
            "latency_ms": response.latency_ms,
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
        "retrieval_latency_ms": response.latency_ms,
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
        pipeline = getattr(request.app.state, "fact_pipeline", None)
        if pipeline is None:
            raise HTTPException(status_code=503, detail="fact pipeline not initialized")
        record = pipeline.store.get_proposal(action_id)
        if record is None:
            raise HTTPException(status_code=404, detail="fact proposal not found")

        if body.action_type == "fact_reject":
            if record["status"] == "committed":
                raise HTTPException(status_code=409, detail="committed proposal cannot be rejected")
            pipeline.store.update_proposal(
                action_id,
                status="rejected",
                rejection_reason=body.payload.get("reason", body.decision),
            )
            return {"action_id": action_id, "status": "rejected"}

        if record["status"] == "committed":
            return record["result"]
        proposal = pipeline.load_proposal(action_id)
        try:
            result = pipeline.commit(
                proposal,
                scope=body.payload.get("scope", "global"),
                project_id=body.payload.get("project_id"),
                resolution=body.payload.get("resolution") or None,
                force=bool(body.payload.get("force", False)),
                auto_resolve=False,
                apply_on_escalate=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        requires_decision = result.relation == "CONFLICT" and result.resolution == "escalate"
        response = {
            "proposal_id": action_id,
            "status": "awaiting_decision" if requires_decision else "committed",
            "requires_decision": requires_decision,
            "relation": result.relation,
            "resolution": result.resolution,
            "reason": result.reason,
            "fact": asdict(result.new_fact),
            "existing_fact": asdict(result.existing_fact) if result.existing_fact else None,
        }
        pipeline.store.update_proposal(
            action_id,
            status=response["status"],
            result=response,
        )
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
