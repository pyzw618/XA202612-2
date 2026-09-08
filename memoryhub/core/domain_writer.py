"""Single transactional writer for approved Preference and Knowledge memory changes."""

from __future__ import annotations

from datetime import datetime

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryDecision,
    MemoryProvenance,
    MemoryStatus,
    MemoryWriteReceipt,
    PreferenceMemory,
    SourceType,
    canonical_sha256,
)
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.memory_metadata import (
    MemoryEvidenceRepository,
    MemoryLineageRepository,
    MemoryProjectionOutboxRepository,
)
from memoryhub.storage.models import FactDecisionRow

Memory = PreferenceMemory | KnowledgeMemory


class DomainMemoryWriter:
    """Persist a domain memory, lineage, evidence, and projection job in one transaction."""

    def __init__(
        self,
        *,
        db: Database,
        pref_repo: PreferenceRepository,
        know_repo: KnowledgeRepository,
        lineage_repo: MemoryLineageRepository | None = None,
        evidence_repo: MemoryEvidenceRepository | None = None,
        outbox_repo: MemoryProjectionOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.lineage_repo = lineage_repo or MemoryLineageRepository(db)
        self.evidence_repo = evidence_repo or MemoryEvidenceRepository(db)
        self.outbox_repo = outbox_repo or MemoryProjectionOutboxRepository(db)

    def write(
        self,
        memory: Memory,
        *,
        action: MemoryDecision | str,
        provenance: MemoryProvenance | None = None,
        semantic_repo=None,
        semantic_result=None,
        transaction_validator=None,
    ) -> MemoryWriteReceipt:
        """Write one change atomically and return its receipt."""
        return self.write_batch([
            (memory, action, provenance, semantic_repo, semantic_result)
        ], transaction_validator=transaction_validator)[0]

    def write_batch(
        self, changes: list[tuple], *, transaction_validator=None
    ) -> list[MemoryWriteReceipt]:
        """Commit several domain changes in one session.

        Fact replacement uses this to archive every selected predecessor and
        create the successor together with semantic bindings, evidence,
        lineage and outbox rows.  Existing single-memory callers keep using
        ``write`` unchanged.
        """
        with self.db.session() as session:
            # Serialize the short authoritative part of FACT writes.  SQLite's
            # deferred transactions otherwise allow two independently
            # prepared conflicting facts to both reach ACTIVE state.
            if any(
                getattr(getattr(change[0], "knowledge_type", None), "value",
                        getattr(change[0], "knowledge_type", None)) == "fact"
                for change in changes
            ):
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if transaction_validator is not None:
                transaction_validator(session)
            receipts = [
                self._write_one(
                    session,
                    memory=memory,
                    action=action,
                    provenance=provenance,
                    semantic_repo=semantic_repo,
                    semantic_result=semantic_result,
                )
                for memory, action, provenance, semantic_repo, semantic_result in changes
            ]
            session.flush()
            return receipts

    def _write_one(
        self,
        session,
        *,
        memory: Memory,
        action: MemoryDecision | str,
        provenance: MemoryProvenance | None,
        semantic_repo=None,
        semantic_result=None,
    ) -> MemoryWriteReceipt:
        decision = action if isinstance(action, MemoryDecision) else MemoryDecision(action)
        provenance = provenance or self._derive_provenance(memory)
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        if repo is None:
            raise RuntimeError(f"domain_writer.repository_unavailable:{memory.memory_type}")
        operation = self._projection_operation(memory)
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        authority = dict(payload.get("vnext_authority", {}) or {})
        tenant_id = authority.get("tenant_id") or "default"
        user_id = authority.get("user_id") or memory.user_id or "default"
        content_version = int(authority.get("content_version", memory.version) or memory.version)
        schema_version = str(authority.get("schema_version", "vnext/v1"))
        policy_version = authority.get("policy_version")
        sensitivity_level = authority.get("sensitivity_level")

        repo.save(memory, session=session)
        self._sync_fact_decision(session, memory, tenant_id=tenant_id, user_id=user_id)
        if semantic_repo is not None and semantic_result is not None:
            semantic_repo.apply_result(session, memory=memory, result=semantic_result)
        elif semantic_repo is not None and memory.memory_type == "knowledge" and self._status(memory) == MemoryStatus.ARCHIVED.value:
            semantic_repo.set_binding_status(
                memory.memory_id, "archived", session=session
            )
        lineage = self.lineage_repo.record(
            memory_id=memory.memory_id,
            memory_type=memory.memory_type,
            parent_memory_id=getattr(memory, "parent_id", "") or None,
            root_memory_id=getattr(memory, "root_id", "") or None,
            semantic_version=max(1, int(memory.version)),
            transition_action=decision.value,
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            content_version=content_version,
            schema_version=schema_version,
            policy_version=policy_version,
        )
        evidence_ids = self.evidence_repo.record_all(
            memory_id=memory.memory_id,
            memory_type=memory.memory_type,
            evidences=list(getattr(memory, "evidences", []) or []),
            provenance=provenance,
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            content_version=content_version,
            schema_version=schema_version,
            policy_version=policy_version,
            sensitivity_level=sensitivity_level,
        )
        outbox = self.outbox_repo.enqueue(
            memory_id=memory.memory_id,
            memory_type=memory.memory_type,
            operation=operation,
            payload={
                "memory_id": memory.memory_id,
                "memory_type": memory.memory_type,
                "operation": operation,
                "status": self._status(memory),
                "semantic_version": lineage.semantic_version,
                "evidence_revision": lineage.evidence_revision,
            },
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            event_id=provenance.event_id,
            content_version=content_version,
            projection_type="long_term",
        )
        return MemoryWriteReceipt(
            memory_id=memory.memory_id,
            memory_type=memory.memory_type,
            action=decision,
            lineage_id=lineage.lineage_id,
            evidence_ids=evidence_ids,
            outbox_id=outbox.outbox_id,
            provenance=provenance,
        )

    @classmethod
    def _sync_fact_decision(cls, session, memory: Memory, *, tenant_id: str,
                            user_id: str) -> None:
        """Keep a FACT proposal and its durable decision row in one commit."""
        if getattr(getattr(memory, "knowledge_type", None), "value",
                   getattr(memory, "knowledge_type", None)) != "fact":
            return
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        task = dict(payload.get("fact_decision_task", {}) or {})
        if not task:
            return
        decision_id = f"fact-decision:{memory.memory_id}"
        row = session.get(FactDecisionRow, decision_id)
        if row is None:
            row = FactDecisionRow(decision_id=decision_id)
            session.add(row)
        row.tenant_id = tenant_id or "default"
        row.user_id = user_id or "default"
        row.memory_id = memory.memory_id
        row.task_type = str(task.get("decision_type") or "fact_conflict")
        row.payload = task
        row.expected_version = int(task.get("expected_version") or memory.version or 1)
        resolution = dict(payload.get("fact_decision_resolution", {}) or {})
        status = cls._status(memory)
        if status == MemoryStatus.PENDING.value:
            row.status = "pending"
            row.result_memory_id = ""
            row.reason = ""
            row.resolved_at = None
        elif resolution:
            row.status = str(resolution.get("status") or "committed")
            row.result_memory_id = str(resolution.get("result_memory_id") or "")
            row.reason = str(resolution.get("reason") or "")
            row.resolved_at = datetime.now()

    @staticmethod
    def _status(memory: Memory) -> str:
        status = memory.status
        return status.value if hasattr(status, "value") else str(status)

    @classmethod
    def _projection_operation(cls, memory: Memory) -> str:
        return "delete" if cls._status(memory) == MemoryStatus.DELETED.value else "upsert"

    @staticmethod
    def _derive_provenance(memory: Memory) -> MemoryProvenance:
        evidence = next(iter(getattr(memory, "evidences", []) or []), None)
        event_id = getattr(evidence, "event_id", "") or (
            f"legacy_memory_{memory.memory_id}_{max(1, int(memory.version))}"
        )
        source_type = getattr(evidence, "source_type", SourceType.MANUAL_CONFIG)
        if not isinstance(source_type, SourceType):
            source_type = SourceType(source_type)
        excerpt = getattr(evidence, "content", "") or ""
        payload = dict(getattr(memory, "extra_payload", {}) or {})
        safety = dict(payload.get("safety", {}) or {})
        safety_action = safety.get("action")
        return MemoryProvenance(
            event_id=event_id,
            source_hash=canonical_sha256(
                {
                    "memory_id": memory.memory_id,
                    "memory_type": memory.memory_type,
                    "event_id": event_id,
                    "source_type": source_type.value,
                    "excerpt": excerpt,
                }
            ),
            source_type=source_type,
            safety_audit_id=str(safety.get("audit_id", "") or "") or None,
            safety_action=safety_action or None,
        )
