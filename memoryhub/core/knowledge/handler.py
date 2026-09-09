"""Knowledge handler preserving KnowledgeExtractor and KnowledgeUpdater contracts."""

from __future__ import annotations

import logging
from typing import Any

from memoryhub.core.memory.base import (
    BaseMemoryHandler,
    MemoryCandidate,
    MemoryDecision,
)
from memoryhub.core.memory.confidence import ConfidenceFactors
from memoryhub.core.memory.freshness import candidate_freshness

logger = logging.getLogger(__name__)


class KnowledgeMemoryHandler(BaseMemoryHandler):
    memory_type = "knowledge"

    def __init__(self, extractor: Any, updater: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.extractor = extractor
        self.updater = updater

    def extract_candidates(
        self, source: Any, *, context: Any = None
    ) -> list[MemoryCandidate]:
        events = list(source) if isinstance(source, (list, tuple)) else [source]
        memories = self.extractor.extract_from_trajectory(events)
        event_ids = [str(getattr(e, "event_id", "")) for e in events]
        occurred_at = str(getattr(events[-1], "occurred_at", "")) if events else ""
        quality = min(
            (
                float(getattr(getattr(e, "quality", None), "score", 1.0) or 1.0)
                for e in events
            ),
            default=1.0,
        )
        return [
            MemoryCandidate(
                "knowledge",
                memory,
                memory.user_id,
                event_ids[-1] if event_ids else "",
                event_ids[-1] if event_ids else "",
                occurred_at,
                list(getattr(memory, "evidences", []) or []),
                quality,
                float(getattr(memory, "confidence", 0.5) or 0.5),
                {},
            )
            for memory in memories
        ]

    def find_similar(self, candidate: MemoryCandidate) -> Any:
        return (
            self.updater._find_equivalent(candidate.payload)
            if self.updater is not None and hasattr(self.updater, "_find_equivalent")
            else None
        )

    def classify_relation(self, candidate: MemoryCandidate, existing: Any) -> str:
        """Duplicate when the semantic content is unchanged; otherwise update."""

        def _fingerprint(memory: Any) -> tuple:
            return (
                str(getattr(memory, "name", "") or "").strip().lower(),
                str(getattr(memory, "content", "") or "").strip().lower(),
                tuple(
                    str(step).strip().lower()
                    for step in (getattr(memory, "steps", None) or [])
                ),
            )

        return "duplicate" if _fingerprint(candidate.payload) == _fingerprint(existing) else "update"

    def build_confidence_factors(
        self, candidate: MemoryCandidate, existing: Any
    ) -> ConfidenceFactors:
        quality = min(candidate.quality_score, candidate.extraction_score)
        return ConfidenceFactors(
            0.85,
            quality,
            self.confidence_calculator.support_from_evidence_count(
                len(candidate.evidences)
            ),
            self._freshness(candidate.occurred_at),
        )

    def apply(self, decision: MemoryDecision) -> Any:
        if self.updater is None or decision.candidate is None:
            return None
        action = str(getattr(decision, "action", "")).lower()
        if action in {"reject", "review"}:
            # 候选被丢弃必须可见：warning 日志 + 挂到 decision.reason 供调用方汇总
            logger.warning(
                "knowledge apply: dropped candidate action=%s memory_id=%s reason=%s",
                action,
                getattr(decision.candidate.payload, "memory_id", "?"),
                getattr(decision, "reason", ""),
            )
            return None
        memory = decision.candidate.payload
        memory.evidences = decision.candidate.evidences
        memory.confidence = decision.confidence
        # Extraction-derived write: the source event already passed the
        # event-level safety gate, so skip the redundant memory-level re-gate
        # (I-14 double-gate fix).
        result = self.updater.add(memory, skip_write_gate=True)
        logger.info(
            "knowledge apply: action=%s memory=%s -> %s",
            action,
            getattr(memory, "memory_id", "?"),
            result,
        )
        return result

    def _freshness(self, value: str) -> float:
        return candidate_freshness(value, memory_type=self.memory_type)
