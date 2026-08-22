"""Candidate staging rules and explicit retrieval isolation."""

from __future__ import annotations

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


__all__ = [
    "ALLOWED_CANDIDATE_TRANSITIONS",
    "can_transition",
    "is_candidate_retrievable",
    "validate_transition",
]
