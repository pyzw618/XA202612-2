"""Synchronize persisted facts with all configured runtime retrieval projections."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from .models import ConflictResult, Fact


@dataclass(slots=True)
class FactSyncResult:
    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class FactIndexService:
    """Keep fact SQLite state and the shared runtime indexes eventually consistent."""

    def __init__(
        self,
        *,
        fact_store,
        vector_store=None,
        vector_engine=None,
        keyword_search=None,
        memory_lookup=None,
        search_cache=None,
        embedding_client=None,
    ) -> None:
        self.fact_store = fact_store
        self.vector_store = vector_store
        self.vector_engine = vector_engine
        self.keyword_search = keyword_search
        self.memory_lookup = memory_lookup if memory_lookup is not None else {}
        self.search_cache = search_cache
        self.embedding_client = embedding_client

    def index_text(self, fact: Fact) -> str:
        return self.fact_store.render_fact(fact)

    def index_metadata(self, fact: Fact) -> dict:
        return {
            "memory_type": "fact",
            "user_id": fact.user_id,
            "content": self.index_text(fact),
            "confidence": fact.confidence,
            "scope": {"scope": fact.scope, "project_id": fact.project_id or ""},
            "subject_id": fact.subject_id,
            "predicate_id": fact.predicate_id,
            "object_id": fact.object_id,
            "status": fact.status,
        }

    def sync_fact(self, fact: Fact, *, remove: bool = False) -> None:
        remove = remove or fact.status != "active"
        fact_id = fact.fact_id
        if remove:
            # Publish the inactive source-of-truth object before external deletes.
            self.memory_lookup[fact_id] = fact
            if self.vector_store is not None:
                self.vector_store.delete(fact_id)
                self.vector_store.save()
            if self.vector_engine is not None:
                self.vector_engine.delete(fact_id)
            if self.keyword_search is not None:
                self.keyword_search.delete(fact_id)
            self.memory_lookup.pop(fact_id, None)
            self._mark_indexed(fact)
            self._clear_cache()
            return

        text = self.index_text(fact)
        metadata = self.index_metadata(fact)
        if (self.vector_store is not None or self.vector_engine is not None) and self.embedding_client is None:
            raise RuntimeError("embedding client not initialized")
        vector = None
        if self.vector_store is not None or self.vector_engine is not None:
            vector = self.embedding_client.embed(text)
        if self.vector_store is not None:
            self.vector_store.update(fact_id, vector)
            self.vector_store.save()
        if self.vector_engine is not None:
            upsert = getattr(self.vector_engine, "upsert", None)
            if callable(upsert):
                upsert(fact_id, text, vector, metadata=metadata)
            else:
                self.vector_engine.insert(fact_id, text, vector, metadata=metadata)
        if self.keyword_search is not None:
            self.keyword_search.update(fact_id, text, json.dumps(metadata, ensure_ascii=False))
        self.memory_lookup[fact_id] = fact
        self._mark_indexed(fact)
        self._clear_cache()

    def sync_pending(self, limit: int = 100) -> FactSyncResult:
        result = FactSyncResult()
        for fact in self.fact_store.list_pending_facts(limit=limit):
            try:
                self.sync_fact(fact)
            except Exception:
                result.failed.append(fact.fact_id)
            else:
                result.succeeded.append(fact.fact_id)
        return result

    def sync_result(self, result: ConflictResult) -> None:
        existing = result.existing_fact
        if existing is not None:
            current = self.fact_store.get_fact(existing.fact_id, user_id=existing.user_id)
            if current is not None:
                self.sync_fact(current)
        current = self.fact_store.get_fact(result.new_fact.fact_id, user_id=result.new_fact.user_id)
        if current is not None:
            self.sync_fact(current)

    def _mark_indexed(self, fact: Fact) -> None:
        version = time.time_ns()
        if not self.fact_store.mark_indexed(fact.fact_id, version, user_id=fact.user_id):
            raise RuntimeError("fact projection state was not persisted")
        fact.pending_index = False
        fact.index_version = version

    def _clear_cache(self) -> None:
        if self.search_cache is not None:
            self.search_cache.clear()
