"""vNext Forget state machine.

Authority is the read boundary: a successful request writes a DELETED
tombstone before any disposable projection is touched.  Projection cleanup is
therefore retryable and can never make a forgotten memory readable again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from memoryhub.adapter.vnext_schemas import ForgetRequest, ForgetResponse, ForgetStatus
from memoryhub.domain.contracts import EvolutionStatus
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import ForgetRow, MemoryProjectionOutboxRow


class ForgetState(str, Enum):
    ACCEPTED = "ACCEPTED"
    READ_BLOCKED = "READ_BLOCKED"
    CLEARING_PROJECTIONS = "CLEARING_PROJECTIONS"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


@dataclass(frozen=True)
class ForgetExecution:
    response: ForgetResponse
    state: ForgetState
    outbox_ids: tuple[str, ...] = ()


class ForgetService:
    """Execute, inspect and retry tenant-scoped Forget requests."""

    def __init__(
        self,
        db: Database,
        authority: AuthorityRepository | None = None,
        outbox: MemoryProjectionOutboxRepository | None = None,
        trace_store: Any | None = None,
    ) -> None:
        self.db = db
        self.authority = authority or AuthorityRepository(db)
        self.outbox = outbox or MemoryProjectionOutboxRepository(db)
        self.trace_store = trace_store

    def execute(
        self,
        request: ForgetRequest,
        *,
        actor_id: str | None = None,
        high_risk_authorized: bool = False,
    ) -> ForgetExecution:
        high_risk = self._is_high_risk(request)
        if not request.dry_run and high_risk and not high_risk_authorized:
            self._record_trace(request, (), "DENIED", high_risk)
            raise PermissionError("forget.high_risk_authorization_required")
        existing = self._idempotent(request)
        if existing is not None:
            self._record_trace(
                request, existing.response.affected_memory_ids, "IDEMPOTENT", high_risk
            )
            return existing
        target_ids = self._resolve_targets(request)
        if request.dry_run:
            response = self._response(request, "ACCEPTED", "ACCEPTED", "ACCEPTED", target_ids)
            self._record_trace(request, target_ids, "DRY_RUN", high_risk)
            return ForgetExecution(response, ForgetState.ACCEPTED)

        record_id = "forget_" + uuid.uuid4().hex
        outbox_ids: list[str] = []
        with self.db.session() as session:
            row = ForgetRow(
                record_id=record_id,
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                state=ForgetState.ACCEPTED.value,
                actor_id=actor_id or request.user_id,
                reason=request.instruction or "explicit forget",
                instruction=request.instruction,
                target_memory_ids=target_ids,
                affected_memory_ids=[],
                warnings=[],
                deleted_count=0,
            )
            session.add(row)
            session.flush()
            affected: list[str] = []
            for memory_id in target_ids:
                envelope = self.authority.get(
                    tenant_id=request.tenant_id,
                    user_id=request.user_id,
                    memory_id=memory_id,
                    include_inactive=True,
                )
                if envelope is None or envelope.evolution_status is EvolutionStatus.DELETED:
                    continue
                tombstone = envelope.model_copy(
                    update={
                        "content_version": envelope.content_version + 1,
                        "evolution_status": EvolutionStatus.DELETED,
                        "valid_to": datetime.now(timezone.utc),
                        "updated_by": actor_id or request.user_id,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
                self.authority.save(tombstone, session=session)
                affected.append(memory_id)
                projection_type = (
                    "preference" if envelope.memory_type.value == "PREFERENCE" else "knowledge"
                )
                outbox_ids.append(
                    self.outbox.enqueue(
                        memory_id=memory_id,
                        memory_type=projection_type,
                        operation="delete",
                        payload={
                            "memory_id": memory_id,
                            "memory_type": envelope.memory_type.value,
                            "operation": "delete",
                            "forget_request_id": record_id,
                        },
                        session=session,
                        tenant_id=request.tenant_id,
                        user_id=request.user_id,
                        content_version=tombstone.content_version,
                        priority=100,
                    ).outbox_id
                )
            row.state = ForgetState.READ_BLOCKED.value
            row.affected_memory_ids = affected
            row.target_memory_ids = target_ids
            row.deleted_count = len(affected)
            row.warnings = (
                [] if len(affected) == len(target_ids) else ["some targets were not active"]
            )
        response = self._response(
            request,
            ForgetState.READ_BLOCKED.value,
            ForgetState.CLEARING_PROJECTIONS.value if outbox_ids else ForgetState.VERIFIED.value,
            ForgetState.VERIFYING.value if outbox_ids else ForgetState.VERIFIED.value,
            target_ids,
            record_id=record_id,
            residual=0,
            warnings=[] if len(outbox_ids) == len(target_ids) else ["some targets were not active"],
        )
        self._record_trace(request, target_ids, "SUCCEEDED", high_risk)
        return ForgetExecution(response, ForgetState.READ_BLOCKED, tuple(outbox_ids))

    def _record_trace(
        self,
        request: ForgetRequest,
        memory_ids: list[str] | tuple[str, ...],
        outcome: str,
        high_risk: bool,
    ) -> None:
        if self.trace_store is None:
            return
        self.trace_store.record_forget(
            trace_id=request.request_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            request_id=request.request_id,
            memory_ids=list(memory_ids),
            outcome=outcome,
            high_risk=high_risk,
        )

    def get(self, record_id: str, *, tenant_id: str, user_id: str) -> ForgetExecution | None:
        with self.db.session() as session:
            row = (
                session.query(ForgetRow)
                .filter(
                    ForgetRow.record_id == record_id,
                    ForgetRow.tenant_id == tenant_id,
                    ForgetRow.user_id == user_id,
                )
                .one_or_none()
            )
            if row is not None:
                self._refresh_row(session, row)
            return None if row is None else self._execution_from_row(row)

    def list(self, *, tenant_id: str, user_id: str, limit: int = 50) -> list[ForgetExecution]:
        with self.db.session() as session:
            rows = (
                session.query(ForgetRow)
                .filter(ForgetRow.tenant_id == tenant_id, ForgetRow.user_id == user_id)
                .order_by(ForgetRow.created_at.desc())
                .limit(max(1, min(limit, 200)))
                .all()
            )
            for row in rows:
                self._refresh_row(session, row)
            return [self._execution_from_row(row) for row in rows]

    def _refresh_row(self, session, row: ForgetRow) -> None:
        """Advance only after every durable projection delete has succeeded."""
        if row.state not in {
            ForgetState.READ_BLOCKED.value,
            ForgetState.CLEARING_PROJECTIONS.value,
            ForgetState.VERIFYING.value,
        }:
            return
        ids = list(row.affected_memory_ids or row.target_memory_ids or [])
        if not ids:
            row.state = ForgetState.VERIFIED.value
            return
        pending = session.query(MemoryProjectionOutboxRow).filter(
            MemoryProjectionOutboxRow.tenant_id == row.tenant_id,
            MemoryProjectionOutboxRow.user_id == row.user_id,
            MemoryProjectionOutboxRow.memory_id.in_(ids),
            MemoryProjectionOutboxRow.operation == "delete",
            MemoryProjectionOutboxRow.status != "succeeded",
        ).count()
        if pending == 0:
            row.state = ForgetState.VERIFIED.value

    def _resolve_targets(self, request: ForgetRequest) -> list[str]:
        if request.target_memory_ids:
            return list(dict.fromkeys(request.target_memory_ids))
        values = self.authority.list(tenant_id=request.tenant_id, user_id=request.user_id)
        if request.normalized_key:
            values = [item for item in values if item.normalized_key == request.normalized_key]
        if request.scope:
            values = [
                item
                for item in values
                if item.scope == request.scope and item.scope_level is request.scope_level
            ]
        return [item.memory_id for item in values]

    @staticmethod
    def _is_high_risk(request: ForgetRequest) -> bool:
        return bool(
            request.scope
            or request.normalized_key
            or request.instruction
            or len(request.target_memory_ids) > 1
        )

    def _idempotent(self, request: ForgetRequest) -> ForgetExecution | None:
        with self.db.session() as session:
            row = (
                session.query(ForgetRow)
                .filter(
                    ForgetRow.tenant_id == request.tenant_id,
                    ForgetRow.user_id == request.user_id,
                    ForgetRow.idempotency_key == request.idempotency_key,
                )
                .one_or_none()
            )
            if row is not None:
                self._refresh_row(session, row)
            return None if row is None else self._execution_from_row(row)

    def _execution_from_row(self, row: ForgetRow) -> ForgetExecution:
        state = ForgetState(row.state or ForgetState.ACCEPTED.value)
        response = self._response(
            type("Request", (), {"request_id": row.request_id or row.record_id})(),
            state.value,
            state.value,
            state.value,
            list(row.target_memory_ids or []),
            record_id=row.record_id,
            residual=0,
            warnings=list(row.warnings or []),
        )
        return ForgetExecution(response, state)

    @staticmethod
    def _response(
        request: Any,
        authority: str,
        projection: str,
        verification: str,
        ids: list[str],
        *,
        record_id: str | None = None,
        residual: int = 0,
        warnings: list[str] | None = None,
    ) -> ForgetResponse:
        return ForgetResponse(
            request_id=request.request_id,
            forget_request_id=record_id or request.request_id,
            authority_status=ForgetStatus(authority),
            projection_status=ForgetStatus(projection),
            verification_status=ForgetStatus(verification),
            residual_retrieval_count=residual,
            affected_memory_ids=ids,
            warnings=warnings or [],
        )


__all__ = ["ForgetExecution", "ForgetService", "ForgetState"]
