"""Read-only provenance and projection management API v2."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from memoryhub.adapter.api import search_memory
from memoryhub.adapter.schemas import SearchRequest
from memoryhub.storage.memory_metadata import (
    MemoryEvidenceRepository,
    MemoryLineageRepository,
    MemoryProjectionOutboxRepository,
)

router = APIRouter(prefix="/api/memory/v2", tags=["memory-v2"])


class ProjectionReplayRequest(BaseModel):
    """Replay only caller-owned failed projections; no business memory is rewritten."""

    user_id: str = Field(min_length=1)
    outbox_ids: list[str] | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _resolve_memory(state, memory_id: str, user_id: str):
    pref_repo = getattr(state, "pref_repo", None)
    know_repo = getattr(state, "know_repo", None)
    fact_store = getattr(state, "fact_store", None)
    if pref_repo is not None:
        memory = pref_repo.get_by_id(memory_id)
        if memory is not None and memory.user_id == user_id:
            return "preference", memory
    if know_repo is not None:
        memory = know_repo.get_by_id(memory_id)
        if memory is not None and memory.user_id == user_id:
            return "knowledge", memory
    if fact_store is not None:
        fact = fact_store.get_fact(memory_id, user_id=user_id)
        if fact is not None:
            return "fact", fact
    return None, None


def _owned_or_404(state, memory_id: str, user_id: str):
    memory_type, memory = _resolve_memory(state, memory_id, user_id)
    if memory is None:
        raise HTTPException(status_code=404, detail={"code": "memory.not_found"})
    return memory_type, memory


def _safe_evidence_excerpt(source_type: str) -> str:
    """Never expose stored source text through management APIs."""
    return f"[{source_type or 'unknown'}] sanitized evidence"


def _get_audit_log(state):
    gate = getattr(state, "safety_gate", None)
    audit_log = getattr(gate, "audit_log", None) if gate is not None else None
    if audit_log is None:
        raise HTTPException(status_code=503, detail={"code": "safety.audit_disabled"})
    return audit_log


@router.get("/memories/{memory_id}/lineage")
async def get_lineage(memory_id: str, request: Request, user_id: str = Query(..., min_length=1)):
    state = request.app.state
    memory_type, memory = _owned_or_404(state, memory_id, user_id)
    repo = MemoryLineageRepository(state.db)
    rows = repo.list_for_memory(memory_id, memory_type)
    return {
        "memory_id": memory_id,
        "memory_type": memory_type,
        "items": [
            {
                "lineage_id": row.lineage_id,
                "parent_memory_id": row.parent_memory_id,
                "root_memory_id": row.root_memory_id,
                "semantic_version": row.semantic_version,
                "evidence_revision": row.evidence_revision,
                "transition_action": row.transition_action,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ],
    }


@router.get("/memories/{memory_id}/evidence")
async def get_evidence(memory_id: str, request: Request, user_id: str = Query(..., min_length=1)):
    state = request.app.state
    memory_type, _ = _owned_or_404(state, memory_id, user_id)
    if memory_type == "fact":
        rows = state.fact_store.list_fact_evidence(memory_id, user_id)
        return {
            "memory_id": memory_id,
            "memory_type": "fact",
            "items": [
                {
                    "evidence_id": row["evidence_id"],
                    "event_id": row.get("event_id", ""),
                    "source_hash": row.get("source_hash", ""),
                    "source_type": "fact_source",
                    "excerpt": _safe_evidence_excerpt("fact_source"),
                    "occurred_at": row.get("observed_at"),
                    "safety_audit_id": row.get("safety_audit_id") or None,
                }
                for row in rows
            ],
        }
    repo = MemoryEvidenceRepository(state.db)
    rows = repo.list_for_memory(memory_id, memory_type)
    return {
        "memory_id": memory_id,
        "memory_type": memory_type,
        "items": [
            {
                "evidence_id": row.evidence_id,
                "event_id": row.event_id,
                "source_hash": row.source_hash,
                "source_type": row.source_type,
                "excerpt": _safe_evidence_excerpt(row.source_type),
                "occurred_at": _iso(row.occurred_at),
                "quality_score": row.quality_score,
                "safety_audit_id": row.safety_audit_id,
            }
            for row in rows
        ],
    }


@router.get("/memories/{memory_id}/audit")
async def get_audit(memory_id: str, request: Request, user_id: str = Query(..., min_length=1)):
    state = request.app.state
    memory_type, _ = _owned_or_404(state, memory_id, user_id)
    if memory_type == "fact":
        audit_ids = {
            str(row.get("safety_audit_id", "") or "")
            for row in state.fact_store.list_fact_evidence(memory_id, user_id)
        }
    else:
        evidence_repo = MemoryEvidenceRepository(state.db)
        audit_ids = {
            str(row.safety_audit_id or "")
            for row in evidence_repo.list_for_memory(memory_id, memory_type)
        }
    audit_ids.discard("")
    audit_log = _get_audit_log(state)
    records, _ = audit_log.list_records(limit=500, offset=0)
    return {
        "memory_id": memory_id,
        "memory_type": memory_type,
        "items": [
            {
                "audit_id": record.audit_id,
                "event_id": record.event_id,
                "created_at": _iso(record.created_at),
                "decision": record.decision.value,
                "reason_codes": list(record.reason_codes),
                "finding_count": record.finding_count,
                "redaction_count": record.redaction_count,
            }
            for record in records
            if record.audit_id in audit_ids
        ],
    }


@router.get("/projections")
async def list_projections(
    request: Request,
    user_id: str = Query(..., min_length=1),
    status: str = Query("pending", pattern="^(pending|failed)$"),
    limit: int = Query(100, ge=1, le=500),
):
    state = request.app.state
    repo = MemoryProjectionOutboxRepository(state.db)
    rows = repo.list_by_status((status,), limit=500)
    items = []
    for row in rows:
        _, memory = _resolve_memory(state, row.memory_id, user_id)
        if memory is None:
            continue
        items.append(
            {
                "outbox_id": row.outbox_id,
                "memory_id": row.memory_id,
                "memory_type": row.memory_type,
                "operation": row.operation,
                "payload_hash": row.payload_hash,
                "status": row.status,
                "attempts": row.attempts,
                "next_retry_at": _iso(row.next_retry_at),
                "error_code": row.error_code,
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
            }
        )
    return {"status": status, "items": items[:limit]}


@router.post("/projections/replay")
async def replay_projections(body: ProjectionReplayRequest, request: Request):
    state = request.app.state
    repo = MemoryProjectionOutboxRepository(state.db)
    failed = repo.list_by_status(("failed",), limit=500)
    requested = set(body.outbox_ids or [])
    owned_ids = []
    for row in failed:
        if requested and row.outbox_id not in requested:
            continue
        _, memory = _resolve_memory(state, row.memory_id, body.user_id)
        if memory is not None:
            owned_ids.append(row.outbox_id)
    requeued = repo.replay(owned_ids)
    return {"requeued": requeued, "outbox_ids": owned_ids}


@router.get("/search")
async def search_with_provenance(
    request: Request,
    user_id: str = Query(..., min_length=1),
    query: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=50),
    include_provenance: bool = False,
):
    """GET retrieval compatibility endpoint with optional safe provenance references."""
    response = await search_memory(
        SearchRequest(user_id=user_id, query=query, top_k=top_k), request
    )
    body = response.model_dump(mode="json")
    if not include_provenance:
        return body

    state = request.app.state
    lineage_repo = MemoryLineageRepository(state.db)
    evidence_repo = MemoryEvidenceRepository(state.db)
    provenance: dict[str, dict] = {}
    for result in response.results:
        memory_type, memory = _resolve_memory(state, result.memory_id, user_id)
        if memory is None:
            continue
        if memory_type == "fact":
            evidence = state.fact_store.list_fact_evidence(result.memory_id, user_id)
            provenance[result.memory_id] = {
                "memory_type": "fact",
                "lineage_count": 0,
                "evidence_count": len(evidence),
                "audit_ids": sorted(
                    {
                        str(item.get("safety_audit_id", "") or "")
                        for item in evidence
                    }
                    - {""}
                ),
            }
            continue
        lineage = lineage_repo.list_for_memory(result.memory_id, memory_type)
        evidence = evidence_repo.list_for_memory(result.memory_id, memory_type)
        provenance[result.memory_id] = {
            "memory_type": memory_type,
            "lineage_count": len(lineage),
            "evidence_count": len(evidence),
            "audit_ids": sorted(
                {str(item.safety_audit_id or "") for item in evidence} - {""}
            ),
        }
    body["provenance"] = provenance
    return body
