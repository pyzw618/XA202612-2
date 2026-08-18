"""Shared idempotent execution path for optional memory extractors."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from memoryhub.adapter.schemas import (
    ExtractionType,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
)
from memoryhub.core.knowledge.updater import KnowledgeUpdater

logger = logging.getLogger(__name__)


class ExtractionExecutor:
    """Execute one extractor against gate-approved, persisted event models."""

    def __init__(
        self,
        *,
        memory_write_service,
        preference_extractor=None,
        preference_updater=None,
        knowledge_extractor=None,
        fact_ingestion_adapter=None,
        knowledge_merge_config=None,
        conflict_repo=None,
        preference_handler=None,
        knowledge_handler=None,
        fact_handler=None,
        fact_mode: str = "legacy",
    ) -> None:
        self.memory_write_service = memory_write_service
        self.preference_extractor = preference_extractor
        self.preference_updater = preference_updater
        self.knowledge_extractor = knowledge_extractor
        self.knowledge_updater = KnowledgeUpdater(
            write_service=memory_write_service,
            merge_config=knowledge_merge_config,
            conflict_repo=conflict_repo,
        )
        self.fact_ingestion_adapter = fact_ingestion_adapter
        self.preference_handler = preference_handler
        self.knowledge_handler = knowledge_handler
        self.fact_handler = fact_handler
        # "knowledge" 模式：事实以 knowledge(FACT) 产出（run_knowledge 内），run_fact 停用
        self.fact_mode = fact_mode

    @staticmethod
    def execution_key(extractor_type: str, event_ids: list[str]) -> str:
        kind = (
            extractor_type.value
            if hasattr(extractor_type, "value")
            else str(extractor_type)
        )
        normalized = "|".join(sorted(dict.fromkeys(event_ids)))
        return hashlib.sha256(f"{kind}|{normalized}".encode("utf-8")).hexdigest()

    @staticmethod
    def _memory_id(prefix: str, execution_key: str, index: int, memory: Any) -> str:
        if isinstance(memory, PreferenceMemory):
            stable = {
                "user_id": memory.user_id,
                "preference_type": str(
                    getattr(memory.preference_type, "value", memory.preference_type)
                ),
                "text": memory.text,
                "payload": memory.payload,
                "scope": memory.scope.model_dump(mode="json"),
                "is_global": memory.is_global,
            }
        else:
            stable = {
                "user_id": memory.user_id,
                "knowledge_type": str(
                    getattr(memory.knowledge_type, "value", memory.knowledge_type)
                ),
                "name": memory.name,
                "content": memory.content,
                "steps": memory.steps,
                "tools": memory.tools,
                "scope": memory.scope.model_dump(mode="json"),
            }
        digest = hashlib.sha256(
            (
                execution_key
                + "|"
                + str(index)
                + "|"
                + json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)
            ).encode("utf-8")
        ).hexdigest()
        return f"{prefix}_{digest[:27]}"

    @staticmethod
    def _uses_generated_id(memory_id: str, prefix: str) -> bool:
        return re.fullmatch(rf"{prefix}_[0-9a-f]{{8}}", memory_id or "") is not None

    def run_preference(self, event: MemoryEvent) -> int:
        if self.preference_handler is not None:
            decisions = self.preference_handler.process(event)
            execution_key = self.execution_key(
                ExtractionType.PREFERENCE, [event.event_id]
            )
            for index, decision in enumerate(decisions):
                candidate = decision.candidate
                if candidate is not None and self._uses_generated_id(
                    candidate.payload.memory_id, "pref"
                ):
                    candidate.payload.memory_id = self._memory_id(
                        "pref", execution_key, index, candidate.payload
                    )
                self.preference_handler.apply(decision)
            return len(decisions)
        if self.preference_extractor is None:
            return 0
        execution_key = self.execution_key(ExtractionType.PREFERENCE, [event.event_id])
        memories = list(self.preference_extractor.extract(event))
        for index, memory in enumerate(memories):
            if self._uses_generated_id(memory.memory_id, "pref"):
                memory.memory_id = self._memory_id("pref", execution_key, index, memory)
            existing = self._get_existing(memory)
            if existing is not None:
                # Repair an index/evidence failure that occurred after SQLite save.
                self.memory_write_service.upsert_memory(existing)
                continue
            if self.preference_updater is not None:
                self.preference_updater.add(memory)
            else:
                self.memory_write_service.upsert_memory(memory)
        return len(memories)

    def run_knowledge(self, events: list[MemoryEvent]) -> int:
        logger.info(
            "run_knowledge: events=%d, handler=%s, extractor=%s",
            len(events),
            self.knowledge_handler is not None,
            self.knowledge_extractor is not None,
        )
        if self.knowledge_handler is not None and events:
            try:
                decisions = self.knowledge_handler.process(events)
            except Exception:
                logger.exception("knowledge handler.process failed")
                raise
            logger.info("run_knowledge: handler produced %d decisions", len(decisions))
            for index, decision in enumerate(decisions):
                candidate = decision.candidate
                if candidate is not None and self._uses_generated_id(
                    candidate.payload.memory_id, "know"
                ):
                    semantic_key = self.execution_key(
                        ExtractionType.KNOWLEDGE,
                        [
                            candidate.payload.user_id,
                            str(
                                getattr(
                                    candidate.payload.knowledge_type,
                                    "value",
                                    candidate.payload.knowledge_type,
                                )
                            ),
                            candidate.payload.scope.scene,
                            candidate.payload.scope.task_type,
                            candidate.payload.scope.app,
                        ],
                    )
                    candidate.payload.memory_id = self._memory_id(
                        "know", semantic_key, index, candidate.payload
                    )
                logger.info(
                    "run_knowledge: apply decision[%d] action=%s id=%s",
                    index,
                    getattr(decision, "action", "?"),
                    getattr(candidate.payload, "memory_id", "?") if candidate else "None",
                )
                self.knowledge_handler.apply(decision)
            return len(decisions)
        if self.knowledge_extractor is None or not events:
            return 0
        memories = list(self.knowledge_extractor.extract_from_trajectory(events))
        for index, memory in enumerate(memories):
            if self._uses_generated_id(memory.memory_id, "know"):
                # Knowledge identity is semantic rather than request-batch based.  The
                # updater still performs fuzzy consolidation for evolving trajectories.
                semantic_key = self.execution_key(
                    ExtractionType.KNOWLEDGE,
                    [
                        memory.user_id,
                        str(
                            getattr(
                                memory.knowledge_type, "value", memory.knowledge_type
                            )
                        ),
                        memory.scope.scene,
                        memory.scope.task_type,
                        memory.scope.app,
                    ],
                )
                memory.memory_id = self._memory_id("know", semantic_key, index, memory)
            self.knowledge_updater.add(memory)

        # fact_mode="knowledge"：事实以 knowledge(FACT) 产出（复用 §4.8.3 extract_facts +
        # §4.8.5 冲突 matcher），与旧 Fact 管线彻底隔离，避免双写。
        if self.fact_mode == "knowledge" and self.knowledge_extractor is not None:
            for fact in self.knowledge_extractor.extract_facts(events):
                self.knowledge_updater.add(fact)
        return len(memories)

    def run_fact(self, event: MemoryEvent) -> int:
        if self.fact_mode == "knowledge":
            return 0  # FACT 已由 run_knowledge 产出，跳过旧 Fact 管线
        if self.fact_handler is not None:
            return sum(
                1
                for decision in self.fact_handler.process_and_apply(event)
                if decision.action not in {"reject", "review"}
            )
        if self.fact_ingestion_adapter is None:
            return 0
        return len(self.fact_ingestion_adapter.ingest_event(event) or [])

    def supports(self, extractor_type: str) -> bool:
        kind = (
            extractor_type.value
            if hasattr(extractor_type, "value")
            else str(extractor_type)
        )
        return {
            ExtractionType.PREFERENCE.value: self.preference_handler is not None
            or self.preference_extractor is not None,
            ExtractionType.KNOWLEDGE.value: self.knowledge_handler is not None
            or self.knowledge_extractor is not None,
            ExtractionType.FACT.value: self.fact_handler is not None
            or self.fact_ingestion_adapter is not None,
        }.get(kind, False)

    def _get_existing(self, memory: PreferenceMemory | KnowledgeMemory):
        repo = (
            getattr(self.memory_write_service, "know_repo", None)
            if memory.memory_type == "knowledge"
            else getattr(self.memory_write_service, "pref_repo", None)
        )
        if repo is None:
            return None
        existing = repo.get_by_id(memory.memory_id)
        if existing is None or existing.user_id != memory.user_id:
            return None
        return existing
