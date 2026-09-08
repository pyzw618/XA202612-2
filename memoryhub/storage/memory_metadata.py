"""Authoritative SQLite repositories for memory lineage, evidence, and projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from random import random
from typing import Any

from sqlalchemy.orm import Session

from memoryhub.adapter.schemas import Evidence, MemoryProvenance, SourceType, canonical_sha256
from memoryhub.storage.database import Database
from memoryhub.storage.models import (
    MemoryEvidenceRow,
    MemoryLineageRow,
    MemoryProjectionOutboxRow,
)


@dataclass(frozen=True, slots=True)
class MemoryLineageView:
    """Detached authoritative lineage record for API and service reads."""

    lineage_id: str
    memory_id: str
    memory_type: str
    parent_memory_id: str | None
    root_memory_id: str | None
    semantic_version: int
    evidence_revision: int
    transition_action: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryEvidenceView:
    """Detached authoritative evidence record for API and service reads."""

    evidence_id: str
    memory_id: str
    memory_type: str
    event_id: str
    source_hash: str
    source_type: str
    excerpt: str
    occurred_at: datetime
    quality_score: float
    safety_audit_id: str | None


class MemoryLineageRepository:
    """Append-only access to authoritative memory version relationships."""

    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        memory_id: str,
        memory_type: str,
        parent_memory_id: str | None,
        root_memory_id: str | None,
        semantic_version: int,
        transition_action: str,
        session: Session,
        tenant_id: str | None = None,
        user_id: str | None = None,
        content_version: int = 1,
        schema_version: str = "vnext/v1",
        policy_version: str | None = None,
    ) -> MemoryLineageRow:
        previous = (
            session.query(MemoryLineageRow)
            .filter(
                MemoryLineageRow.memory_id == memory_id,
                MemoryLineageRow.memory_type == memory_type,
            )
            .order_by(MemoryLineageRow.evidence_revision.desc())
            .first()
        )
        evidence_revision = 1 if previous is None else previous.evidence_revision + 1
        root_id = root_memory_id or (previous.root_memory_id if previous else None) or memory_id
        lineage_id = "lineage_" + canonical_sha256(
            {
                "memory_id": memory_id,
                "memory_type": memory_type,
                "semantic_version": max(1, semantic_version),
                "evidence_revision": evidence_revision,
                "transition_action": transition_action,
                "parent_memory_id": parent_memory_id or "",
                "root_memory_id": root_id,
            }
        )[:48]
        row = MemoryLineageRow(
            lineage_id=lineage_id,
            memory_id=memory_id,
            memory_type=memory_type,
            tenant_id=tenant_id,
            user_id=user_id,
            parent_memory_id=parent_memory_id or None,
            root_memory_id=root_id,
            semantic_version=max(1, semantic_version),
            content_version=max(1, int(content_version)),
            schema_version=schema_version,
            policy_version=policy_version,
            evidence_revision=evidence_revision,
            transition_action=transition_action,
        )
        session.add(row)
        return row

    def list_for_memory(
        self, memory_id: str, memory_type: str
    ) -> list[MemoryLineageView]:
        with self.db.session() as session:
            rows = (
                session.query(MemoryLineageRow)
                .filter(
                    MemoryLineageRow.memory_id == memory_id,
                    MemoryLineageRow.memory_type == memory_type,
                )
                .order_by(
                    MemoryLineageRow.semantic_version.asc(),
                    MemoryLineageRow.evidence_revision.asc(),
                    MemoryLineageRow.created_at.asc(),
                )
                .all()
            )
            return [
                MemoryLineageView(
                    lineage_id=row.lineage_id,
                    memory_id=row.memory_id,
                    memory_type=row.memory_type,
                    parent_memory_id=row.parent_memory_id,
                    root_memory_id=row.root_memory_id,
                    semantic_version=row.semantic_version,
                    evidence_revision=row.evidence_revision,
                    transition_action=row.transition_action,
                    created_at=row.created_at,
                )
                for row in rows
            ]


class MemoryEvidenceRepository:
    """Deduplicated authoritative memory evidence repository."""

    def __init__(self, db: Database):
        self.db = db

    def record_all(
        self,
        *,
        memory_id: str,
        memory_type: str,
        evidences: list[Evidence],
        provenance: MemoryProvenance,
        session: Session,
        tenant_id: str | None = None,
        user_id: str | None = None,
        content_version: int = 1,
        schema_version: str = "vnext/v1",
        policy_version: str | None = None,
        sensitivity_level: str | None = None,
    ) -> list[str]:
        source_items = evidences or [
            Evidence(
                event_id=provenance.event_id,
                content="",
                source_type=provenance.source_type,
            )
        ]
        evidence_ids: list[str] = []
        for evidence in source_items:
            event_id = evidence.event_id or provenance.event_id
            source_hash = self._source_hash(evidence, provenance)
            row = (
                session.query(MemoryEvidenceRow)
                .filter(
                    MemoryEvidenceRow.memory_id == memory_id,
                    MemoryEvidenceRow.event_id == event_id,
                    MemoryEvidenceRow.source_hash == source_hash,
                )
                .first()
            )
            if row is None:
                row = MemoryEvidenceRow(
                    evidence_id="evidence_"
                    + canonical_sha256(
                        {
                            "memory_id": memory_id,
                            "event_id": event_id,
                            "source_hash": source_hash,
                        }
                    )[:48],
                    memory_id=memory_id,
                    memory_type=memory_type,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    event_id=event_id,
                    source_hash=source_hash,
                    source_type=self._source_type(evidence, provenance).value,
                    schema_version=schema_version,
                    content_version=max(1, int(content_version)),
                    policy_version=policy_version,
                    sensitivity_level=sensitivity_level,
                    excerpt=(evidence.content or "")[:1000],
                    occurred_at=evidence.timestamp or datetime.now(),
                    quality_score=max(0.0, min(1.0, float(evidence.weight))),
                    safety_audit_id=provenance.safety_audit_id,
                )
                session.add(row)
            evidence_ids.append(row.evidence_id)
        return evidence_ids

    @staticmethod
    def _source_hash(evidence: Evidence, provenance: MemoryProvenance) -> str:
        if evidence.event_id in ("", provenance.event_id):
            return provenance.source_hash
        return canonical_sha256(
            {
                "event_id": evidence.event_id,
                "source_type": str(evidence.source_type),
                "excerpt": evidence.content,
                "timestamp": evidence.timestamp.isoformat(),
            }
        )

    @staticmethod
    def _source_type(evidence: Evidence, provenance: MemoryProvenance) -> SourceType:
        value = evidence.source_type or provenance.source_type
        return value if isinstance(value, SourceType) else SourceType(value)

    def list_for_memory(
        self, memory_id: str, memory_type: str
    ) -> list[MemoryEvidenceView]:
        with self.db.session() as session:
            rows = (
                session.query(MemoryEvidenceRow)
                .filter(
                    MemoryEvidenceRow.memory_id == memory_id,
                    MemoryEvidenceRow.memory_type == memory_type,
                )
                .order_by(MemoryEvidenceRow.occurred_at.asc(), MemoryEvidenceRow.evidence_id.asc())
                .all()
            )
            return [
                MemoryEvidenceView(
                    evidence_id=row.evidence_id,
                    memory_id=row.memory_id,
                    memory_type=row.memory_type,
                    event_id=row.event_id,
                    source_hash=row.source_hash,
                    source_type=row.source_type,
                    excerpt=row.excerpt,
                    occurred_at=row.occurred_at,
                    quality_score=float(row.quality_score),
                    safety_audit_id=row.safety_audit_id,
                )
                for row in rows
            ]




@dataclass(frozen=True, slots=True)
class ProjectionOutboxItem:
    """Detached outbox lease returned to a projection worker."""

    outbox_id: str
    tenant_id: str | None
    user_id: str | None
    memory_id: str
    memory_type: str
    operation: str
    event_id: str | None
    content_version: int
    payload_hash: str
    attempts: int
    lease_token: str
    lease_version: int
    priority: int
    max_attempts: int
    backoff_policy: dict[str, Any]

    def backoff_delay(self, attempts: int | None = None) -> int:
        """Compute next retry delay in seconds from the backoff policy."""
        policy = self.backoff_policy or {}
        base = max(1, int(policy.get("base_delay_seconds", 5)))
        max_delay = max(base, int(policy.get("max_delay_seconds", 3600)))
        jitter = bool(policy.get("jitter", False))
        exponent = min(max(0, (attempts if attempts is not None else self.attempts) - 1), 10)
        delay = min(max_delay, base * (2**exponent))
        if jitter:
            delay = int(delay * (0.5 + random()))
        return max(1, delay)


@dataclass(frozen=True, slots=True)
class ProjectionOutboxView:
    """Detached outbox status projection for management APIs and diagnostics."""

    outbox_id: str
    tenant_id: str | None
    user_id: str | None
    memory_id: str
    memory_type: str
    operation: str
    event_id: str | None
    content_version: int
    payload_hash: str
    status: str
    attempts: int
    max_attempts: int
    priority: int
    next_retry_at: datetime | None
    error_code: str
    lease_token: str | None
    lease_version: int
    lease_expires_at: datetime | None
    dead_lettered_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _default_backoff_policy() -> dict[str, Any]:
    return {
        "base_delay_seconds": 5,
        "max_delay_seconds": 3600,
        "jitter": False,
    }


class MemoryProjectionOutboxRepository:
    """Reliable projection jobs with worker leasing, retries, and operator replay."""

    def __init__(self, db: Database):
        self.db = db

    def enqueue(
        self,
        *,
        memory_id: str,
        memory_type: str,
        operation: str,
        payload: dict[str, Any],
        session: Session,
        tenant_id: str | None = None,
        user_id: str | None = None,
        event_id: str | None = None,
        content_version: int = 1,
        projection_type: str = "vector",
        priority: int | None = None,
        max_attempts: int | None = None,
        backoff_policy: dict[str, Any] | None = None,
    ) -> MemoryProjectionOutboxRow:
        payload_hash = canonical_sha256(payload)
        outbox_id = "outbox_" + canonical_sha256(
            {
                "memory_id": memory_id,
                "memory_type": memory_type,
                "operation": operation,
                "payload_hash": payload_hash,
                "tenant_id": tenant_id or "",
                "content_version": max(1, int(content_version)),
                "projection_type": projection_type,
            }
        )[:48]
        if priority is None:
            priority = 10 if operation == "delete" else 0
        if max_attempts is None:
            max_attempts = 5
        if backoff_policy is None:
            backoff_policy = _default_backoff_policy()
        row = session.get(MemoryProjectionOutboxRow, outbox_id)
        if row is None:
            # Older schemas enforce a natural-key uniqueness constraint that
            # does not include the payload hash.  A repeated write of the
            # same event/version must reuse that row even when its lineage
            # payload has a newer evidence revision.
            natural_key = {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "memory_id": memory_id,
                "memory_type": memory_type,
                "operation": operation,
                "event_id": event_id,
                "content_version": max(1, int(content_version)),
                "projection_type": projection_type,
            }
            row = session.query(MemoryProjectionOutboxRow).filter_by(**natural_key).first()
            if row is not None and row.payload_hash != payload_hash:
                row = None
        if row is None:
            # Some installations predate content-version in the unique key;
            # keep their single event projection row idempotent as well.
            row = session.query(MemoryProjectionOutboxRow).filter_by(
                tenant_id=tenant_id,
                memory_id=memory_id,
                memory_type=memory_type,
                operation=operation,
                event_id=event_id,
            ).first()
            if row is not None and row.payload_hash != payload_hash:
                row = None
        now = datetime.now()
        if row is None:
            row = MemoryProjectionOutboxRow(
                outbox_id=outbox_id,
                memory_id=memory_id,
                memory_type=memory_type,
                tenant_id=tenant_id,
                user_id=user_id,
                operation=operation,
                event_id=event_id,
                content_version=max(1, int(content_version)),
                projection_type=projection_type,
                payload_hash=payload_hash,
                status="pending",
                priority=priority,
                max_attempts=max_attempts,
                backoff_policy=backoff_policy,
                attempts=0,
                lease_version=0,
            )
            session.add(row)
        else:
            # Re-enqueue: bump the existing request if it is dead-lettered or stale.
            if row.status == "dead_letter":
                row.status = "pending"
                row.attempts = 0
                row.dead_lettered_at = None
                row.error_code = ""
                row.next_retry_at = None
            row.priority = priority
            row.max_attempts = max_attempts
            row.backoff_policy = backoff_policy
            row.content_version = max(row.content_version or 1, int(content_version))
            row.updated_at = now
        return row

    def claim_ready(
        self,
        *,
        limit: int = 100,
        lease_seconds: int = 300,
        now: datetime | None = None,
    ) -> list[ProjectionOutboxItem]:
        """Lease pending/failed work and reclaim abandoned processing leases."""
        now = now or datetime.now()
        lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
        with self.db.session() as session:
            # Reclaim stale leases first so they are eligible for re-claiming.
            stale = (
                session.query(MemoryProjectionOutboxRow)
                .filter(
                    MemoryProjectionOutboxRow.status == "processing",
                    MemoryProjectionOutboxRow.lease_expires_at < now,
                )
                .all()
            )
            for row in stale:
                row.status = "failed"
                row.error_code = "projection.lease_expired"
                row.next_retry_at = now
                row.lease_token = None
                row.lease_expires_at = None
                row.updated_at = now
            rows = (
                session.query(MemoryProjectionOutboxRow)
                .filter(
                    MemoryProjectionOutboxRow.status.in_(("pending", "failed")),
                    (MemoryProjectionOutboxRow.next_retry_at.is_(None))
                    | (MemoryProjectionOutboxRow.next_retry_at <= now),
                )
                .order_by(
                    MemoryProjectionOutboxRow.priority.desc(),
                    MemoryProjectionOutboxRow.created_at.asc(),
                )
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            items: list[ProjectionOutboxItem] = []
            for row in rows:
                row.status = "processing"
                row.attempts = int(row.attempts or 0) + 1
                row.lease_version = int(row.lease_version or 0) + 1
                row.lease_token = uuid.uuid4().hex
                row.lease_expires_at = lease_expires_at
                row.updated_at = now
                items.append(
                    ProjectionOutboxItem(
                        outbox_id=row.outbox_id,
                        tenant_id=row.tenant_id,
                        user_id=row.user_id,
                        memory_id=row.memory_id,
                        memory_type=row.memory_type,
                        operation=row.operation,
                        event_id=row.event_id,
                        content_version=row.content_version,
                        payload_hash=row.payload_hash,
                        attempts=row.attempts,
                        lease_token=row.lease_token,
                        lease_version=row.lease_version,
                        priority=row.priority,
                        max_attempts=row.max_attempts,
                        backoff_policy=dict(row.backoff_policy or {}),
                    )
                )
            session.flush()
            return items

    def mark_succeeded(
        self, outbox_id: str, *, lease_token: str | None = None, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now()
        with self.db.session() as session:
            row = session.get(MemoryProjectionOutboxRow, outbox_id)
            if row is None:
                return False
            if lease_token is not None:
                if row.status != "processing":
                    return False
                if row.lease_token != lease_token:
                    return False
                if row.lease_expires_at is not None and row.lease_expires_at < now:
                    return False
            elif row.status != "processing":
                # Backward compatibility: only allow unverified success on a processing row.
                return False
            row.status = "completed"
            row.error_code = ""
            row.next_retry_at = None
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
            return True

    def mark_failed(
        self,
        outbox_id: str,
        *,
        error_code: str,
        lease_token: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now()
        with self.db.session() as session:
            row = session.get(MemoryProjectionOutboxRow, outbox_id)
            if row is None:
                return False
            if lease_token is not None:
                if row.status != "processing":
                    return False
                if row.lease_token != lease_token:
                    return False
                if row.lease_expires_at is not None and row.lease_expires_at < now:
                    return False
            attempts = int(row.attempts or 0)
            max_attempts = max(1, int(row.max_attempts or 5))
            if attempts >= max_attempts:
                row.status = "dead_letter"
                row.dead_lettered_at = now
                row.next_retry_at = None
            else:
                policy = dict(row.backoff_policy or {})
                base = max(1, int(policy.get("base_delay_seconds", 5)))
                max_delay = max(base, int(policy.get("max_delay_seconds", 3600)))
                jitter = bool(policy.get("jitter", False))
                exponent = min(max(0, attempts - 1), 10)
                delay = min(max_delay, base * (2**exponent))
                if jitter:
                    delay = int(delay * (0.5 + random()))
                row.status = "failed"
                row.next_retry_at = now + timedelta(seconds=max(1, delay))
            row.error_code = error_code
            row.lease_token = None
            row.lease_expires_at = None
            row.updated_at = now
            return True

    def replay(self, outbox_ids: list[str] | None = None) -> int:
        """Move failed/dead-letter work back to pending without changing business memory rows."""
        with self.db.session() as session:
            query = session.query(MemoryProjectionOutboxRow).filter(
                MemoryProjectionOutboxRow.status.in_(("failed", "dead_letter"))
            )
            if outbox_ids is not None:
                ids = [outbox_id for outbox_id in dict.fromkeys(outbox_ids) if outbox_id]
                if not ids:
                    return 0
                query = query.filter(MemoryProjectionOutboxRow.outbox_id.in_(ids))
            return query.update(
                {
                    "status": "pending",
                    "attempts": 0,
                    "next_retry_at": None,
                    "error_code": "",
                    "dead_lettered_at": None,
                    "updated_at": datetime.now(),
                },
                synchronize_session=False,
            )

    def list_by_status(
        self, statuses: tuple[str, ...] = ("pending", "failed"), limit: int = 100
    ) -> list[ProjectionOutboxView]:
        with self.db.session() as session:
            rows = (
                session.query(MemoryProjectionOutboxRow)
                .filter(MemoryProjectionOutboxRow.status.in_(statuses))
                .order_by(
                    MemoryProjectionOutboxRow.priority.desc(),
                    MemoryProjectionOutboxRow.created_at.asc(),
                )
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [
                ProjectionOutboxView(
                    outbox_id=row.outbox_id,
                    tenant_id=row.tenant_id,
                    user_id=row.user_id,
                    memory_id=row.memory_id,
                    memory_type=row.memory_type,
                    operation=row.operation,
                    event_id=row.event_id,
                    content_version=row.content_version,
                    payload_hash=row.payload_hash,
                    status=row.status,
                    attempts=int(row.attempts or 0),
                    max_attempts=int(row.max_attempts or 5),
                    priority=int(row.priority or 0),
                    next_retry_at=row.next_retry_at,
                    error_code=row.error_code or "",
                    lease_token=row.lease_token,
                    lease_version=int(row.lease_version or 0),
                    lease_expires_at=row.lease_expires_at,
                    dead_lettered_at=row.dead_lettered_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    def list_dead_letter(self, limit: int = 100) -> list[ProjectionOutboxView]:
        return self.list_by_status(("dead_letter",), limit=limit)

    def list_by_memory(
        self,
        memory_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[ProjectionOutboxView]:
        with self.db.session() as session:
            query = session.query(MemoryProjectionOutboxRow).filter(
                MemoryProjectionOutboxRow.memory_id == memory_id
            )
            if tenant_id is not None:
                query = query.filter(MemoryProjectionOutboxRow.tenant_id == tenant_id)
            if user_id is not None:
                query = query.filter(MemoryProjectionOutboxRow.user_id == user_id)
            rows = (
                query.order_by(MemoryProjectionOutboxRow.created_at.desc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [
                ProjectionOutboxView(
                    outbox_id=row.outbox_id,
                    tenant_id=row.tenant_id,
                    user_id=row.user_id,
                    memory_id=row.memory_id,
                    memory_type=row.memory_type,
                    operation=row.operation,
                    event_id=row.event_id,
                    content_version=row.content_version,
                    payload_hash=row.payload_hash,
                    status=row.status,
                    attempts=int(row.attempts or 0),
                    max_attempts=int(row.max_attempts or 5),
                    priority=int(row.priority or 0),
                    next_retry_at=row.next_retry_at,
                    error_code=row.error_code or "",
                    lease_token=row.lease_token,
                    lease_version=int(row.lease_version or 0),
                    lease_expires_at=row.lease_expires_at,
                    dead_lettered_at=row.dead_lettered_at,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    def update_projection_version(
        self,
        memory_id: str,
        memory_type: str,
        projection_version: int,
        *,
        session: Session,
    ) -> bool:
        """Bump the Authority row's projection_version after a successful projection."""
        from memoryhub.storage.models import KnowledgeRow, PreferenceRow

        now = datetime.now()
        model = PreferenceRow if memory_type == "preference" else KnowledgeRow
        row = session.query(model).filter(model.memory_id == memory_id).first()
        if row is None:
            return False
        row.projection_version = max(0, int(projection_version))
        row.updated_at = now
        return True
