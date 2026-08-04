"""Synchronize persisted facts with the main retrieval indexes."""

from __future__ import annotations

import json

from .models import ConflictResult, Fact


class FactIndexService:
    """Keep fact SQLite state and the shared runtime indexes consistent."""

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
            "scope": {
                "scope": fact.scope,
                "project_id": fact.project_id or "",
            },
            "subject_id": fact.subject_id,
            "predicate_id": fact.predicate_id,
            "object_id": fact.object_id,
            "status": fact.status,
        }

    def sync_fact(self, fact: Fact, *, remove: bool = False) -> None:
        remove = remove or fact.status != "active"
        fact_id = fact.fact_id
        if remove:
            if self.vector_store is not None:
                self.vector_store.delete(fact_id)
                self.vector_store.save()
            if self.vector_engine is not None:
                self.vector_engine.delete(fact_id)
            if self.keyword_search is not None:
                self.keyword_search.delete(fact_id)
            self.memory_lookup.pop(fact_id, None)
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
            self.vector_engine.insert(fact_id, text, vector, metadata=metadata)
        if self.keyword_search is not None:
            self.keyword_search.update(
                fact_id, text, json.dumps(metadata, ensure_ascii=False)
            )
        self.memory_lookup[fact_id] = fact
        self._clear_cache()

    def sync_result(self, result: ConflictResult) -> None:
        existing = result.existing_fact
        if existing is not None:
            current = self.fact_store.get_fact(
                existing.fact_id, user_id=existing.user_id
            )
            if current is not None:
                self.sync_fact(current)
        current = self.fact_store.get_fact(
            result.new_fact.fact_id, user_id=result.new_fact.user_id
        )
        if current is not None:
            self.sync_fact(current)

    def _clear_cache(self) -> None:
        if self.search_cache is not None:
            self.search_cache.clear()
