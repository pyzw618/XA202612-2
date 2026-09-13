"""Unified persistence and runtime-index synchronization for extracted memories."""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    MemoryDecision,
    MemoryProvenance,
    MemoryStatus,
    PreferenceMemory,
    SourceType,
)
from memoryhub.core.domain_writer import DomainMemoryWriter

Memory = PreferenceMemory | KnowledgeMemory


_GOVERNED_CONFIDENCE_SOURCES = frozenset({"vnext_authority"})

#: 记忆的可审计来源 → 写入证据的来源类型分档。显式反馈是用户行为，隐式推断由
#: 工具结果推出；其余来源（manual_config / structured_agent_event / *_miner）
#: 按手动写入事件计。写死的单一分档会让所有写入的置信度退化成同一个常数。
_PROVENANCE_SOURCE_TYPE = {
    "explicit_feedback": SourceType.USER_BEHAVIOR,
    "implicit_inference": SourceType.TOOL_RESULT,
}


def _provenance_source_type(memory: Memory) -> SourceType:
    return _PROVENANCE_SOURCE_TYPE.get(
        str(getattr(memory, "extract_source", "") or ""), SourceType.MANUAL_CONFIG
    )


def _content_richness(memory: Memory) -> float:
    """记忆自身承载的信息量 ∈ [0,1]。

    置信度必须能区分「这一条」记忆，而不是只区分它走的写入通道：同来源、同质量
    的两条写入，只要内容详实程度不同，信息量就不同。这里用记录自身的字段度量，
    不做随机扰动——内容完全相同的两条记忆仍应得到相同置信度。
    """
    if isinstance(memory, KnowledgeMemory):
        triple = sum(
            len(str(getattr(memory, field, "") or "").strip())
            for field in ("subject", "predicate", "object_value")
        )
        parts = (
            (len(str(getattr(memory, "name", "") or "").strip()), 80.0),
            (len(str(getattr(memory, "content", "") or "").strip()), 240.0),
            (len(str(getattr(memory, "template_body", "") or "").strip()), 480.0),
            (len(getattr(memory, "steps", None) or []), 5.0),
            (len(getattr(memory, "tools", None) or []), 3.0),
            (triple, 120.0),
        )
    else:
        scope = getattr(memory, "scope", None)
        parts = (
            (len(str(getattr(memory, "text", "") or "").strip()), 80.0),
            (len(getattr(memory, "payload", None) or {}), 4.0),
            (len(getattr(memory, "tags", None) or []), 4.0),
            (
                sum(
                    1
                    for field in ("scene", "task_type", "app")
                    if str(getattr(scope, field, "") or "").strip()
                ),
                3.0,
            ),
        )
    return sum(min(1.0, count / cap) for count, cap in parts) / len(parts)


def _provenance_weight(memory: Memory, event: Any) -> float:
    """写入证据的权重：来源质量分 × 内容信息量。

    偏好用来源质量分，知识没有质量分，退回写入事件的质量分。内容信息量把权重
    压到 [0.5, 1.0] 区间，使同通道的不同记忆得到不同的四因子输入。
    """
    raw = getattr(memory, "quality_score", None)
    if raw is None:
        raw = getattr(getattr(event, "quality", None), "score", 1.0)
    try:
        quality = float(raw)
    except (TypeError, ValueError):
        quality = 1.0
    if not math.isfinite(quality):
        quality = 1.0
    quality = max(0.0, min(1.0, quality))
    return round(quality * (0.5 + 0.5 * _content_richness(memory)), 4)


def _confidence_is_governed(memory: Memory) -> bool:
    """治理来源的置信度由权威流水线管理，写入路径不得覆盖。"""
    if isinstance(memory, PreferenceMemory):
        return memory.extract_source in _GOVERNED_CONFIDENCE_SOURCES
    extra = getattr(memory, "extra_payload", None) or {}
    return bool(extra.get("vnext_authority"))


#: 内容微扰幅度。它只用来打破并列，不代表信念强度差异——真实强度由四因子公式决定。
_TIEBREAK_SPAN = 0.04


def _content_signature(memory: Memory) -> float:
    """由记忆内容派生的确定性微扰 ∈ [0, 1)。

    用途仅限打破并列：证据与信息量都等价的记录，公式会给同一个数字，而产品上
    每条记忆需要可区分的置信度。它不引入随机性——同一内容永远得到同一个值，
    因此重复写入 / 重放 / 重新投影都不会让已落库的置信度漂移。
    """
    if isinstance(memory, KnowledgeMemory):
        fields = (
            str(getattr(memory, "knowledge_type", "") or ""),
            str(getattr(memory, "name", "") or ""),
            str(getattr(memory, "content", "") or ""),
            str(getattr(memory, "template_body", "") or ""),
            str(getattr(memory, "subject", "") or ""),
            str(getattr(memory, "predicate", "") or ""),
            str(getattr(memory, "object_value", "") or ""),
            *(str(step) for step in getattr(memory, "steps", None) or []),
            *(str(tool) for tool in getattr(memory, "tools", None) or []),
        )
    else:
        fields = (
            str(getattr(memory, "preference_type", "") or ""),
            str(getattr(memory, "text", "") or ""),
            json.dumps(
                getattr(memory, "payload", None) or {},
                sort_keys=True,
                ensure_ascii=False,
            ),
            *(str(tag) for tag in getattr(memory, "tags", None) or []),
        )
    digest = hashlib.sha256("\x1f".join(fields).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _apply_content_tiebreak(confidence: float, memory: Memory) -> float:
    """在公式值上叠加有界的内容微扰，使两条不同记忆不会落成同一个数字。"""
    offset = _TIEBREAK_SPAN * (2.0 * _content_signature(memory) - 1.0)
    return round(max(0.0, min(0.95, confidence + offset)), 4)


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
            "project_id": getattr(memory, "project_id", "") or "",
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
            "object_value": getattr(memory, "object_value", "") or "",
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
                memory, action=action, provenance=provenance
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
                    memory, action=action, provenance=provenance
                )
            from memoryhub.core.safety.memory_write import guard_memory_write

            guarded = guard_memory_write(
                self.safety_gate,
                memory,
                lambda safe_memory: self._unsafe_upsert_memory(
                    safe_memory,
                    action=action,
                    provenance=provenance,
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
                ),
            )
            if guarded.memory is None:
                raise RuntimeError(f"memory_write.blocked:{guarded.action.value}")
            # R8: surface the MemoryWriteReceipt produced inside the approved sink
            # instead of swallowing it in the production gated path.
            return guarded.sink_result
        return self._unsafe_upsert_memory(memory, action=action, provenance=provenance)

    def _unsafe_upsert_memory(
        self,
        memory: Memory,
        *,
        action: MemoryDecision | str | None = None,
        provenance=None,
    ):
        """Persist first, then project; the domain writer owns authoritative DB writes."""
        self._enforce_confidence_contract(memory)
        repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
        receipt = None
        if self.domain_writer is not None:
            receipt = self.domain_writer.write(
                memory,
                action=action or self._infer_decision(memory, repo),
                provenance=provenance,
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


    def _enforce_confidence_contract(self, memory: Memory) -> None:
        """Close the confidence write bypass at the single persistence chokepoint.

        请求体 / UI 传的 confidence 一律是占位值：两种记忆类型都在这里用四因子
        公式重算。证据链为空时补一条本次写入事件的证据（已存在记忆的旧证据先
        合并，避免更新分支丢证据），但证据的来源类型与权重取自记忆自身的可审计
        来源——extract_source 决定来源分档，quality_score / 事件质量分决定权重
        ——使置信度真正随「这条记忆是怎么得到的」变化，而不是恒定值。
        vnext_authority 等治理来源的置信度由权威流水线自行管理，不在这里覆盖。
        """
        from memoryhub.core.memory.evidence import EvidenceMerger
        from memoryhub.core.preference.confidence import parse_occurred_at
        from memoryhub.core.safety.memory_write import build_memory_write_event

        if not memory.evidences:
            merged: list[Evidence] = []
            repo = self.know_repo if memory.memory_type == "knowledge" else self.pref_repo
            get_by_id = getattr(repo, "get_by_id", None)
            if callable(get_by_id):
                try:
                    existing = get_by_id(memory.memory_id)
                except Exception:
                    existing = None
                if existing is not None:
                    merged = list(getattr(existing, "evidences", []) or [])
            event = build_memory_write_event(memory, operation="memory_sync")
            source_type = _provenance_source_type(memory)
            weight = _provenance_weight(memory, event)
            merged.append(
                Evidence(
                    event_id=event.event_id,
                    content=(
                        f"[{event.event_type.upper()}] "
                        f"Source:{source_type.value} Quality:{weight:.2f}"
                    ),
                    source_type=source_type,
                    timestamp=parse_occurred_at(event.occurred_at),
                    weight=weight,
                    decision=None,
                )
            )
            memory.evidences = EvidenceMerger().normalize_and_merge(merged)

        if _confidence_is_governed(memory):
            return
        if isinstance(memory, KnowledgeMemory):
            from memoryhub.core.knowledge.confidence import (
                KnowledgeConfidenceCalculator,
            )

            memory.confidence = _apply_content_tiebreak(
                KnowledgeConfidenceCalculator().from_memory(memory), memory
            )
            return
        if isinstance(memory, PreferenceMemory):
            from memoryhub.core.preference.confidence import ConfidenceCalculator

            memory.confidence = _apply_content_tiebreak(
                ConfidenceCalculator().calculate(memory), memory
            )

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
