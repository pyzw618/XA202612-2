"""Fact handler that reuses the public FactMemoryPipeline API."""

from __future__ import annotations

from typing import Any

from memoryhub.core.memory.base import (
    BaseMemoryHandler,
    MemoryCandidate,
    MemoryDecision,
)
from memoryhub.core.memory.confidence import ConfidenceFactors
from memoryhub.core.memory.freshness import candidate_freshness


class FactMemoryHandler(BaseMemoryHandler):
    memory_type = "fact"

    def __init__(self, pipeline: Any, *, adapter: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pipeline = pipeline
        self.adapter = adapter

    def extract_candidates(
        self, source: Any, *, context: Any = None
    ) -> list[MemoryCandidate]:
        if self.adapter is not None:
            proposals = self.adapter.propose_from_event(source)
            event_id = str(getattr(source, "event_id", ""))
            occurred_at = str(getattr(source, "occurred_at", ""))
            quality = float(
                getattr(getattr(source, "quality", None), "score", 1.0) or 1.0
            )
        else:
            text = str(source)
            proposals = self.pipeline.propose(text)
            event_id = occurred_at = ""
            quality = 1.0
        result = []
        for proposal in proposals:
            metadata = dict(getattr(proposal, "metadata", {}) or {})
            evidence = {
                "event_id": event_id,
                "evidence_id": proposal.proposal_id,
                "content": proposal.raw_triple.evidence,
                "source_id": proposal.source_id,
                "source_type": metadata.get("content_source", "event_text"),
                "timestamp": occurred_at,
                "quality": quality,
            }
            result.append(
                MemoryCandidate(
                    "fact",
                    proposal,
                    str(
                        metadata.get("user_id", getattr(source, "user_id", "default"))
                        or "default"
                    ),
                    proposal.source_id,
                    event_id,
                    occurred_at,
                    [evidence],
                    quality,
                    float(proposal.raw_triple.confidence),
                    metadata,
                )
            )
        return result

    def find_similar(self, candidate: MemoryCandidate) -> Any:
        # The pipeline owns authoritative conflict matching during commit.
        return None

    def build_confidence_factors(
        self, candidate: MemoryCandidate, existing: Any
    ) -> ConfidenceFactors:
        source = (
            0.85 if candidate.metadata.get("content_source") == "tool_result" else 0.95
        )
        if candidate.metadata.get("tool_status") == "partial":
            source = min(source, 0.60)
        quality = min(candidate.quality_score, candidate.extraction_score)
        return ConfidenceFactors(
            source,
            quality,
            self.confidence_calculator.support_from_evidence_count(
                len(candidate.evidences)
            ),
            self._freshness(candidate.occurred_at),
        )

    def apply(self, decision: MemoryDecision) -> Any:
        if decision.action in {"reject", "review"} or decision.candidate is None:
            return None
        candidate = decision.candidate
        proposal = candidate.payload
        proposal.raw_triple.confidence = decision.confidence
        scope = "project" if proposal.project_id_hint else "global"
        return self.pipeline.commit(
            proposal,
            scope=scope,
            project_id=proposal.project_id_hint,
            user_id=candidate.user_id,
        )

    def _freshness(self, occurred_at: str) -> float:
        return candidate_freshness(occurred_at, memory_type=self.memory_type)
