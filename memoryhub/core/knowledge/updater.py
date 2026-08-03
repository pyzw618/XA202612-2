"""Semantic consolidation for extracted knowledge memories.

This module keeps the public KnowledgeMemory and repository contracts unchanged.
It consolidates repeated observations into one active memory while preserving
source evidence and making retries idempotent.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from memoryhub.adapter.schemas import KnowledgeMemory, MemoryStatus


class KnowledgeUpdater:
    """Merge semantically equivalent knowledge without creating duplicate rows."""

    def __init__(self, *, write_service) -> None:
        self.write_service = write_service
        self.know_repo = getattr(write_service, "know_repo", None)

    def add(self, memory: KnowledgeMemory) -> str:
        if self.know_repo is None:
            self.write_service.upsert_memory(memory)
            return memory.memory_id

        exact = self.know_repo.get_by_id(memory.memory_id)
        if exact is not None and exact.user_id == memory.user_id:
            incoming_events = {e.event_id for e in memory.evidences if e.event_id}
            existing_events = {e.event_id for e in exact.evidences if e.event_id}
            if incoming_events and not incoming_events.issubset(existing_events):
                exact = self._merge(
                    exact,
                    memory,
                    add_support=not bool(incoming_events & existing_events),
                )
            # Also repairs an index/evidence failure after the SQLite write succeeded.
            self.write_service.upsert_memory(exact)
            return exact.memory_id

        existing = self._find_equivalent(memory)
        if existing is None:
            self.write_service.upsert_memory(memory)
            return memory.memory_id

        incoming_events = {e.event_id for e in memory.evidences if e.event_id}
        existing_events = {e.event_id for e in existing.evidences if e.event_id}
        if incoming_events and incoming_events.issubset(existing_events):
            # Retry after SQLite succeeded but a downstream index write failed.
            self.write_service.upsert_memory(existing)
            return existing.memory_id

        merged = self._merge(
            existing,
            memory,
            add_support=not bool(incoming_events & existing_events),
        )
        self.write_service.upsert_memory(merged)
        return merged.memory_id

    def _find_equivalent(self, memory: KnowledgeMemory) -> KnowledgeMemory | None:
        candidates = self.know_repo.list_all(status="active", user_id=memory.user_id)
        best = None
        best_score = 0.0
        for candidate in candidates:
            if candidate.knowledge_type != memory.knowledge_type:
                continue
            if not self._scope_compatible(candidate, memory):
                continue
            score = self._similarity(candidate, memory)
            threshold = (
                0.58
                if str(getattr(memory.knowledge_type, "value", memory.knowledge_type))
                in {"workflow", "template"}
                else 0.82
            )
            if score >= threshold and score > best_score:
                best = candidate
                best_score = score
        return best

    @staticmethod
    def _scope_compatible(left: KnowledgeMemory, right: KnowledgeMemory) -> bool:
        for field in ("scene", "task_type", "app"):
            a = getattr(left.scope, field, "")
            b = getattr(right.scope, field, "")
            if a and b and a != b:
                return False
        return True

    def _similarity(self, left: KnowledgeMemory, right: KnowledgeMemory) -> float:
        left_steps = {self._normalize(item) for item in left.steps if self._normalize(item)}
        right_steps = {self._normalize(item) for item in right.steps if self._normalize(item)}
        union = left_steps | right_steps
        step_score = len(left_steps & right_steps) / len(union) if union else 0.0
        name_score = SequenceMatcher(
            None, self._normalize(left.name), self._normalize(right.name)
        ).ratio()
        content_score = SequenceMatcher(
            None, self._normalize(left.content), self._normalize(right.content)
        ).ratio()
        if left_steps or right_steps:
            return 0.6 * step_score + 0.25 * name_score + 0.15 * content_score
        return 0.65 * name_score + 0.35 * content_score

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^0-9a-zA-Z一-龥]+", "", str(value or "").lower())

    def _merge(
        self,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
        *,
        add_support: bool,
    ) -> KnowledgeMemory:
        merged = existing.model_copy(deep=True)
        merged.steps = self._ordered_union(existing.steps, incoming.steps, limit=12)
        merged.tools = self._ordered_union(existing.tools, incoming.tools, limit=20)
        merged.evidences = self._merge_evidences(existing.evidences, incoming.evidences)
        if len(incoming.content) > len(existing.content):
            merged.content = incoming.content
        if len(incoming.name) > len(existing.name):
            merged.name = incoming.name
        if incoming.template_body and len(incoming.template_body) >= len(existing.template_body):
            merged.template_body = incoming.template_body
        old_total = max(1, existing.total_count)
        if add_support:
            incoming_total = max(1, incoming.total_count)
            merged.total_count = old_total + incoming_total
            merged.success_count = max(0, existing.success_count) + max(0, incoming.success_count)
            weighted_confidence = (
                existing.confidence * old_total + incoming.confidence * incoming_total
            ) / merged.total_count
            support_bonus = min(0.08, 0.01 * max(0, merged.total_count - 1))
            merged.confidence = round(min(0.98, weighted_confidence + support_bonus), 4)
        else:
            # A partially overlapping evidence set is the same execution being
            # completed across requests, not another successful reuse.
            merged.total_count = existing.total_count
            merged.success_count = existing.success_count
            merged.confidence = max(existing.confidence, incoming.confidence)
        merged.version = max(1, existing.version) + 1
        merged.status = MemoryStatus.ACTIVE
        merged.updated_at = datetime.now(timezone.utc)
        return merged

    @staticmethod
    def _ordered_union(left: list[str], right: list[str], *, limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in [*left, *right]:
            cleaned = str(value).strip()
            key = KnowledgeUpdater._normalize(cleaned)
            if cleaned and key and key not in seen:
                result.append(cleaned)
                seen.add(key)
        return result[:limit]

    @staticmethod
    def _merge_evidences(left, right):
        result = []
        seen = set()
        for evidence in [*left, *right]:
            key = evidence.event_id or evidence.evidence_id
            if key and key in seen:
                continue
            result.append(evidence)
            if key:
                seen.add(key)
        return result
