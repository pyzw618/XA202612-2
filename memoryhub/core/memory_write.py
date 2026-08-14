"""Unified persistence and runtime-index synchronization for extracted memories."""

from __future__ import annotations

import json
import time
from typing import Any

from memoryhub.adapter.schemas import KnowledgeMemory, MemoryStatus, PreferenceMemory

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

    @staticmethod
    def index_text(memory: Memory) -> str:
        if memory.memory_type == "knowledge":
            parts = [
                memory.name,
                memory.content,
                *memory.steps,
                *memory.tools,
                memory.template_body,
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
            "safety": dict(
                getattr(memory, "extra_payload", {}).get("safety", {}) or {}
            ),
        }

    def upsert_memory(self, memory: Memory) -> None:
        """Persist through the memory safety gate whenever active content is written."""
        status = (
            memory.status.value
            if hasattr(memory.status, "value")
            else str(memory.status)
        )
        if status == MemoryStatus.ACTIVE.value:
            if self.safety_gate is None:
                if self.require_safety:
                    raise RuntimeError("memory_write.safety_gate_unavailable")
                return self._unsafe_upsert_memory(memory)
            from memoryhub.core.safety.memory_write import guard_memory_write

            guarded = guard_memory_write(
                self.safety_gate,
                memory,
                self._unsafe_upsert_memory,
                operation="memory_sync",
            )
            if guarded.memory is None:
                raise RuntimeError(f"memory_write.blocked:{guarded.action.value}")
            return None
        return self._unsafe_upsert_memory(memory)

    def _unsafe_upsert_memory(self, memory: Memory) -> None:
        """Internal sink invoked only after a verified safe projection or lifecycle action."""
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        repo.save(memory)
        if self.evidence_store is not None:
            # EvidenceStore is append-only, so rewrite the current deduplicated
            # evidence set to make retries and in-place knowledge evolution idempotent.
            self.evidence_store.delete(memory.memory_id)
            if memory.evidences:
                self.evidence_store.batch_save(memory.memory_id, memory.evidences)
        self.sync_memory(memory)

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
