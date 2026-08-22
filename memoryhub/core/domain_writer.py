"""Single transactional writer for approved Preference and Knowledge memory changes."""

from __future__ import annotations

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
    ) -> MemoryWriteReceipt:
        """Write all authoritative records atomically and return the resulting receipt."""
        decision = action if isinstance(action, MemoryDecision) else MemoryDecision(action)
        provenance = provenance or self._derive_provenance(memory)
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        if repo is None:
            raise RuntimeError(f"domain_writer.repository_unavailable:{memory.memory_type}")
        operation = self._projection_operation(memory)
        authority = dict(
            getattr(memory, "extra_payload", {}).get("vnext_authority", {}) or {}
        )
        tenant_id = authority.get("tenant_id")
        user_id = authority.get("user_id") or memory.user_id
        content_version = int(authority.get("content_version", memory.version) or memory.version)
        schema_version = str(authority.get("schema_version", "vnext/v1"))
        policy_version = authority.get("policy_version")
        sensitivity_level = authority.get("sensitivity_level")

        with self.db.session() as session:
            repo.save(memory, session=session)
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
            session.flush()
            return MemoryWriteReceipt(
                memory_id=memory.memory_id,
                memory_type=memory.memory_type,
                action=decision,
                lineage_id=lineage.lineage_id,
                evidence_ids=evidence_ids,
                outbox_id=outbox.outbox_id,
                provenance=provenance,
            )

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
        safety = dict(getattr(memory, "extra_payload", {}).get("safety", {}) or {})
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
