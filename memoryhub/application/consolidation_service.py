"""Candidate consolidation: promotion scoring, thresholds, reason codes and Fast Path.

The service decides whether a staged Candidate is ready to become a Long-Term
memory.  It is intentionally conservative: one implicit behavior cannot be
promoted to GLOBAL, and sensitive/ambiguous/conflicting content is never
fast-tracked.
"""

from __future__ import annotations

from dataclasses import dataclass

from memoryhub.domain.contracts import (
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.vnext_repositories import CandidateView


class ConsolidationError(ValueError):
    """A consolidation decision cannot be produced from invalid input."""


class PromotionDecision(str):
    """Consolidation outcome for a candidate."""

    PROMOTE = "PROMOTE"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


PROMOTION_REASONS: dict[str, str] = {
    "HIGH_CONFIDENCE": "confidence exceeds the promotion threshold",
    "MULTI_EPISODE_EVIDENCE": "multiple independent episodes support the claim",
    "STABLE_PREFERENCE": "preference is stable across episodes",
    "REPEATED_SEMANTIC_FACT": "semantic fact is independently corroborated",
    "FAST_PATH_EXPLICIT": "user explicitly requested long-term storage",
    "FAST_PATH_HIGH_TRUST_TOOL": "high-trust tool result with clear scope",
}

REVIEW_REASONS: dict[str, str] = {
    "SCORE_IN_REVIEW_BAND": "score is in the review/decision band",
    "LOW_CONFIDENCE": "confidence is below the type-specific promotion threshold",
    "LOW_UTILITY": "utility is too low for a long-term memory",
    "LOW_STABILITY": "stability is too low for a long-term memory",
    "INSUFFICIENT_EVIDENCE": "not enough independent evidence to promote",
    "AMBIGUOUS_SCOPE": "scope is ambiguous or session-local",
    "CONFLICTING_MEMORY": "an active memory with the same key/scope exists",
    "SENSITIVE_CONTENT": "content is flagged for review",
}

REJECT_REASONS: dict[str, str] = {
    "SCORE_BELOW_REVIEW_THRESHOLD": "score is below the review threshold",
    "UNSTABLE": "stability is critically low",
    "ZERO_UTILITY": "utility is effectively zero",
    "REJECTED_BY_POLICY": "candidate was rejected or dropped by policy",
    "FAST_PATH_BLOCKED": "fast path criteria were not satisfied",
}


@dataclass(frozen=True, slots=True)
class TypeWeights:
    """Weights for the promotion score of one memory type."""

    confidence: float
    utility: float
    stability: float
    frequency: float
    max_frequency: int
    promote_threshold: float
    review_threshold: float
    fast_path_min_frequency: int


_DEFAULT_WEIGHTS: dict[MemoryType, TypeWeights] = {
    MemoryType.PREFERENCE: TypeWeights(
        confidence=0.25,
        utility=0.25,
        stability=0.15,
        frequency=0.35,
        max_frequency=2,
        promote_threshold=0.70,
        review_threshold=0.40,
        fast_path_min_frequency=1,
    ),
    MemoryType.SEMANTIC: TypeWeights(
        confidence=0.35,
        utility=0.15,
        stability=0.20,
        frequency=0.30,
        max_frequency=3,
        promote_threshold=0.72,
        review_threshold=0.40,
        fast_path_min_frequency=2,
    ),
    MemoryType.PROCEDURAL: TypeWeights(
        confidence=0.25,
        utility=0.20,
        stability=0.25,
        frequency=0.30,
        max_frequency=3,
        promote_threshold=0.78,
        review_threshold=0.50,
        fast_path_min_frequency=2,
    ),
    MemoryType.EPISODIC: TypeWeights(
        confidence=0.20,
        utility=0.15,
        stability=0.15,
        frequency=0.50,
        max_frequency=3,
        promote_threshold=0.68,
        review_threshold=0.38,
        fast_path_min_frequency=2,
    ),
}


@dataclass(frozen=True, slots=True)
class ConsolidationContext:
    """Runtime context for a consolidation decision."""

    source_event: MemoryEventContract | None = None
    explicit_long_term: bool = False
    sensitivity_level: str = "NONE"
    tool_trust: str = "medium"


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    """Promotion decision with explainable reason codes."""

    candidate_id: str
    decision: str
    score: float
    reasons: list[str]
    fast_path: bool
    envelope: LongTermEnvelope | None

    @property
    def is_promoted(self) -> bool:
        return self.decision == PromotionDecision.PROMOTE


class ConsolidationService:
    """Score candidates, apply type-specific thresholds, and enforce Fast Path."""

    def __init__(
        self,
        authority_facade: LongTermAuthorityFacade | None = None,
        *,
        weights: dict[MemoryType, TypeWeights] | None = None,
        max_frequency_normalizer: int = 5,
    ) -> None:
        self.authority_facade = authority_facade
        self.weights = weights or _DEFAULT_WEIGHTS
        self.max_frequency_normalizer = max_frequency_normalizer

    def consolidate(
        self,
        candidate: CandidateView,
        *,
        memory_id: str,
        context: ConsolidationContext | None = None,
        existing_memory: LongTermEnvelope | None = None,
    ) -> ConsolidationResult:
        """Return a scored, explainable consolidation decision for one candidate."""

        if not isinstance(candidate, CandidateView):
            raise ConsolidationError("consolidation requires a CandidateView")

        ctx = context or ConsolidationContext()
        memory_type = self._parse_memory_type(candidate.memory_type)
        weights = self.weights[memory_type]

        score = self._score(candidate, weights)

        reasons: list[str] = []

        # Base decision using thresholds
        if score >= weights.promote_threshold:
            decision = PromotionDecision.PROMOTE
        elif score >= weights.review_threshold:
            decision = PromotionDecision.REVIEW
        else:
            decision = PromotionDecision.REJECT

        # Append reason codes based on the decision
        reasons.extend(self._score_reasons(candidate, score, weights, decision))

        # Fast path is only evaluated when the base decision is PROMOTE
        fast_path = False
        envelope: LongTermEnvelope | None = None

        if decision == PromotionDecision.PROMOTE:
            fast_path = self._fast_path_eligible(
                candidate, memory_type, ctx, existing_memory, weights
            )
            if fast_path:
                reason = (
                    "FAST_PATH_EXPLICIT"
                    if ctx.explicit_long_term
                    else "FAST_PATH_HIGH_TRUST_TOOL"
                )
                reasons.append(reason)
            envelope = self._build_envelope(candidate, memory_id, memory_type)

        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            decision=decision,
            score=round(score, 4),
            reasons=reasons,
            fast_path=fast_path,
            envelope=envelope,
        )

    @staticmethod
    def _parse_memory_type(value: str) -> MemoryType:
        try:
            return MemoryType(value.upper())
        except ValueError as exc:
            raise ConsolidationError(f"unsupported memory type: {value}") from exc

    def _score(self, candidate: CandidateView, weights: TypeWeights) -> float:
        """Weighted combination of confidence, utility, stability and frequency."""

        freq = min(
            max(candidate.frequency, 0) / weights.max_frequency,
            1.0,
        )
        return (
            weights.confidence * candidate.confidence
            + weights.utility * candidate.utility
            + weights.stability * candidate.stability
            + weights.frequency * freq
        )

    def _score_reasons(
        self,
        candidate: CandidateView,
        score: float,
        weights: TypeWeights,
        decision: str,
    ) -> list[str]:
        reasons: list[str] = []

        if decision == PromotionDecision.REJECT:
            reasons.append("SCORE_BELOW_REVIEW_THRESHOLD")
            if candidate.stability < 0.3:
                reasons.append("UNSTABLE")
            if candidate.utility < 0.2:
                reasons.append("ZERO_UTILITY")
        elif decision == PromotionDecision.REVIEW:
            reasons.append("SCORE_IN_REVIEW_BAND")
            if candidate.confidence < weights.promote_threshold:
                reasons.append("LOW_CONFIDENCE")
            if candidate.utility < weights.promote_threshold:
                reasons.append("LOW_UTILITY")
            if candidate.stability < weights.promote_threshold:
                reasons.append("LOW_STABILITY")
            if candidate.frequency < 2:
                reasons.append("INSUFFICIENT_EVIDENCE")
        else:  # PROMOTE
            if candidate.confidence >= 0.85:
                reasons.append("HIGH_CONFIDENCE")
            if candidate.frequency >= 2:
                reasons.append("MULTI_EPISODE_EVIDENCE")
            if candidate.memory_type == MemoryType.PREFERENCE.value and candidate.stability >= 0.6:
                reasons.append("STABLE_PREFERENCE")
            if candidate.memory_type == MemoryType.SEMANTIC.value and candidate.frequency >= 2:
                reasons.append("REPEATED_SEMANTIC_FACT")

        return reasons

    def _fast_path_eligible(
        self,
        candidate: CandidateView,
        memory_type: MemoryType,
        context: ConsolidationContext,
        existing_memory: LongTermEnvelope | None,
        weights: TypeWeights,
    ) -> bool:
        """Fast path is only for explicit, high-confidence, non-risky content."""

        # Only PREFERENCE and SEMANTIC may be fast-tracked.
        if memory_type not in {MemoryType.PREFERENCE, MemoryType.SEMANTIC}:
            return False

        # Strict confidence and evidence floors.
        if candidate.confidence < 0.9:
            return False
        if candidate.frequency < weights.fast_path_min_frequency:
            return False

        # Source must be explicit user instruction or high-trust tool fact.
        source_ok = self._explicit_source(context)
        if not source_ok:
            return False

        # Sensitive or review-flagged content never uses Fast Path.
        if context.sensitivity_level.upper() in {"HIGH", "REVIEW", "MASK", "DROP"}:
            return False

        # Ambiguous or session-local scope is not allowed.
        if candidate.scope_level == MemoryScope.SESSION.value or not candidate.scope:
            return False
        if candidate.scope_level.upper() not in {
            MemoryScope.TASK.value,
            MemoryScope.PROJECT.value,
            MemoryScope.APPLICATION.value,
            MemoryScope.DOMAIN.value,
            MemoryScope.GLOBAL.value,
        }:
            return False

        # Conflicting active memory blocks Fast Path (REVIEW instead).
        if (
            existing_memory is not None
            and existing_memory.evolution_status is EvolutionStatus.ACTIVE
        ):
            return False

        # If we have an authority facade, check the chain for active conflicts.
        if self.authority_facade is not None and existing_memory is None:
            siblings = self.authority_facade.repository.list(
                tenant_id=candidate.tenant_id,
                user_id=candidate.user_id,
                include_inactive=False,
            )
            key = (
                candidate.tenant_id,
                candidate.user_id,
                memory_type.value,
                candidate.normalized_key,
                f"{candidate.scope_level}:{candidate.scope}",
            )
            for sibling in siblings:
                if (
                    sibling.evolution_status is EvolutionStatus.ACTIVE
                    and LongTermAuthorityFacade.chain_key(sibling) == key
                ):
                    return False

        return True

    @staticmethod
    def _explicit_source(context: ConsolidationContext) -> bool:
        if context.explicit_long_term:
            return True
        event = context.source_event
        if event is None:
            return False
        if event.source_type.upper() in {"MANUAL_CONFIG", "TOOL_RESULT", "USER_BEHAVIOR"}:
            return True
        payload = event.payload or {}
        if payload.get("explicit_long_term") is True:
            return True
        if event.source_type.upper() == "TOOL_RESULT" and context.tool_trust.lower() == "high":
            return True
        return False

    @staticmethod
    def _build_envelope(
        candidate: CandidateView,
        memory_id: str,
        memory_type: MemoryType,
    ) -> LongTermEnvelope:
        """Materialize a promoted candidate into a Long-Term envelope."""

        scope_level = MemoryScope(candidate.scope_level.upper())
        content = dict(candidate.claim)
        if memory_type is MemoryType.SEMANTIC and not all(
            str(content.get(key, "")).strip()
            for key in ("subject", "predicate", "object_value")
        ):
            from memoryhub.core.knowledge.extractor import parse_explicit_fact_statement

            triple = parse_explicit_fact_statement(str(content.get("statement", "")))
            if triple is not None:
                content.update(
                    subject=triple[0], predicate=triple[1], object_value=triple[2]
                )
        return LongTermEnvelope(
            tenant_id=candidate.tenant_id,
            user_id=candidate.user_id,
            memory_id=memory_id,
            memory_type=memory_type,
            normalized_key=candidate.normalized_key,
            content=content,
            scope_level=scope_level,
            scope=candidate.scope,
            evolution_status=EvolutionStatus.ACTIVE,
            confidence=candidate.confidence,
            utility=candidate.utility,
            evidence_refs=list(candidate.evidence_refs),
            candidate_id=candidate.candidate_id,
        )


__all__ = [
    "ConsolidationContext",
    "ConsolidationError",
    "ConsolidationResult",
    "ConsolidationService",
    "PromotionDecision",
    "PROMOTION_REASONS",
    "REJECT_REASONS",
    "REVIEW_REASONS",
    "TypeWeights",
]
