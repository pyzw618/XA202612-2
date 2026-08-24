"""Projection repair service: point and offline reconciliation with Authority.

Authority rows are the source of truth.  Projections are disposable, so repair
always re-enqueues the correct outbox operation rather than touching the vector
store directly.  This keeps repair verifiable and rollback is just another
outbox replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import KnowledgeRow, PreferenceRow


@dataclass(frozen=True, slots=True)
class RepairDiagnostic:
    """A single repair finding with a safe, idempotent outbox action."""

    category: str
    memory_id: str
    memory_type: str
    authority_version: int
    projection_version: int
    action: str
    reason: str


class RepairService:
    """Diagnose and enqueue repairs for projection drift."""

    CATEGORIES: tuple[str, ...] = ("missing", "stale", "orphan", "incompatible", "duplicate")

    def __init__(
        self,
        db: Database,
        authority_repository: Any,
        outbox_repo: MemoryProjectionOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.authority_repository = authority_repository
        self.outbox_repo = outbox_repo or MemoryProjectionOutboxRepository(db)

    def diagnose(
        self,
        memory_id: str,
        memory_type: str | None = None,
        *,
        session: Session | None = None,
    ) -> RepairDiagnostic:
        """Inspect Authority and return the repair action, without writing."""
        if session is None:
            with self.db.session() as session:
                return self.diagnose(memory_id, memory_type, session=session)

        row, detected_type = self._find_row(session, memory_id)
        if row is None:
            return RepairDiagnostic(
                category="incompatible",
                memory_id=memory_id,
                memory_type=memory_type or "unknown",
                authority_version=0,
                projection_version=0,
                action="none",
                reason="memory not found in authority",
            )

        memory_type = memory_type or detected_type
        content_version = max(1, int(row.version or 1))
        projection_version = int(row.projection_version or 0)
        status = str(row.status or "active").lower()

        if status in ("deleted", "superseded"):
            return RepairDiagnostic(
                category="orphan",
                memory_id=memory_id,
                memory_type=memory_type,
                authority_version=content_version,
                projection_version=projection_version,
                action="delete",
                reason=f"authority status is {status}",
            )

        if memory_type not in ("preference", "knowledge"):
            return RepairDiagnostic(
                category="incompatible",
                memory_id=memory_id,
                memory_type=memory_type,
                authority_version=content_version,
                projection_version=projection_version,
                action="none",
                reason="unsupported memory type for vector projection",
            )

        if projection_version == 0:
            return RepairDiagnostic(
                category="missing",
                memory_id=memory_id,
                memory_type=memory_type,
                authority_version=content_version,
                projection_version=0,
                action="upsert",
                reason="projection_version is zero",
            )

        if projection_version < content_version:
            return RepairDiagnostic(
                category="stale",
                memory_id=memory_id,
                memory_type=memory_type,
                authority_version=content_version,
                projection_version=projection_version,
                action="upsert",
                reason="projection lags authority content_version",
            )

        return RepairDiagnostic(
            category="ok",
            memory_id=memory_id,
            memory_type=memory_type,
            authority_version=content_version,
            projection_version=projection_version,
            action="none",
            reason="projection is up to date",
        )

    def repair_one(
        self,
        memory_id: str,
        memory_type: str | None = None,
        *,
        session: Session | None = None,
        dry_run: bool = False,
    ) -> RepairDiagnostic:
        """Diagnose and enqueue the matching outbox operation if needed."""
        if session is None:
            with self.db.session() as session:
                diagnostic = self.repair_one(
                    memory_id, memory_type, session=session, dry_run=dry_run
                )
                session.commit()
                return diagnostic

        diagnostic = self.diagnose(memory_id, memory_type, session=session)
        if diagnostic.action == "none" or dry_run:
            return diagnostic

        priority = 10 if diagnostic.action == "delete" else 5
        payload = {
            "memory_id": diagnostic.memory_id,
            "memory_type": diagnostic.memory_type,
            "operation": diagnostic.action,
            "content_version": diagnostic.authority_version,
            "projection_type": "vector",
        }
        self.outbox_repo.enqueue(
            memory_id=diagnostic.memory_id,
            memory_type=diagnostic.memory_type,
            operation=diagnostic.action,
            payload=payload,
            session=session,
            tenant_id=None,
            user_id=None,
            content_version=diagnostic.authority_version,
            projection_type="vector",
            priority=priority,
        )
        return diagnostic

    def repair_all(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        dry_run: bool = False,
        limit: int = 1000,
    ) -> list[RepairDiagnostic]:
        """Scan active Authority rows and enqueue repairs for every drift."""
        diagnostics: list[RepairDiagnostic] = []
        with self.db.session() as session:
            for model, memory_type in (
                (PreferenceRow, "preference"),
                (KnowledgeRow, "knowledge"),
            ):
                query = session.query(model)
                if tenant_id is not None:
                    query = query.filter(model.tenant_id == tenant_id)
                if user_id is not None:
                    query = query.filter(model.user_id == user_id)
                rows = query.limit(max(1, min(int(limit), 5000))).all()
                for row in rows:
                    diagnostic = self.repair_one(
                        row.memory_id,
                        memory_type,
                        session=session,
                        dry_run=dry_run,
                    )
                    if diagnostic.category != "ok":
                        diagnostics.append(diagnostic)
            if not dry_run:
                session.commit()
        return diagnostics

    def _find_row(
        self, session: Session, memory_id: str
    ) -> tuple[PreferenceRow | KnowledgeRow | None, str]:
        pref = session.query(PreferenceRow).filter_by(memory_id=memory_id).first()
        if pref is not None:
            return pref, "preference"
        know = session.query(KnowledgeRow).filter_by(memory_id=memory_id).first()
        if know is not None:
            return know, "knowledge"
        return None, "unknown"


class RepairWorker:
    """Offline worker that scans Authority and enqueues projection repairs."""

    def __init__(
        self,
        repair_service: RepairService,
        outbox_repo: MemoryProjectionOutboxRepository | None = None,
    ) -> None:
        self.repair_service = repair_service
        self.outbox_repo = outbox_repo or repair_service.outbox_repo

    def run_once(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        dry_run: bool = False,
        limit: int = 1000,
    ) -> list[RepairDiagnostic]:
        """Return the list of drifts found (and optionally repaired)."""
        return self.repair_service.repair_all(
            tenant_id=tenant_id,
            user_id=user_id,
            dry_run=dry_run,
            limit=limit,
        )
