"""Candidate staging service: normalization, Scope, near-duplicate merge, evidence groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.domain.candidate import normalize_claim_key
from memoryhub.domain.contracts import Candidate, MemoryEventContract, MemoryScope
from memoryhub.storage.vnext_repositories import CandidateRepository, CandidateView


@dataclass(frozen=True, slots=True)
class CandidateStageResult:
    """Result of staging one reflection Candidate."""

    candidate: CandidateView
    created: bool
    merged: bool
    is_independent_evidence: bool


class CandidateService:
    """Stage Candidates with near-duplicate merge and independent evidence groups.

    The service guarantees:
    - the same event/episode does not create a second independent evidence group;
    - repeated statements in the same task do not inflate independent support;
    - Scope is never auto-promoted to GLOBAL.
    """

    def __init__(
        self,
        repository: CandidateRepository,
        *,
        default_scope_level: MemoryScope = MemoryScope.TASK,
    ) -> None:
        self.repository = repository
        self.default_scope_level = default_scope_level

    def stage(
        self,
        candidate: Candidate,
        *,
        source_event: MemoryEventContract,
        episode_id: str,
    ) -> CandidateStageResult:
        """Stage a Candidate, merging near-duplicates and grouping evidence."""

        if not isinstance(candidate, Candidate):
            raise TypeError("candidate staging requires Candidate")

        scope_level, scope = self._resolve_scope(
            candidate, source_event.payload, episode_id
        )
        normalized_key = normalize_claim_key(candidate.claim, candidate.memory_type.value)

        existing = self.repository.find_by_key(
            tenant_id=candidate.tenant_id,
            user_id=candidate.user_id,
            normalized_key=normalized_key,
        )

        if existing is not None and self._is_near_duplicate(existing, scope_level, scope):
            return self._merge(
                existing,
                candidate,
                source_event=source_event,
                episode_id=episode_id,
            )

        created = self.repository.create(
            candidate_id=candidate.candidate_id,
            tenant_id=candidate.tenant_id,
            user_id=candidate.user_id,
            memory_type=candidate.memory_type.value,
            normalized_key=normalized_key,
            claim=dict(candidate.claim),
            scope_level=scope_level.value,
            scope=scope,
            status=candidate.status.value,
            evidence_refs=[source_event.event_id],
            supporting_episode_ids=[episode_id],
            frequency=1,
        )
        return CandidateStageResult(
            candidate=created,
            created=True,
            merged=False,
            is_independent_evidence=True,
        )

    def _resolve_scope(
        self,
        candidate: Candidate,
        event_payload: dict[str, Any],
        episode_id: str,
    ) -> tuple[MemoryScope, str]:
        """Resolve scope from explicit event payload, then candidate, then default.

        Local scopes are never auto-promoted to GLOBAL.
        """

        explicit_level = event_payload.get("scope_level") or event_payload.get("scope")
        if explicit_level is not None:
            try:
                scope_level = MemoryScope(str(explicit_level).upper())
            except ValueError:
                scope_level = self.default_scope_level
            scope = event_payload.get("scope") or candidate.scope
            return scope_level, scope

        if candidate.scope_level is not None:
            return candidate.scope_level, candidate.scope

        return self.default_scope_level, f"TASK:{episode_id}"

    @staticmethod
    def _is_near_duplicate(
        existing: CandidateView,
        scope_level: MemoryScope,
        scope: str,
    ) -> bool:
        """Two candidates are near-duplicates when key and scope match."""

        return existing.scope_level == scope_level.value and existing.scope == scope

    def _merge(
        self,
        existing: CandidateView,
        candidate: Candidate,
        *,
        source_event: MemoryEventContract,
        episode_id: str,
    ) -> CandidateStageResult:
        """Merge a new Candidate into an existing near-duplicate and add evidence."""

        is_independent = not self._already_supported(
            existing, source_event.event_id, episode_id
        )

        updated = self.repository.add_evidence(
            tenant_id=existing.tenant_id,
            user_id=existing.user_id,
            candidate_id=existing.candidate_id,
            event_id=source_event.event_id,
            episode_id=episode_id,
            is_independent=is_independent,
        )

        return CandidateStageResult(
            candidate=updated,
            created=False,
            merged=True,
            is_independent_evidence=is_independent,
        )

    @staticmethod
    def _already_supported(
        existing: CandidateView, event_id: str, episode_id: str
    ) -> bool:
        """Return whether this event/episode already supports the candidate."""

        if event_id in (existing.evidence_refs or []):
            return True
        if episode_id in (existing.supporting_episode_ids or []):
            return True
        return False


__all__ = ["CandidateService", "CandidateStageResult"]
