"""Shared memory processing template without changing public schemas."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from .confidence import ConfidenceFactors, UnifiedConfidenceCalculator
from .evidence import EvidenceMerger

MemoryType = Literal["fact", "preference", "knowledge"]
MemoryAction = Literal["new", "update", "coexist", "duplicate", "review", "reject"]


@dataclass(slots=True)
class MemoryCandidate:
    memory_type: MemoryType
    payload: Any
    user_id: str
    source_id: str = ""
    event_id: str = ""
    occurred_at: str = ""
    evidences: list[Any] = field(default_factory=list)
    quality_score: float = 1.0
    extraction_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryDecision:
    action: MemoryAction
    reason: str
    confidence: float
    existing_id: str = ""
    candidate: MemoryCandidate | None = None


class BaseMemoryHandler(ABC):
    """Consistent ``extract -> merge -> score -> decide -> apply`` orchestration."""

    memory_type: MemoryType

    def __init__(
        self,
        *,
        evidence_merger: EvidenceMerger | None = None,
        confidence_calculator: UnifiedConfidenceCalculator | None = None,
    ) -> None:
        self.evidence_merger = evidence_merger or EvidenceMerger()
        self.confidence_calculator = (
            confidence_calculator or UnifiedConfidenceCalculator()
        )

    def process(self, source: Any, *, context: Any = None) -> list[MemoryDecision]:
        decisions: list[MemoryDecision] = []
        for candidate in self.extract_candidates(source, context=context):
            candidate.evidences = self.evidence_merger.normalize_and_merge(
                candidate.evidences
            )
            existing = self.find_similar(candidate)
            factors = self.build_confidence_factors(candidate, existing)
            confidence = self.confidence_calculator.calculate(
                factors, memory_type=candidate.memory_type
            )
            decision = self.decide(candidate, existing, confidence)
            decision.candidate = candidate
            decision.confidence = confidence
            decisions.append(decision)
        return decisions

    def process_and_apply(
        self, source: Any, *, context: Any = None
    ) -> list[MemoryDecision]:
        decisions = self.process(source, context=context)
        for decision in decisions:
            self.apply(decision)
        return decisions

    def decide(
        self, candidate: MemoryCandidate, existing: Any, confidence: float
    ) -> MemoryDecision:
        if confidence < self.confidence_calculator.reject_threshold:
            return MemoryDecision(
                "reject", "confidence below write threshold", confidence
            )
        if confidence < self.confidence_calculator.review_threshold:
            return MemoryDecision(
                "review", "confidence requires confirmation", confidence
            )
        if existing is None:
            return MemoryDecision("new", "no similar memory found", confidence)
        return self.decide_existing(candidate, existing, confidence)

    def decide_existing(
        self, candidate: MemoryCandidate, existing: Any, confidence: float
    ) -> MemoryDecision:
        existing_id = str(
            getattr(existing, "memory_id", getattr(existing, "fact_id", ""))
        )
        return MemoryDecision("update", "similar memory found", confidence, existing_id)

    @abstractmethod
    def extract_candidates(
        self, source: Any, *, context: Any = None
    ) -> list[MemoryCandidate]: ...

    @abstractmethod
    def find_similar(self, candidate: MemoryCandidate) -> Any: ...

    @abstractmethod
    def build_confidence_factors(
        self, candidate: MemoryCandidate, existing: Any
    ) -> ConfidenceFactors: ...

    @abstractmethod
    def apply(self, decision: MemoryDecision) -> Any: ...
