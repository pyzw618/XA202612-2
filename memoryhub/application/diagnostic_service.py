"""Tenant-scoped, redacted management diagnostics."""

from __future__ import annotations

from typing import Any

from memoryhub.observability.audit_store import AuditStore
from memoryhub.storage.memory_metadata import (
    MemoryEvidenceRepository,
    MemoryLineageRepository,
    MemoryProjectionOutboxRepository,
)
from memoryhub.storage.models import MemoryCandidateRow


class DiagnosticService:
    def __init__(self, db, *, trace_store=None, audit_store: AuditStore | None = None) -> None:
        self.db = db
        self.trace_store = trace_store
        self.audit_store = audit_store or AuditStore(db)
        self.outbox = MemoryProjectionOutboxRepository(db)

    def inspect(
        self,
        *,
        target_type: str,
        target_id: str,
        tenant_id: str,
        user_id: str,
        include_sensitive: bool = False,
        actor_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.audit_store.record(
            action="DIAGNOSTIC_INSPECT",
            tenant_id=tenant_id,
            user_id=user_id,
            actor_id=actor_id or user_id,
            target_type=target_type,
            target_id=target_id,
            details={"include_sensitive": False, "redacted": True},
        )
        if target_type == "projection":
            return [
                self._safe(item.__dict__)
                for item in self.outbox.list_by_memory(
                    target_id, tenant_id=tenant_id, user_id=user_id
                )
            ]
        if target_type == "lineage":
            repo = MemoryLineageRepository(self.db)
            return [
                self._safe(item.__dict__)
                for memory_type in (
                    "preference", "knowledge", "semantic", "procedural", "episodic"
                )
                for item in repo.list_for_memory(target_id, memory_type)
            ]
        if target_type == "evidence":
            repo = MemoryEvidenceRepository(self.db)
            return [
                self._safe(item.__dict__)
                for memory_type in (
                    "preference", "knowledge", "semantic", "procedural", "episodic"
                )
                for item in repo.list_for_memory(target_id, memory_type)
            ]
        if target_type == "candidate":
            with self.db.session() as session:
                rows = (
                    session.query(MemoryCandidateRow)
                    .filter_by(candidate_id=target_id, tenant_id=tenant_id, user_id=user_id)
                    .all()
                )
                return [self._safe(row.__dict__) for row in rows]
        if target_type == "retrieval_trace":
            spans = (
                self.trace_store.list_by_trace(target_id) if self.trace_store is not None else []
            )
            return [
                self._safe(span.model_dump(mode="json"))
                for span in spans
                if span.tenant_id == tenant_id and span.user_id == user_id
            ]
        if target_type == "memory":
            with self.db.session() as session:
                rows = []
                for table in ("preferences", "knowledge"):
                    rows.extend(
                        session.execute(
                            __import__("sqlalchemy").text(
                                f"SELECT memory_id, tenant_id, user_id, status, version, "
                                f"projection_version FROM {table} WHERE memory_id=:id "
                                "AND tenant_id=:tenant AND user_id=:user"
                            ),
                            {"id": target_id, "tenant": tenant_id, "user": user_id},
                        )
                        .mappings()
                        .all()
                    )
                return [self._safe(dict(row)) for row in rows]
        return []

    @staticmethod
    def _safe(value: Any) -> Any:
        forbidden = {
            "content", "text", "payload", "raw_payload", "original_payload", "claim",
            "excerpt", "evidence", "evidence_text", "raw_query", "original_query",
            "query", "body", "memory_body", "embedding",
        }
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if str(key).lower() in forbidden
                    else DiagnosticService._safe(item)
                )
                for key, item in value.items()
                if key != "_sa_instance_state"
            }
        if isinstance(value, (list, tuple)):
            return [DiagnosticService._safe(item) for item in value]
        return value


__all__ = ["DiagnosticService"]
