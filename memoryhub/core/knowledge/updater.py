"""Semantic consolidation and conflict auditing for knowledge memories."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from memoryhub.adapter.schemas import (
    ConflictRecord,
    KnowledgeConflictResolution,
    KnowledgeMemory,
    MemoryDecision,
    MemoryStatus,
)
from memoryhub.config import KnowledgeMergeConfig
from memoryhub.core.knowledge.confidence import KnowledgeConfidenceCalculator
from memoryhub.core.knowledge.prompts import (
    KNOWLEDGE_CONFLICT_SYSTEM,
    KNOWLEDGE_CONFLICT_USER,
)
from memoryhub.core.memory.evidence import EvidenceMerger
from memoryhub.core.memory.llm import StructuredLLMAdapter

logger = logging.getLogger(__name__)


class KnowledgeUpdater:
    """Merge equivalent knowledge and audit ambiguous semantic collisions."""

    def __init__(
        self,
        *,
        write_service,
        merge_config: KnowledgeMergeConfig | None = None,
        conflict_repo=None,
        llm_client=None,
    ) -> None:
        self.write_service = write_service
        self.know_repo = getattr(write_service, "know_repo", None)
        self.config = merge_config or KnowledgeMergeConfig()
        self.conflict_repo = conflict_repo
        self.confidence_calculator = KnowledgeConfidenceCalculator()
        self._adapter = (
            StructuredLLMAdapter(llm_client)
            if llm_client is not None
            and callable(getattr(llm_client, "generate", None))
            else None
        )

    def add(self, memory: KnowledgeMemory) -> str:
        if self.know_repo is None:
            self.write_service.upsert_memory(memory, action=MemoryDecision.NEW)
            return memory.memory_id

        exact = self.know_repo.get_by_id(memory.memory_id)
        if exact is not None and exact.user_id == memory.user_id:
            incoming_events = {e.event_id for e in memory.evidences if e.event_id}
            existing_events = {e.event_id for e in exact.evidences if e.event_id}
            has_new_evidence = bool(incoming_events - existing_events)
            if not has_new_evidence and not self._has_semantic_delta(exact, memory):
                logger.debug("knowledge add: dedup %s", memory.memory_id)
                return exact.memory_id
            if not self._has_semantic_delta(exact, memory):
                reinforced = self._reinforce(
                    exact,
                    memory,
                    add_support=has_new_evidence
                    and not bool(incoming_events & existing_events),
                )
                if has_new_evidence:
                    reinforced.version = max(1, exact.version) + 1
                self.write_service.upsert_memory(
                    reinforced, action=MemoryDecision.REINFORCE
                )
                logger.info("knowledge add: reinforce %s -> v%s", exact.memory_id, reinforced.version)
                return reinforced.memory_id
            merged = self._merge(
                exact,
                memory,
                add_support=has_new_evidence
                and not bool(incoming_events & existing_events),
            )
            self._archive_and_save_version(exact, merged)
            logger.info("knowledge add: merge %s -> %s", exact.memory_id, merged.memory_id)
            return merged.memory_id

        existing, score = self._find_best_candidate(memory)
        if existing is None or score < self.config.equivalent_threshold:
            if existing is not None and score >= self.config.conflict_threshold:
                resolution = self._llm_judge_conflict(existing, memory)
                if resolution == KnowledgeConflictResolution.EQUIVALENT:
                    merged = self._merge(
                        existing,
                        memory,
                        add_support=bool(
                            {e.event_id for e in memory.evidences if e.event_id}
                            - {e.event_id for e in existing.evidences if e.event_id}
                        ),
                    )
                    self._archive_and_save_version(existing, merged)
                    logger.info(
                        "knowledge add: llm-equivalent merge %s -> %s",
                        existing.memory_id,
                        merged.memory_id,
                    )
                    return merged.memory_id
                if resolution == KnowledgeConflictResolution.CONCRETE_CONFLICT:
                    merged = self._llm_merge_conflict(existing, memory)
                    self._archive_and_save_version(existing, merged)
                    logger.info(
                        "knowledge add: llm-concrete-conflict merge %s -> %s",
                        existing.memory_id,
                        merged.memory_id,
                    )
                    return merged.memory_id
                # NO_CONFLICT → save as NEW and record
                self._record_ambiguous_conflict(existing, memory, score)
                logger.info(
                    "knowledge add: llm-no-conflict score=%.2f %s vs %s",
                    score,
                    existing.memory_id,
                    memory.memory_id,
                )
            self.write_service.upsert_memory(memory, action=MemoryDecision.NEW)
            return memory.memory_id

        incoming_events = {e.event_id for e in memory.evidences if e.event_id}
        existing_events = {e.event_id for e in existing.evidences if e.event_id}
        if incoming_events and incoming_events.issubset(existing_events):
            self.write_service.upsert_memory(existing, action=MemoryDecision.DUPLICATE)
            logger.debug("knowledge add: duplicate %s", existing.memory_id)
            return existing.memory_id

        if not self._has_semantic_delta(existing, memory):
            reinforced = self._reinforce(
                existing,
                memory,
                add_support=not bool(incoming_events & existing_events),
            )
            self.write_service.upsert_memory(
                reinforced, action=MemoryDecision.REINFORCE
            )
            logger.info("knowledge add: reinforce %s -> v%s", existing.memory_id, reinforced.version)
            return reinforced.memory_id
        merged = self._merge(
            existing,
            memory,
            add_support=not bool(incoming_events & existing_events),
        )
        self._archive_and_save_version(existing, merged)
        logger.info("knowledge add: merge %s -> %s", existing.memory_id, merged.memory_id)
        return merged.memory_id

    def _find_equivalent(self, memory: KnowledgeMemory) -> KnowledgeMemory | None:
        candidate, score = self._find_best_candidate(memory)
        return candidate if score >= self.config.equivalent_threshold else None

    def _find_best_candidate(
        self, memory: KnowledgeMemory
    ) -> tuple[KnowledgeMemory | None, float]:
        candidates = self.know_repo.list_all(status="active", user_id=memory.user_id)
        best = None
        best_score = 0.0
        for candidate in candidates:
            if candidate.knowledge_type != memory.knowledge_type:
                continue
            if not self._scope_compatible(candidate, memory):
                continue
            score = self._similarity(candidate, memory)
            if score > best_score:
                best = candidate
                best_score = score
        return best, best_score

    @staticmethod
    def _scope_compatible(left: KnowledgeMemory, right: KnowledgeMemory) -> bool:
        for field in ("scene", "task_type", "app"):
            a = getattr(left.scope, field, "")
            b = getattr(right.scope, field, "")
            if a and b and a != b:
                return False
        return True

    def _similarity(self, left: KnowledgeMemory, right: KnowledgeMemory) -> float:
        left_steps = {
            self._normalize(item) for item in left.steps if self._normalize(item)
        }
        right_steps = {
            self._normalize(item) for item in right.steps if self._normalize(item)
        }
        union = left_steps | right_steps
        step_score = len(left_steps & right_steps) / len(union) if union else 0.0
        name_score = SequenceMatcher(
            None, self._normalize(left.name), self._normalize(right.name)
        ).ratio()
        content_score = SequenceMatcher(
            None, self._normalize(left.content), self._normalize(right.content)
        ).ratio()
        weights = (
            self.config.name_weight,
            self.config.content_weight,
            self.config.steps_weight if union else 0.0,
        )
        total = sum(weights)
        return (
            name_score * weights[0]
            + content_score * weights[1]
            + step_score * weights[2]
        ) / total

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^0-9a-zA-Z一-龥]+", "", str(value or "").lower())

    # ─── LLM 冲突裁决 ──────────────────────────────────────────────────

    def _llm_available(self) -> bool:
        return self._adapter is not None

    def _llm_judge_conflict(
        self,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
    ) -> KnowledgeConflictResolution:
        """调用 LLM 判断两条知识是等价、兼容还是真正冲突。

        LLM 不可用时降级为 NO_CONFLICT（分别保留）。
        """
        if not self._llm_available():
            return KnowledgeConflictResolution.NO_CONFLICT

        old_type = str(
            getattr(existing.knowledge_type, "value", existing.knowledge_type)
        )
        new_type = str(
            getattr(incoming.knowledge_type, "value", incoming.knowledge_type)
        )
        user_msg = KNOWLEDGE_CONFLICT_USER.format(
            old_name=existing.name,
            old_type=old_type,
            old_content=existing.content,
            old_steps=", ".join(existing.steps) if existing.steps else "(无)",
            old_tools=", ".join(existing.tools) if existing.tools else "(无)",
            old_confidence=f"{existing.confidence:.2f}",
            old_version=existing.version,
            new_name=incoming.name,
            new_type=new_type,
            new_content=incoming.content,
            new_steps=", ".join(incoming.steps) if incoming.steps else "(无)",
            new_tools=", ".join(incoming.tools) if incoming.tools else "(无)",
            new_confidence=f"{incoming.confidence:.2f}",
            new_version=incoming.version,
        )

        try:
            data = self._adapter.generate_json(
                task_name="knowledge_conflict_judgment",
                system_prompt=KNOWLEDGE_CONFLICT_SYSTEM,
                prompt=user_msg,
                parser=lambda value: (
                    value
                    if isinstance(value, dict)
                    else (_ for _ in ()).throw(
                        ValueError("LLM response must be an object")
                    )
                ),
            )
            judgment = str(data.get("judgment", "no_conflict")).strip()
            allowed = {item.value for item in KnowledgeConflictResolution}
            if judgment not in allowed:
                judgment = KnowledgeConflictResolution.NO_CONFLICT.value
            resolution = KnowledgeConflictResolution(judgment)
            logger.info(
                "knowledge llm judgment: %s for %s vs %s",
                resolution.value,
                existing.memory_id,
                incoming.memory_id,
            )
            return resolution

        except Exception as exc:
            logger.warning(
                "knowledge llm judgment failed: %s, fallback to no_conflict", exc
            )
            return KnowledgeConflictResolution.NO_CONFLICT

    def _llm_merge_conflict(
        self,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
    ) -> KnowledgeMemory:
        """LLM 裁决为 concrete_conflict 时，请求 LLM 合并两条知识。"""
        old_type = str(
            getattr(existing.knowledge_type, "value", existing.knowledge_type)
        )
        new_type = str(
            getattr(incoming.knowledge_type, "value", incoming.knowledge_type)
        )
        user_msg = KNOWLEDGE_CONFLICT_USER.format(
            old_name=existing.name,
            old_type=old_type,
            old_content=existing.content,
            old_steps=", ".join(existing.steps) if existing.steps else "(无)",
            old_tools=", ".join(existing.tools) if existing.tools else "(无)",
            old_confidence=f"{existing.confidence:.2f}",
            old_version=existing.version,
            new_name=incoming.name,
            new_type=new_type,
            new_content=incoming.content,
            new_steps=", ".join(incoming.steps) if incoming.steps else "(无)",
            new_tools=", ".join(incoming.tools) if incoming.tools else "(无)",
            new_confidence=f"{incoming.confidence:.2f}",
            new_version=incoming.version,
        )

        try:
            data = self._adapter.generate_json(
                task_name="knowledge_conflict_merge",
                system_prompt=KNOWLEDGE_CONFLICT_SYSTEM,
                prompt=user_msg,
                parser=lambda value: (
                    value
                    if isinstance(value, dict)
                    else (_ for _ in ()).throw(
                        ValueError("LLM response must be an object")
                    )
                ),
            )
            merged = incoming.model_copy(deep=True)
            merged.memory_id = f"{existing.memory_id}_v{existing.version + 1}"
            merged.parent_id = existing.memory_id
            merged.name = str(data.get("merged_name", incoming.name))
            merged.content = str(data.get("merged_content", incoming.content))
            merged_steps = data.get("merged_steps")
            if isinstance(merged_steps, list) and merged_steps:
                merged.steps = [str(s) for s in merged_steps]
            else:
                merged.steps = self._ordered_union(
                    existing.steps, incoming.steps, limit=12
                )
            merged_tools = data.get("merged_tools")
            if isinstance(merged_tools, list) and merged_tools:
                merged.tools = [str(t) for t in merged_tools]
            else:
                merged.tools = self._ordered_union(
                    existing.tools, incoming.tools, limit=20
                )
            merged.evidences = self._merge_evidences(
                existing.evidences, incoming.evidences
            )
            merged.total_count = max(1, existing.total_count) + max(
                1, incoming.total_count
            )
            merged.success_count = min(
                merged.total_count,
                max(0, existing.success_count) + max(0, incoming.success_count),
            )
            merged.confidence = self.confidence_calculator.merge_score(
                existing_confidence=existing.confidence,
                incoming_confidence=incoming.confidence,
                success_count=merged.success_count,
                total_count=merged.total_count,
                evidence_count=len(merged.evidences),
            )
            merged.version = max(1, existing.version) + 1
            merged.status = MemoryStatus.ACTIVE
            merged.updated_at = datetime.now(timezone.utc)
            return merged

        except Exception as exc:
            logger.warning("knowledge llm merge failed: %s, fallback to simple merge", exc)
            return self._merge(existing, incoming, add_support=True)

    def _record_ambiguous_conflict(
        self,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
        score: float,
    ) -> None:
        if self.conflict_repo is None:
            return
        digest = hashlib.sha256(
            f"{existing.user_id}|{existing.memory_id}|{incoming.memory_id}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        record = ConflictRecord(
            conflict_id=f"conf_know_{digest}",
            user_id=existing.user_id,
            old_memory_id=existing.memory_id,
            new_memory_id=incoming.memory_id,
            memory_type="knowledge",
            old_content=existing.content,
            new_content=incoming.content,
            conflict_field="semantic_equivalence",
            reason=f"knowledge.semantic_similarity={score:.4f}",
        )
        self.conflict_repo.save(record)

    def _has_semantic_delta(
        self, existing: KnowledgeMemory, incoming: KnowledgeMemory
    ) -> bool:
        return self._semantic_fingerprint(existing) != self._semantic_fingerprint(
            incoming
        )

    def _semantic_fingerprint(self, memory: KnowledgeMemory) -> tuple:
        return (
            self._normalize(memory.name),
            self._normalize(memory.content),
            tuple(
                self._normalize(step) for step in memory.steps if self._normalize(step)
            ),
            tuple(
                self._normalize(tool) for tool in memory.tools if self._normalize(tool)
            ),
            self._normalize(memory.template_body),
            (
                memory.status.value
                if hasattr(memory.status, "value")
                else str(memory.status)
            ),
        )

    def _reinforce(
        self, existing: KnowledgeMemory, incoming: KnowledgeMemory, *, add_support: bool
    ) -> KnowledgeMemory:
        """Preserve the active semantic record when only evidence has changed."""
        reinforced = existing.model_copy(deep=True)
        reinforced.evidences = self._merge_evidences(
            existing.evidences, incoming.evidences
        )
        if add_support:
            reinforced.total_count = max(1, existing.total_count) + max(
                1, incoming.total_count
            )
            reinforced.success_count = min(
                reinforced.total_count,
                max(0, existing.success_count) + max(0, incoming.success_count),
            )
            # Evidence revisions remain addressable through the stable memory ID.
            reinforced.version = max(1, existing.version) + 1
        reinforced.confidence = self.confidence_calculator.merge_score(
            existing_confidence=existing.confidence,
            incoming_confidence=incoming.confidence,
            success_count=reinforced.success_count,
            total_count=reinforced.total_count,
            evidence_count=len(reinforced.evidences),
        )
        reinforced.updated_at = datetime.now(timezone.utc)
        return reinforced

    def _archive_and_save_version(
        self, existing: KnowledgeMemory, successor: KnowledgeMemory
    ) -> None:
        archived = existing.model_copy(deep=True)
        archived.status = MemoryStatus.ARCHIVED
        archived.updated_at = datetime.now(timezone.utc)
        self.write_service.upsert_memory(archived, action=MemoryDecision.REVISE)
        self.write_service.upsert_memory(successor, action=MemoryDecision.REVISE)

    def _merge(
        self,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
        *,
        add_support: bool,
    ) -> KnowledgeMemory:
        merged = incoming.model_copy(deep=True)
        if not merged.memory_id or merged.memory_id == existing.memory_id:
            merged.memory_id = f"{existing.memory_id}_v{existing.version + 1}"
        merged.parent_id = existing.memory_id
        merged.steps = self._ordered_union(existing.steps, incoming.steps, limit=12)
        merged.tools = self._ordered_union(existing.tools, incoming.tools, limit=20)
        merged.evidences = self._merge_evidences(existing.evidences, incoming.evidences)
        if len(incoming.content) > len(existing.content):
            merged.content = incoming.content
        if len(incoming.name) > len(existing.name):
            merged.name = incoming.name
        if incoming.template_body and len(incoming.template_body) >= len(
            existing.template_body
        ):
            merged.template_body = incoming.template_body
        old_total = max(1, existing.total_count)
        if add_support:
            incoming_total = max(1, incoming.total_count)
            merged.total_count = old_total + incoming_total
            merged.success_count = min(
                merged.total_count,
                max(0, existing.success_count) + max(0, incoming.success_count),
            )
        else:
            merged.total_count = existing.total_count
            merged.success_count = existing.success_count
        merged.confidence = self.confidence_calculator.merge_score(
            existing_confidence=existing.confidence,
            incoming_confidence=incoming.confidence,
            success_count=merged.success_count,
            total_count=merged.total_count,
            evidence_count=len(merged.evidences),
        )
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
        """Compatibility wrapper around the shared deterministic evidence merger."""
        return EvidenceMerger().normalize_and_merge([*left, *right])
