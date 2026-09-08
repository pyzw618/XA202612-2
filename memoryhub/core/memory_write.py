"""Unified persistence and runtime-index synchronization for extracted memories."""

from __future__ import annotations

import json
import time
from typing import Any

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    MemoryDecision,
    MemoryProvenance,
    MemoryStatus,
    PreferenceMemory,
)
from memoryhub.core.domain_writer import DomainMemoryWriter

Memory = PreferenceMemory | KnowledgeMemory


class MemoryWriteService:
    """Keep SQLite, runtime lookup, vector/BM25 indexes, and cache consistent."""

    def __init__(
        self,
        *,
        pref_repo,
        know_repo,
        vector_store=None,
        vector_engine=None,
        keyword_search=None,
        memory_lookup: dict[str, Memory] | None = None,
        search_cache=None,
        embedding_client=None,
        evidence_store=None,
        conflict_repo=None,
        safety_gate=None,
        require_safety: bool = False,
        domain_writer: DomainMemoryWriter | None = None,
        project_immediately: bool = True,
    ) -> None:
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.vector_store = vector_store
        self.vector_engine = vector_engine
        self.keyword_search = keyword_search
        self.memory_lookup = memory_lookup
        self.search_cache = search_cache
        self.embedding_client = embedding_client
        self.evidence_store = evidence_store
        self.conflict_repo = conflict_repo
        self.safety_gate = safety_gate
        self.require_safety = bool(require_safety)
        self.project_immediately = bool(project_immediately)
        self.domain_writer = domain_writer or self._build_domain_writer()

    @staticmethod
    def index_text(memory: Memory) -> str:
        if memory.memory_type == "knowledge":
            parts = [
                memory.name,
                memory.content,
                *memory.steps,
                *memory.tools,
                memory.template_body,
                memory.subject,
                memory.predicate,
                memory.object_value,
            ]
            return " ".join(str(part).strip() for part in parts if str(part).strip())
        return memory.text

    @classmethod
    def index_metadata(cls, memory: Memory) -> dict[str, Any]:
        return {
            "memory_type": memory.memory_type,
            "user_id": memory.user_id,
            "content": cls.index_text(memory),
            "confidence": memory.confidence,
            "scope": memory.scope.model_dump(),
            "status": (
                memory.status.value
                if hasattr(memory.status, "value")
                else str(memory.status)
            ),
            "quality_score": getattr(memory, "quality_score", 1.0),
            "updated_at": str(getattr(memory, "updated_at", "") or ""),
            "created_at": str(getattr(memory, "created_at", "") or ""),
            "evidence_count": len(getattr(memory, "evidences", []) or []),
            "subject": getattr(memory, "subject", "") or "",
            "predicate": getattr(memory, "predicate", "") or "",
            "level": getattr(memory, "level", "long") or "long",
            "safety": dict(
                getattr(memory, "extra_payload", {}).get("safety", {}) or {}
            ),
        }

    def upsert_memory(
        self,
        memory: Memory,
        *,
        action: MemoryDecision | str | None = None,
        provenance=None,
        skip_write_gate: bool = False,
        semantic_repo=None,
        semantic_result=None,
    ):
        """Persist through the safety gate while preserving an explicit domain action.

        ``skip_write_gate`` is used by the event-extraction path (REFACTOR_PLAN_V2
        I-14): memories derived from events that already passed the event-level
        safety gate do not need a second, redundant memory-level re-gate. This
        removes the intermittent "double gate" safe-projection / review failure
        without weakening the explicit-write safety boundary.
        """
        if skip_write_gate:
            return self._unsafe_upsert_memory(
                memory, action=action, provenance=provenance,
                semantic_repo=semantic_repo, semantic_result=semantic_result,
            )
        status = (
            memory.status.value
            if hasattr(memory.status, "value")
            else str(memory.status)
        )
        if status == MemoryStatus.ACTIVE.value:
            if self.safety_gate is None:
                if self.require_safety:
                    raise RuntimeError("memory_write.safety_gate_unavailable")
                return self._unsafe_upsert_memory(
                    memory, action=action, provenance=provenance,
                    semantic_repo=semantic_repo, semantic_result=semantic_result,
                )
            from memoryhub.core.safety.memory_write import guard_memory_write

            guarded = guard_memory_write(
                self.safety_gate,
                memory,
                lambda safe_memory: self._unsafe_upsert_memory(
                    safe_memory,
                    action=action,
                    provenance=provenance,
                    semantic_repo=semantic_repo,
                    semantic_result=semantic_result,
                ),
                operation="memory_sync",
                approved_sink=lambda safe_memory, approved: self._unsafe_upsert_memory(
                    safe_memory,
                    action=action,
                    provenance=provenance or MemoryProvenance(
                        event_id=approved.safe_event.event_id,
                        source_hash=approved.safe_event.source_hash,
                        source_type=approved.safe_event.source_type,
                        safety_audit_id=approved.audit_id,
                        safety_action=approved.action,
                    ),
                    semantic_repo=semantic_repo,
                    semantic_result=semantic_result,
                ),
            )
            if guarded.memory is None:
                raise RuntimeError(f"memory_write.blocked:{guarded.action.value}")
            # R8: surface the MemoryWriteReceipt produced inside the approved sink
            # instead of swallowing it in the production gated path.
            return guarded.sink_result
        return self._unsafe_upsert_memory(
            memory, action=action, provenance=provenance,
            semantic_repo=semantic_repo, semantic_result=semantic_result,
        )

    def upsert_fact_decision(
        self,
        memory: KnowledgeMemory,
        *,
        replacements: list[KnowledgeMemory] | None = None,
        action: MemoryDecision | str = MemoryDecision.SUPERSEDE,
        provenance=None,
        semantic_repo=None,
        semantic_result=None,
    ):
        """Commit a FACT successor and its replaced predecessors atomically."""
        replacements = list(replacements or [])
        if self.domain_writer is None:
            for old in replacements:
                self.upsert_memory(old, action=MemoryDecision.SUPERSEDE)
            return self.upsert_memory(
                memory, action=action, provenance=provenance,
                semantic_repo=semantic_repo, semantic_result=semantic_result,
            )

        def commit(safe_memory: KnowledgeMemory, approved_provenance=None):
            changes = []
            for old in replacements:
                old.status = MemoryStatus.ARCHIVED
                changes.append((old, MemoryDecision.SUPERSEDE, None, semantic_repo, None))
            changes.append((
                safe_memory, action, approved_provenance, semantic_repo, semantic_result
            ))
            receipts = self.domain_writer.write_batch(changes)
            for old in replacements:
                self.sync_memory(old)
            self.sync_memory(safe_memory)
            return receipts[-1]

        status = (
            memory.status.value if hasattr(memory.status, "value") else str(memory.status)
        )
        if status != MemoryStatus.ACTIVE.value:
            return commit(memory, provenance)
        if self.safety_gate is None:
            if self.require_safety:
                raise RuntimeError("memory_write.safety_gate_unavailable")
            return commit(memory, provenance)
        from memoryhub.core.safety.memory_write import guard_memory_write

        guarded = guard_memory_write(
            self.safety_gate,
            memory,
            lambda safe_memory: commit(safe_memory, provenance),
            operation="memory_sync",
            approved_sink=lambda safe_memory, approved: commit(
                safe_memory,
                provenance or MemoryProvenance(
                    event_id=approved.safe_event.event_id,
                    source_hash=approved.safe_event.source_hash,
                    source_type=approved.safe_event.source_type,
                    safety_audit_id=approved.audit_id,
                    safety_action=approved.action,
                ),
            ),
        )
        if guarded.memory is None:
            raise RuntimeError(f"memory_write.blocked:{guarded.action.value}")
        return guarded.sink_result

    def upsert_fact_duplicate(
        self,
        proposal: KnowledgeMemory,
        reinforced: KnowledgeMemory,
        *,
        semantic_repo=None,
        semantic_result=None,
        provenance=None,
    ):
        """Atomically consume a pending proposal while adding its evidence.

        Entity-resolution decisions can prove that a pending proposal is the
        same fact as an existing row.  The proposal must leave the pending
        queue and the existing row must receive the evidence in one commit so
        a restart cannot expose both records as active.
        """
        proposal.status = MemoryStatus.DELETED
        if self.domain_writer is not None:
            receipts = self.domain_writer.write_batch([
                (proposal, MemoryDecision.REJECT, provenance, None, None),
                (reinforced, MemoryDecision.REINFORCE, provenance,
                 semantic_repo, semantic_result),
            ])
            self.sync_memory(proposal)
            self.sync_memory(reinforced)
            return receipts[-1]
        self.upsert_memory(
            proposal, action=MemoryDecision.REJECT, skip_write_gate=True,
            provenance=provenance,
        )
        return self.upsert_memory(
            reinforced, action=MemoryDecision.REINFORCE, skip_write_gate=True,
            provenance=provenance, semantic_repo=semantic_repo,
            semantic_result=semantic_result,
        )

    def _unsafe_upsert_memory(
        self,
        memory: Memory,
        *,
        action: MemoryDecision | str | None = None,
        provenance=None,
        semantic_repo=None,
        semantic_result=None,
    ):
        """Persist first, then project; the domain writer owns authoritative DB writes."""
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        receipt = None
        if self.domain_writer is not None:
            receipt = self.domain_writer.write(
                memory,
                action=action or self._infer_decision(memory, repo),
                provenance=provenance,
                semantic_repo=semantic_repo,
                semantic_result=semantic_result,
            )
        else:
            repo.save(memory)
        if self.evidence_store is not None:
            # JSONL remains a short-term read compatibility adapter.  The SQLite
            # MemoryEvidenceRepository is authoritative for all new writer paths.
            self.evidence_store.delete(memory.memory_id)
            if memory.evidences:
                self.evidence_store.batch_save(memory.memory_id, memory.evidences)
        if self.project_immediately:
            self.sync_memory(memory)
        return receipt

    def _build_domain_writer(self) -> DomainMemoryWriter | None:
        """Enable the transactional path only when both repositories share a Database."""
        db = getattr(self.pref_repo, "db", None) or getattr(self.know_repo, "db", None)
        if db is None:
            return None
        other_db = getattr(self.know_repo, "db", None)
        if self.pref_repo is not None and self.know_repo is not None and db is not other_db:
            return None
        return DomainMemoryWriter(
            db=db,
            pref_repo=self.pref_repo,
            know_repo=self.know_repo,
        )

    @staticmethod
    def _infer_decision(memory: Memory, repo) -> MemoryDecision:
        """Compatibility classification until callers pass explicit domain decisions."""
        get_by_id = getattr(repo, "get_by_id", None)
        existing = get_by_id(memory.memory_id) if callable(get_by_id) else None
        if existing is None:
            return MemoryDecision.NEW
        if getattr(memory, "parent_id", "") and memory.parent_id != memory.memory_id:
            return MemoryDecision.SUPERSEDE
        if int(getattr(memory, "version", 1) or 1) > int(
            getattr(existing, "version", 1) or 1
        ):
            return MemoryDecision.REVISE
        return MemoryDecision.REINFORCE

    def sync_memory(self, memory: Memory, *, remove: bool = False) -> None:
        explicit_remove = remove
        status = (
            memory.status.value
            if hasattr(memory.status, "value")
            else str(memory.status)
        )
        remove = remove or status != MemoryStatus.ACTIVE.value
        memory_id = memory.memory_id

        if remove:
            # Publish an inactive tombstone to the shared lookup before external deletes.
            # If a vector backend is temporarily unavailable, production retrieval will
            # still fail closed on status instead of returning the stale vector.
            if self.memory_lookup is not None:
                self.memory_lookup[memory_id] = memory
            self._clear_cache()
            if self.vector_store is not None:
                self.vector_store.delete(memory_id)
                self.vector_store.save()
            if self.vector_engine is not None:
                self.vector_engine.delete(memory_id)
            if self.keyword_search is not None:
                self.keyword_search.delete(memory_id)
            if self.memory_lookup is not None:
                self.memory_lookup.pop(memory_id, None)
            if (
                explicit_remove or status == MemoryStatus.DELETED.value
            ) and self.evidence_store is not None:
                self.evidence_store.delete(memory_id)
            if (
                explicit_remove or status == MemoryStatus.DELETED.value
            ) and self.conflict_repo is not None:
                self.conflict_repo.delete_for_memories([memory_id])
            self._clear_cache()
            self._mark_synchronized(memory)
            return

        text = self.index_text(memory)
        metadata = self.index_metadata(memory)
        if (
            self.vector_store is not None or self.vector_engine is not None
        ) and self.embedding_client is None:
            raise RuntimeError("embedding client not initialized")
        vector = None
        if self.vector_store is not None or self.vector_engine is not None:
            vector = self.embedding_client.embed(text)
        if self.vector_store is not None:
            self.vector_store.update(memory_id, vector)
            self.vector_store.save()
        if self.vector_engine is not None:
            self.vector_engine.insert(memory_id, text, vector, metadata=metadata)
        if self.keyword_search is not None:
            self.keyword_search.update(
                memory_id, text, json.dumps(metadata, ensure_ascii=False)
            )
        if self.memory_lookup is not None:
            self.memory_lookup[memory_id] = memory
        self._clear_cache()
        self._mark_synchronized(memory)

    def _mark_synchronized(self, memory: Memory) -> None:
        """Clear pending_index only after all configured runtime projections succeed."""
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        mark_indexed = getattr(repo, "mark_indexed", None)
        if mark_indexed is not None:
            mark_indexed([memory.memory_id], time.time_ns())

    def _clear_cache(self) -> None:
        if self.search_cache is not None:
            self.search_cache.clear()
