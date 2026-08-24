"""Candidate staging rules and explicit retrieval isolation."""

from __future__ import annotations

from typing import Any

from memoryhub.domain.contracts import CandidateStatus

ALLOWED_CANDIDATE_TRANSITIONS: dict[str, frozenset[str]] = {
    CandidateStatus.ACCUMULATING.value: frozenset(
        {
            CandidateStatus.ACCUMULATING.value,
            CandidateStatus.CONFIRMED.value,
            CandidateStatus.REJECTED.value,
            CandidateStatus.REVIEW.value,
        }
    ),
    CandidateStatus.REVIEW.value: frozenset(
        {
            CandidateStatus.REVIEW.value,
            CandidateStatus.CONFIRMED.value,
            CandidateStatus.REJECTED.value,
        }
    ),
    CandidateStatus.CONFIRMED.value: frozenset({CandidateStatus.CONFIRMED.value}),
    CandidateStatus.REJECTED.value: frozenset({CandidateStatus.REJECTED.value}),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_CANDIDATE_TRANSITIONS.get(current, frozenset())


def validate_transition(current: str, target: str) -> None:
    if not can_transition(current, target):
        raise ValueError(f"candidate transition {current}->{target} is not allowed")


def is_candidate_retrievable(*, include_candidates: bool = False) -> bool:
    """Normal retrieval is false; review/promotion must opt in explicitly."""

    return bool(include_candidates)


_STOP_WORDS: frozenset[str] = frozenset(
    ["the", "a", "an", "is", "are", "was", "were", "be", "been", "being"]
)


def normalize_claim_key(claim: dict[str, Any], memory_type: str) -> str:
    """Create a stable, scope-agnostic key from a candidate claim.

    The key is used for near-duplicate detection and evidence grouping.
    Scope is intentionally excluded here; callers compare scope separately.
    """

    text_parts: list[str] = []
    for key in sorted(claim):
        value = claim[key]
        if isinstance(value, str):
            text_parts.append(f"{key}:{value}")
        elif isinstance(value, (list, tuple)):
            text_parts.append(f"{key}:{','.join(str(item) for item in value)}")
        else:
            text_parts.append(f"{key}:{value}")

    raw = " ".join(text_parts).lower()
    normalized = " ".join(
        word.strip(".,!?;:'\"")
        for word in raw.split()
        if word.strip(".,!?;:'\"") and word not in _STOP_WORDS
    )
    return f"{memory_type.lower()}:{normalized}"


def independent_evidence_group_key(
    *, event_id: str, episode_id: str, source_hash: str = ""
) -> str:
    """A key representing one independent evidence group.

    Same event or same episode does not create multiple independent groups.
    Source hash is included so that genuinely different excerpts from the same
    event are still grouped together.
    """

    return f"{event_id}:{episode_id}:{source_hash}"


__all__ = [
    "ALLOWED_CANDIDATE_TRANSITIONS",
    "can_transition",
    "independent_evidence_group_key",
    "is_candidate_retrievable",
    "normalize_claim_key",
    "validate_transition",
]
