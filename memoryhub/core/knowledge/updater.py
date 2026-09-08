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
    KnowledgeType,
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
from memoryhub.core.fact import FactSemanticService, FactSemanticResult
from memoryhub.storage.database import FactSemanticRepository

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
        self.fact_semantics = None
        if (self.know_repo is not None and hasattr(self.know_repo, "db")
                and getattr(self.know_repo.db, "session_factory", None) is not None):
            self.fact_semantics = FactSemanticService(
                knowledge_repo=self.know_repo,
                semantic_repo=FactSemanticRepository(self.know_repo.db),
            )

    def add(
        self, memory: KnowledgeMemory, *, skip_write_gate: bool = False
    ) -> str:
        if self.know_repo is None:
            self.write_service.upsert_memory(
                memory,
                action=MemoryDecision.NEW,
                skip_write_gate=skip_write_gate,
            )
            return memory.memory_id

        if (
            getattr(memory.knowledge_type, "value", str(memory.knowledge_type))
            == KnowledgeType.FACT.value
        ):
            # 事实性知识走 S/P/O 精确匹配，不走文本相似度（REFACTOR_PLAN_V2 §4.8.5）
            return self._add_fact(memory, skip_write_gate=skip_write_gate)

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
                    reinforced,
                    action=MemoryDecision.REINFORCE,
                    skip_write_gate=skip_write_gate,
                )
                logger.info("knowledge add: reinforce %s -> v%s", exact.memory_id, reinforced.version)
                return reinforced.memory_id
            merged = self._merge(
                exact,
                memory,
                add_support=has_new_evidence
                and not bool(incoming_events & existing_events),
            )
            self._archive_and_save_version(
                exact, merged, skip_write_gate=skip_write_gate
            )
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
                    self._archive_and_save_version(
                        existing, merged, skip_write_gate=skip_write_gate
                    )
                    logger.info(
                        "knowledge add: llm-equivalent merge %s -> %s",
                        existing.memory_id,
                        merged.memory_id,
                    )
                    return merged.memory_id
                if resolution == KnowledgeConflictResolution.CONCRETE_CONFLICT:
                    merged = self._llm_merge_conflict(existing, memory)
                    self._archive_and_save_version(
                        existing, merged, skip_write_gate=skip_write_gate
                    )
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
            self.write_service.upsert_memory(
                memory,
                action=MemoryDecision.NEW,
                skip_write_gate=skip_write_gate,
            )
            return memory.memory_id

        incoming_events = {e.event_id for e in memory.evidences if e.event_id}
        existing_events = {e.event_id for e in existing.evidences if e.event_id}
        if incoming_events and incoming_events.issubset(existing_events):
            self.write_service.upsert_memory(
                existing,
                action=MemoryDecision.DUPLICATE,
                skip_write_gate=skip_write_gate,
            )
            logger.debug("knowledge add: duplicate %s", existing.memory_id)
            return existing.memory_id

        if not self._has_semantic_delta(existing, memory):
            reinforced = self._reinforce(
                existing,
                memory,
                add_support=not bool(incoming_events & existing_events),
            )
            self.write_service.upsert_memory(
                reinforced,
                action=MemoryDecision.REINFORCE,
                skip_write_gate=skip_write_gate,
            )
            logger.info("knowledge add: reinforce %s -> v%s", existing.memory_id, reinforced.version)
            return reinforced.memory_id
        merged = self._merge(
            existing,
            memory,
            add_support=not bool(incoming_events & existing_events),
        )
        self._archive_and_save_version(
            existing, merged, skip_write_gate=skip_write_gate
        )
        logger.info("knowledge add: merge %s -> %s", existing.memory_id, merged.memory_id)
        return merged.memory_id

    def _find_equivalent(self, memory: KnowledgeMemory) -> KnowledgeMemory | None:
        candidate, score = self._find_best_candidate(memory)
        return candidate if score >= self.config.equivalent_threshold else None

    # ─── FACT 冲突 matcher（S/P/O 精确匹配，REFACTOR_PLAN_V2 §4.8.5）──────────

    _MAX_FACT_CONFLICT_VERSIONS = 3

    @staticmethod
    def _attach_fact_semantic(memory: KnowledgeMemory, semantic: FactSemanticResult) -> None:
        """Keep normalized IDs in both legacy metadata and vNext envelope content."""
        fact_semantic = {
            "subject_id": semantic.subject_id,
            "predicate_id": semantic.predicate_id,
            "object_id": semantic.object_id,
            "scope": semantic.scope,
        }
        payload = dict(memory.extra_payload or {})
        payload["fact_semantic"] = fact_semantic
        authority = payload.get("vnext_authority")
        if isinstance(authority, dict):
            authority = dict(authority)
            authority["content"] = {
                **dict(authority.get("content", {}) or {}),
                "fact_semantic": fact_semantic,
            }
            payload["vnext_authority"] = authority
        memory.extra_payload = payload

    @staticmethod
    def _set_fact_outcome(memory: KnowledgeMemory, outcome: str) -> None:
        """Expose the semantic write outcome without duplicating fact state."""
        payload = dict(memory.extra_payload or {})
        payload["fact_outcome"] = outcome
        memory.extra_payload = payload

    def _get_owned_fact(self, memory_id: str, *, user_id: str, tenant_id: str):
        try:
            return self.know_repo.get_by_id(
                memory_id, user_id=user_id, tenant_id=tenant_id
            )
        except TypeError:
            return self.know_repo.get_by_id(memory_id)

    def _ensure_pending_fact_id(self, memory: KnowledgeMemory, *, tenant_id: str) -> None:
        """Keep a pending proposal from overwriting an active deterministic ID.

        Explicit FACT proposals use a stable content hash for idempotency.  A
        later entity-resolution task may have the same raw triple as an
        already-active row, so it needs a separate durable proposal ID.
        """
        current = self._get_owned_fact(
            memory.memory_id, user_id=memory.user_id, tenant_id=tenant_id
        )
        if current is None:
            return
        if getattr(current.status, "value", str(current.status)) != MemoryStatus.ACTIVE.value:
            return
        original_id = memory.memory_id
        suffix = hashlib.sha256(
            f"{tenant_id}|{memory.user_id}|{original_id}|pending".encode("utf-8")
        ).hexdigest()[:22]
        memory.memory_id = f"know_fact_{suffix}"
        payload = dict(memory.extra_payload or {})
        payload["fact_origin_id"] = original_id
        memory.extra_payload = payload

    def _add_fact(
        self, memory: KnowledgeMemory, *, skip_write_gate: bool = False
    ) -> str:
        if self.fact_semantics is not None:
            # Bind legacy FACT rows once, then use canonical entity/predicate IDs
            # for all subsequent comparisons.
            tenant_id = self.fact_semantics._tenant(memory)
            try:
                active_facts = self.know_repo.list_all(
                    status="active", user_id=memory.user_id, tenant_id=tenant_id
                )
            except TypeError:
                active_facts = self.know_repo.list_all(
                    status="active", user_id=memory.user_id
                )
            for old in active_facts:
                if getattr(old.knowledge_type, "value", str(old.knowledge_type)) == KnowledgeType.FACT.value:
                    self.fact_semantics.ensure_memory_binding(old)
            semantic = self.fact_semantics.prepare(memory)
            if semantic.relation == "DECISION_REQUIRED":
                self._ensure_pending_fact_id(memory, tenant_id=semantic.tenant_id)
                memory.status = MemoryStatus.PENDING
                self._set_fact_outcome(memory, "pending")
                decision_task = {
                    **(semantic.decision_task or {}),
                    "expected_version": memory.version,
                }
                memory.extra_payload = {
                    **dict(memory.extra_payload or {}),
                    "fact_decision_task": decision_task,
                }
                self.write_service.upsert_memory(memory, action=MemoryDecision.REVIEW,
                                                  skip_write_gate=skip_write_gate)
                self.fact_semantics.save_decision(memory, decision_task)
                return memory.memory_id
            self._attach_fact_semantic(memory, semantic)
            existing = None
            if semantic.existing_memory_ids:
                existing = self._get_owned_fact(
                    semantic.existing_memory_ids[0],
                    user_id=memory.user_id,
                    tenant_id=semantic.tenant_id,
                )
            if semantic.relation == "CONFLICT":
                self._ensure_pending_fact_id(memory, tenant_id=semantic.tenant_id)
                memory.status = MemoryStatus.PENDING
                self._set_fact_outcome(memory, "pending")
                hard_constraints = {
                    "irreflexive_violation", "domain_type_violation",
                    "range_type_violation", "relation_cycle",
                }
                conflict_types = set(semantic.conflict_types or [semantic.conflict_type])
                allowed_actions = (
                    ["reject", "keep_old"]
                    if conflict_types & hard_constraints
                    else ["replace", "keep_old", "merge", "coexist"]
                )
                memory.extra_payload = {
                    **dict(memory.extra_payload or {}),
                    "fact_decision_task": {
                        "decision_type": "fact_conflict",
                        "allowed_actions": allowed_actions,
                        "expected_version": memory.version,
                        "conflict_type": semantic.conflict_type,
                        "conflict_types": list(semantic.conflict_types or []),
                        "reason": semantic.reason,
                        "existing_memory_ids": semantic.existing_memory_ids,
                        "expected_existing_versions": {
                            existing_id: int(
                                getattr(self._get_owned_fact(
                                    existing_id,
                                    user_id=memory.user_id,
                                    tenant_id=semantic.tenant_id,
                                ), "version", 1)
                                or 1
                            )
                            for existing_id in semantic.existing_memory_ids
                        },
                    },
                }
                self.write_service.upsert_memory(memory, action=MemoryDecision.REVIEW,
                                                  skip_write_gate=skip_write_gate)
                self.fact_semantics.save_decision(memory, memory.extra_payload["fact_decision_task"])
                return memory.memory_id
            if semantic.relation == "DUPLICATE" and existing is not None:
                reinforced = self._reinforce(existing, memory, add_support=False)
                self._set_fact_outcome(reinforced, "duplicate")
                self.write_service.upsert_memory(reinforced, action=MemoryDecision.REINFORCE,
                                                  skip_write_gate=skip_write_gate,
                                                  semantic_repo=self.fact_semantics.repository,
                                                  semantic_result=semantic)
                if getattr(self.write_service, "domain_writer", None) is None:
                    self.fact_semantics.commit(reinforced, semantic)
                    self.fact_semantics.bind(reinforced, semantic)
                return reinforced.memory_id
            if semantic.relation == "COEXIST":
                self._set_fact_outcome(memory, "coexist")
                self.write_service.upsert_memory(memory, action=MemoryDecision.COEXIST,
                                                  skip_write_gate=skip_write_gate,
                                                  semantic_repo=self.fact_semantics.repository,
                                                  semantic_result=semantic)
                if getattr(self.write_service, "domain_writer", None) is None:
                    self.fact_semantics.commit(memory, semantic)
                    self.fact_semantics.bind(memory, semantic)
                return memory.memory_id
            self._set_fact_outcome(memory, "new")
            self.write_service.upsert_memory(memory, action=MemoryDecision.NEW,
                                              skip_write_gate=skip_write_gate,
                                              semantic_repo=self.fact_semantics.repository,
                                              semantic_result=semantic)
            if getattr(self.write_service, "domain_writer", None) is None:
                self.fact_semantics.commit(memory, semantic)
                self.fact_semantics.bind(memory, semantic)
            return memory.memory_id

        existing = self._find_best_fact_candidate(memory)
        if existing is None:
            self._set_fact_outcome(memory, "new")
            self.write_service.upsert_memory(
                memory,
                action=MemoryDecision.NEW,
                skip_write_gate=skip_write_gate,
            )
            return memory.memory_id
        if self._same_fact(existing, memory):
            # 同 S/P/O → 只补证据，不覆盖（REINFORCE）
            reinforced = self._reinforce(existing, memory, add_support=False)
            self._set_fact_outcome(reinforced, "duplicate")
            self.write_service.upsert_memory(
                reinforced,
                action=MemoryDecision.REINFORCE,
                skip_write_gate=skip_write_gate,
            )
            return reinforced.memory_id
        if existing.single_value:
            if (existing.version or 1) >= self._MAX_FACT_CONFLICT_VERSIONS:
                # 连续单值冲突过多 → REVIEW，不再自动覆盖（防止无限版本链）
                memory.status = MemoryStatus.PENDING
                self.write_service.upsert_memory(
                    memory,
                    action=MemoryDecision.REVIEW,
                    skip_write_gate=skip_write_gate,
                )
                return memory.memory_id
            merged = self._merge_fact(existing, memory)
            self._archive_and_save_version(
                existing, merged, skip_write_gate=skip_write_gate
            )
            return merged.memory_id
        # 多值/未知 → 共存
        self._set_fact_outcome(memory, "coexist")
        self.write_service.upsert_memory(
            memory,
            action=MemoryDecision.COEXIST,
            skip_write_gate=skip_write_gate,
        )
        return memory.memory_id

    def _find_best_fact_candidate(
        self, memory: KnowledgeMemory
    ) -> KnowledgeMemory | None:
        """按 user + subject + predicate 精确匹配 active 事实性知识。"""
        subj = self._normalize(memory.subject or "")
        pred = self._normalize(memory.predicate or "")
        if not subj or not pred:
            return None
        candidates = self.know_repo.list_all(status="active", user_id=memory.user_id)
        for candidate in candidates:
            if (
                getattr(candidate.knowledge_type, "value", str(candidate.knowledge_type))
                != KnowledgeType.FACT.value
            ):
                continue
            if (
                self._normalize(candidate.subject or "") == subj
                and self._normalize(candidate.predicate or "") == pred
            ):
                return candidate
        return None

    @staticmethod
    def _same_fact(left: KnowledgeMemory, right: KnowledgeMemory) -> bool:
        return (
            KnowledgeUpdater._normalize(left.subject or "")
            == KnowledgeUpdater._normalize(right.subject or "")
            and KnowledgeUpdater._normalize(left.predicate or "")
            == KnowledgeUpdater._normalize(right.predicate or "")
            and KnowledgeUpdater._normalize(left.object_value or "")
            == KnowledgeUpdater._normalize(right.object_value or "")
        )

    def _merge_fact(
        self, existing: KnowledgeMemory, incoming: KnowledgeMemory
    ) -> KnowledgeMemory:
        merged = incoming.model_copy(deep=True)
        if not merged.memory_id or merged.memory_id == existing.memory_id:
            merged.memory_id = f"{existing.memory_id}_v{existing.version + 1}"
        merged.parent_id = existing.memory_id
        merged.evidences = self._merge_evidences(
            existing.evidences, incoming.evidences
        )
        merged.version = max(1, existing.version) + 1
        merged.status = MemoryStatus.ACTIVE
        merged.updated_at = datetime.now(timezone.utc)
        merged.confidence = self.confidence_calculator.merge_score(
            existing_confidence=existing.confidence,
            incoming_confidence=incoming.confidence,
            success_count=existing.success_count,
            total_count=existing.total_count,
            evidence_count=len(merged.evidences),
        )
        return merged

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
        self,
        existing: KnowledgeMemory,
        successor: KnowledgeMemory,
        *,
        skip_write_gate: bool = False,
    ) -> None:
        archived = existing.model_copy(deep=True)
        archived.status = MemoryStatus.ARCHIVED
        archived.updated_at = datetime.now(timezone.utc)
        self.write_service.upsert_memory(
            archived,
            action=MemoryDecision.REVISE,
            skip_write_gate=skip_write_gate,
        )
        self.write_service.upsert_memory(
            successor,
            action=MemoryDecision.REVISE,
            skip_write_gate=skip_write_gate,
        )
        if self.fact_semantics is not None and getattr(existing.knowledge_type, "value", str(existing.knowledge_type)) == KnowledgeType.FACT.value:
            self.fact_semantics.set_status(existing.memory_id, "archived")
            self.fact_semantics.bind(successor, FactSemanticResult("BOUND", **{
                "subject_id": (successor.extra_payload or {}).get("fact_semantic", {}).get("subject_id", ""),
                "predicate_id": (successor.extra_payload or {}).get("fact_semantic", {}).get("predicate_id", ""),
                "object_id": (successor.extra_payload or {}).get("fact_semantic", {}).get("object_id", ""),
            }))

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
