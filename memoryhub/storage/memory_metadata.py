"""Authoritative SQLite repositories for memory lineage, evidence, and projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
            parent_memory_id=parent_memory_id or None,
            root_memory_id=root_id,
            semantic_version=max(1, semantic_version),
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
                    event_id=event_id,
                    source_hash=source_hash,
                    source_type=self._source_type(evidence, provenance).value,
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
    memory_id: str
    memory_type: str
    operation: str
    payload_hash: str
    attempts: int


@dataclass(frozen=True, slots=True)
class ProjectionOutboxView:
    """Detached outbox status projection for management APIs and diagnostics."""

    outbox_id: str
    memory_id: str
    memory_type: str
    operation: str
    payload_hash: str
    status: str
    attempts: int
    next_retry_at: datetime | None
    error_code: str
    created_at: datetime
    updated_at: datetime


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
    ) -> MemoryProjectionOutboxRow:
        payload_hash = canonical_sha256(payload)
        outbox_id = "outbox_" + canonical_sha256(
            {
                "memory_id": memory_id,
                "memory_type": memory_type,
                "operation": operation,
                "payload_hash": payload_hash,
            }
        )[:48]
        row = session.get(MemoryProjectionOutboxRow, outbox_id)
        if row is None:
            row = MemoryProjectionOutboxRow(
                outbox_id=outbox_id,
                memory_id=memory_id,
                memory_type=memory_type,
                operation=operation,
                payload_hash=payload_hash,
                status="pending",
            )
            session.add(row)
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
        stale_before = now - timedelta(seconds=max(1, lease_seconds))
        with self.db.session() as session:
            session.query(MemoryProjectionOutboxRow).filter(
                MemoryProjectionOutboxRow.status == "processing",
                MemoryProjectionOutboxRow.updated_at < stale_before,
            ).update(
                {
                    "status": "failed",
                    "error_code": "projection.lease_expired",
                    "next_retry_at": now,
                    "updated_at": now,
                },
                synchronize_session=False,
            )
            rows = (
                session.query(MemoryProjectionOutboxRow)
                .filter(
                    MemoryProjectionOutboxRow.status.in_(("pending", "failed")),
                    (MemoryProjectionOutboxRow.next_retry_at.is_(None))
                    | (MemoryProjectionOutboxRow.next_retry_at <= now),
                )
                .order_by(MemoryProjectionOutboxRow.created_at.asc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            items: list[ProjectionOutboxItem] = []
            for row in rows:
                row.status = "processing"
                row.attempts = int(row.attempts or 0) + 1
                row.updated_at = now
                items.append(
                    ProjectionOutboxItem(
                        outbox_id=row.outbox_id,
                        memory_id=row.memory_id,
                        memory_type=row.memory_type,
                        operation=row.operation,
                        payload_hash=row.payload_hash,
                        attempts=row.attempts,
                    )
                )
            session.flush()
            return items

    def mark_succeeded(self, outbox_id: str, *, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        with self.db.session() as session:
            row = session.get(MemoryProjectionOutboxRow, outbox_id)
            if row is None:
                return False
            row.status = "completed"
            row.error_code = ""
            row.next_retry_at = None
            row.updated_at = now
            return True

    def mark_failed(
        self,
        outbox_id: str,
        *,
        error_code: str,
        base_delay_seconds: int = 5,
        max_delay_seconds: int = 3600,
        now: datetime | None = None,
    ) -> bool:
        now = now or datetime.now()
        with self.db.session() as session:
            row = session.get(MemoryProjectionOutboxRow, outbox_id)
            if row is None:
                return False
            exponent = min(max(0, int(row.attempts or 1) - 1), 10)
            delay = min(max_delay_seconds, max(1, base_delay_seconds) * (2**exponent))
            row.status = "failed"
            row.error_code = error_code
            row.next_retry_at = now + timedelta(seconds=delay)
            row.updated_at = now
            return True

    def replay(self, outbox_ids: list[str] | None = None) -> int:
        """Move failed work back to pending without changing business memory rows."""
        with self.db.session() as session:
            query = session.query(MemoryProjectionOutboxRow).filter(
                MemoryProjectionOutboxRow.status == "failed"
            )
            if outbox_ids is not None:
                ids = [outbox_id for outbox_id in dict.fromkeys(outbox_ids) if outbox_id]
                if not ids:
                    return 0
                query = query.filter(MemoryProjectionOutboxRow.outbox_id.in_(ids))
            return query.update(
                {
                    "status": "pending",
                    "next_retry_at": None,
                    "error_code": "",
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
                .order_by(MemoryProjectionOutboxRow.created_at.asc())
                .limit(max(1, min(int(limit), 500)))
                .all()
            )
            return [
                ProjectionOutboxView(
                    outbox_id=row.outbox_id,
                    memory_id=row.memory_id,
                    memory_type=row.memory_type,
                    operation=row.operation,
                    payload_hash=row.payload_hash,
                    status=row.status,
                    attempts=int(row.attempts or 0),
                    next_retry_at=row.next_retry_at,
                    error_code=row.error_code or "",
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]
