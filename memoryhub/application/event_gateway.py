"""vNext Event Gateway: policy/identity/scope/idempotency before commit."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from sqlalchemy.exc import IntegrityError

from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.storage.database import Database
from memoryhub.storage.models import EventRow, IdempotencyRecordRow


class GatewayStatus(str, Enum):
    COMMITTED = "COMMITTED"
    IDEMPOTENT = "IDEMPOTENT"
    CONFLICT = "CONFLICT"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class EventGatewayResult:
    status: GatewayStatus
    event_id: str
    trace_id: str
    action: str
    idempotency_record_id: str | None = None
    reason_code: str = ""


PolicyProcessor = Callable[[MemoryEventContract], MemoryEventContract]
AuthorizationCheck = Callable[[MemoryEventContract], bool]


class EventGateway:
    """Persist only a policy-approved event and its deduplication metadata.

    The gateway deliberately stops at the Event/Idempotency commit. Working,
    Episode, Candidate and Long-Term writes are downstream canonical services;
    this prevents the ingress from becoming a second business state machine.
    """

    def __init__(
        self,
        db: Database,
        *,
        policy: PolicyProcessor,
        identity_check: AuthorizationCheck | None = None,
        scope_check: AuthorizationCheck | None = None,
    ) -> None:
        self.db = db
        if not callable(policy):
            raise ValueError("event gateway requires a policy processor")
        self.policy = policy
        self.identity_check = identity_check or (lambda event: True)
        self.scope_check = scope_check or (lambda event: True)

    def submit(self, event: MemoryEventContract) -> EventGatewayResult:
        """Run the ordered gateway pipeline and return a safe status only."""
        if not isinstance(event, MemoryEventContract):
            raise TypeError("event gateway requires MemoryEventContract")
        if not self._authorized(self.identity_check, event):
            return self._blocked(event, GatewayStatus.REJECTED, "identity_rejected")
        if not self._authorized(self.scope_check, event):
            return self._blocked(event, GatewayStatus.REJECTED, "scope_rejected")

        try:
            governed = self.policy(event)
        except Exception:
            return self._blocked(event, GatewayStatus.REJECTED, "policy_failed")
        if not isinstance(governed, MemoryEventContract):
            return self._blocked(event, GatewayStatus.REJECTED, "policy_invalid_result")
        if (governed.tenant_id, governed.user_id) != (event.tenant_id, event.user_id):
            return self._blocked(event, GatewayStatus.REJECTED, "policy_identity_changed")

        action = governed.policy_action
        if action == "REVIEW":
            return self._blocked(
                governed, GatewayStatus.REVIEW, "policy_review", action=action
            )
        if action == "DROP":
            return self._blocked(
                governed, GatewayStatus.REJECTED, "policy_drop", action=action
            )
        if action not in {"ALLOW", "MASK"}:
            return self._blocked(
                governed, GatewayStatus.REJECTED, "policy_action_invalid", action=action
            )
        if action == "MASK" and governed.payload == event.payload:
            return self._blocked(
                event,
                GatewayStatus.REJECTED,
                "policy_mask_not_sanitized",
                action=action,
            )

        request_hash = self._request_hash(event)
        record_id = self._idempotency_record_id(event, request_hash)
        reconcile_existing_event = False
        try:
            with self.db.session() as session:
                existing = (
                    session.query(IdempotencyRecordRow)
                    .filter_by(
                        tenant_id=event.tenant_id,
                        idempotency_key=event.idempotency_key,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    return self._existing_result(
                        existing,
                        event=event,
                        request_hash=request_hash,
                        action=action,
                    )

                # Event IDs are the table primary key, therefore the conflict
                # check must use the same global scope as the database constraint.
                event_exists = (
                    session.query(EventRow)
                    .filter_by(event_id=event.event_id)
                    .one_or_none()
                )
                if event_exists is not None:
                    if (
                        event_exists.tenant_id == event.tenant_id
                        and event_exists.idempotency_key == event.idempotency_key
                    ):
                        # SQLite can expose a newer commit in a second-table
                        # read while this Session still has the first table's
                        # snapshot. Reconcile after this Session closes.
                        reconcile_existing_event = True
                    else:
                        return EventGatewayResult(
                            status=GatewayStatus.CONFLICT,
                            event_id=event.event_id,
                            trace_id=event.trace_id,
                            action=action,
                            reason_code="event_id_conflict",
                        )

                if not reconcile_existing_event:
                    session.add(self._event_row(governed))
                    session.add(
                        IdempotencyRecordRow(
                            idempotency_record_id=record_id,
                            tenant_id=event.tenant_id,
                            user_id=event.user_id,
                            idempotency_key=event.idempotency_key,
                            request_hash=request_hash,
                            status="COMMITTED",
                            event_id=event.event_id,
                            trace_id=event.trace_id,
                        )
                    )
                    session.flush()
        except IntegrityError:
            # Two processes may pass the read-before-write checks together.
            # Re-read after rollback and turn the unique-key race into the same
            # deterministic idempotent/conflict result as a sequential retry.
            return self._resolve_commit_race(
                event=event,
                request_hash=request_hash,
                action=action,
            )
        if reconcile_existing_event:
            return self._resolve_commit_race(
                event=event,
                request_hash=request_hash,
                action=action,
            )

        return EventGatewayResult(
            status=GatewayStatus.COMMITTED,
            event_id=event.event_id,
            trace_id=event.trace_id,
            action=action,
            idempotency_record_id=record_id,
        )

    @staticmethod
    def _authorized(check: AuthorizationCheck, event: MemoryEventContract) -> bool:
        try:
            return check(event) is True
        except Exception:
            return False

    @staticmethod
    def _blocked(
        event: MemoryEventContract,
        status: GatewayStatus,
        reason_code: str,
        *,
        action: str | None = None,
    ) -> EventGatewayResult:
        return EventGatewayResult(
            status=status,
            event_id=event.event_id,
            trace_id=event.trace_id,
            action=action or event.policy_action,
            reason_code=reason_code,
        )

    @staticmethod
    def _existing_result(
        existing: IdempotencyRecordRow,
        *,
        event: MemoryEventContract,
        request_hash: str,
        action: str,
    ) -> EventGatewayResult:
        if existing.request_hash == request_hash and existing.event_id == event.event_id:
            return EventGatewayResult(
                status=GatewayStatus.IDEMPOTENT,
                event_id=event.event_id,
                trace_id=event.trace_id,
                action=action,
                idempotency_record_id=existing.idempotency_record_id,
            )
        return EventGatewayResult(
            status=GatewayStatus.CONFLICT,
            event_id=event.event_id,
            trace_id=event.trace_id,
            action=action,
            idempotency_record_id=existing.idempotency_record_id,
            reason_code="idempotency_conflict",
        )

    def _resolve_commit_race(
        self,
        *,
        event: MemoryEventContract,
        request_hash: str,
        action: str,
    ) -> EventGatewayResult:
        with self.db.session() as session:
            existing = (
                session.query(IdempotencyRecordRow)
                .filter_by(
                    tenant_id=event.tenant_id,
                    idempotency_key=event.idempotency_key,
                )
                .one_or_none()
            )
            if existing is not None:
                return self._existing_result(
                    existing,
                    event=event,
                    request_hash=request_hash,
                    action=action,
                )
            event_exists = (
                session.query(EventRow).filter_by(event_id=event.event_id).one_or_none()
            )
            if event_exists is not None:
                return EventGatewayResult(
                    status=GatewayStatus.CONFLICT,
                    event_id=event.event_id,
                    trace_id=event.trace_id,
                    action=action,
                    reason_code="event_id_conflict",
                )
        raise RuntimeError("event gateway commit race could not be reconciled")

    @staticmethod
    def _request_hash(event: MemoryEventContract) -> str:
        # created_at/updated_at are local model metadata and are not persisted
        # in EventRow.  Excluding them keeps worker rehydration idempotent while
        # retaining the complete governed payload and identity in the hash.
        data = event.model_dump(mode="json")
        data.pop("created_at", None)
        data.pop("updated_at", None)
        serialized = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @classmethod
    def _idempotency_record_id(cls, event: MemoryEventContract, request_hash: str) -> str:
        value = f"{event.tenant_id}:{event.idempotency_key}:{request_hash}"
        return "idem_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:48]

    @staticmethod
    def _event_row(event: MemoryEventContract) -> EventRow:
        return EventRow(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            source_type=event.source_type,
            event_type=event.event_type,
            user_id=event.user_id,
            session_id=event.session_id,
            task_type=event.task_id,
            occurred_at=event.occurred_at,
            payload=dict(event.payload),
            schema_version=event.schema_version,
            content_version=event.content_version,
            policy_version=event.policy_version,
            retention_class=event.retention_class,
            sensitivity_level=event.sensitivity_level,
            policy_action=event.policy_action,
            idempotency_key=event.idempotency_key,
            trace_id=event.trace_id,
            source_hash=event.source_hash,
        )


__all__ = ["EventGateway", "EventGatewayResult", "GatewayStatus"]
