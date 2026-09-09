"""Authority validation and scope-aware conflict resolution.

This module is the trust boundary between raw recall candidates and the
context that is actually shown to the agent.  It must guarantee:

* DELETED/SUPERSEDED memories do not leak into context.
* Stale projection versions are detected and rejected when Authority-checked.
* Scope conflicts are resolved with the precedence
  TASK > PROJECT > APPLICATION > DOMAIN > GLOBAL.
* Every dropped candidate carries an explicit, auditable reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from memoryhub.adapter.vnext_schemas import RetrievedMemory
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    MemoryScope,
)
from memoryhub.storage.authority_repository import AuthorityRepository


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Result of validating a single candidate against Authority."""

    memory: RetrievedMemory
    valid: bool
    reason: str = ""
    authority_version: int | None = None
    authority_status: str | None = None


@dataclass(frozen=True, slots=True)
class ConflictGroup:
    """A set of memories that share the same identity key and compete."""

    identity_key: str
    memories: list[RetrievedMemory] = field(default_factory=list)
    selected: RetrievedMemory | None = None
    dropped: list[RetrievedMemory] = field(default_factory=list)
    resolution: str = ""


@dataclass(frozen=True, slots=True)
class ScopeResolution:
    """Outputs of the scope resolver pass."""

    selected: list[RetrievedMemory] = field(default_factory=list)
    conflict_groups: list[ConflictGroup] = field(default_factory=list)
    dropped: list[tuple[RetrievedMemory, str]] = field(default_factory=list)
    invalid: list[ValidationResult] = field(default_factory=list)
    authority_checked: bool = False


class ScopeResolver:
    """Filter and resolve candidates using Authority truth and scope rules."""

    # Narrower scope wins.  Lower ordinal = higher priority.
    SCOPE_PRECEDENCE: tuple[MemoryScope, ...] = (
        MemoryScope.TASK,
        MemoryScope.PROJECT,
        MemoryScope.APPLICATION,
        MemoryScope.DOMAIN,
        MemoryScope.GLOBAL,
        # SESSION is not a long-term scope; treat it as project-adjacent.
        MemoryScope.SESSION,
    )

    # Statuses that must never appear in context.
    BLOCKED_STATUSES: frozenset[str] = frozenset(
        {EvolutionStatus.DELETED.value, EvolutionStatus.SUPERSEDED.value}
    )

    def __init__(
        self,
        authority_repository: AuthorityRepository | None = None,
        *,
        authority_checked: bool = False,
        repair_callback: Callable[[RetrievedMemory], None] | None = None,
    ) -> None:
        self.authority_repository = authority_repository
        self.authority_checked = authority_checked
        self.repair_callback = repair_callback

    def resolve(
        self,
        candidates: list[RetrievedMemory],
        *,
        tenant_id: str = "",
        user_id: str = "",
        preferred_scope_level: MemoryScope | None = None,
        preferred_scope: str = "",
    ) -> ScopeResolution:
        """Run the full validation + conflict resolution pipeline."""
        validated = self._validate_candidates(candidates)
        eligible, scope_dropped = self._filter_request_scope(
            validated,
            tenant_id=tenant_id,
            user_id=user_id,
            preferred_scope_level=preferred_scope_level,
            preferred_scope=preferred_scope,
        )
        valid_memories = [r.memory for r in eligible if r.valid]
        invalid = [r for r in eligible if not r.valid]

        selected, groups, conflict_dropped = self._resolve_conflicts(
            valid_memories,
            preferred_scope_level=preferred_scope_level,
            preferred_scope=preferred_scope,
        )

        return ScopeResolution(
            selected=selected,
            conflict_groups=groups,
            dropped=[*scope_dropped, *conflict_dropped],
            invalid=invalid,
            authority_checked=self.authority_checked,
        )

    @staticmethod
    def _filter_request_scope(
        results: list[ValidationResult],
        *,
        tenant_id: str,
        user_id: str,
        preferred_scope_level: MemoryScope | None,
        preferred_scope: str,
    ) -> tuple[list[ValidationResult], list[tuple[RetrievedMemory, str]]]:
        """Apply request ownership/scope eligibility before conflict grouping.

        Working and Episode candidates are already structurally narrowed by
        their repositories.  Long-term candidates may use GLOBAL as a safe
        fallback; every other scoped record must exactly match the request.
        """
        preferred_scope_value = preferred_scope.split(":", 1)[-1]
        eligible: list[ValidationResult] = []
        dropped: list[tuple[RetrievedMemory, str]] = []
        for result in results:
            memory = result.memory
            reason = ""
            if tenant_id and memory.tenant_id != tenant_id:
                reason = "tenant does not match request"
            elif user_id and memory.user_id != user_id:
                reason = "user does not match request"
            elif (
                memory.layer is LifecycleLayer.LONG_TERM
                and preferred_scope_level is not None
                and preferred_scope
                and memory.scope_level is not MemoryScope.GLOBAL
                and (
                    memory.scope_level is not preferred_scope_level
                    or memory.scope.split(":", 1)[-1] != preferred_scope_value
                )
            ):
                reason = "scope does not match request"
            if reason:
                dropped.append((memory, reason))
            else:
                eligible.append(result)
        return eligible, dropped

    def _validate_candidates(self, candidates: list[RetrievedMemory]) -> list[ValidationResult]:
        """Reject blocked statuses and stale projection versions."""
        results: list[ValidationResult] = []
        for memory in candidates:
            status = memory.evolution_status.upper()
            if status in self.BLOCKED_STATUSES:
                results.append(
                    ValidationResult(
                        memory=memory,
                        valid=False,
                        reason=f"{status} memory is not retrievable",
                    )
                )
                continue

            if memory.layer is LifecycleLayer.LONG_TERM and self.authority_checked:
                authority = self._authority_lookup(memory)
                if authority is None:
                    results.append(
                        ValidationResult(
                            memory=memory,
                            valid=False,
                            reason="memory not found in Authority",
                        )
                    )
                    continue
                if authority.evolution_status.value in self.BLOCKED_STATUSES:
                    results.append(
                        ValidationResult(
                            memory=memory,
                            valid=False,
                            reason=f"Authority reports {authority.evolution_status.value}",
                            authority_version=authority.content_version,
                            authority_status=authority.evolution_status.value,
                        )
                    )
                    continue
                if memory.content_version < authority.content_version:
                    results.append(
                        ValidationResult(
                            memory=memory,
                            valid=False,
                            reason="projection version is older than Authority",
                            authority_version=authority.content_version,
                            authority_status=authority.evolution_status.value,
                        )
                    )
                    continue
                if memory.projection_version < authority.projection_version:
                    reason = "projection stale"
                    results.append(
                        ValidationResult(
                            memory=memory,
                            valid=False,
                            reason=reason,
                            authority_version=authority.projection_version,
                            authority_status=authority.evolution_status.value,
                        )
                    )
                    if self.repair_callback is not None:
                        try:
                            self.repair_callback(memory)
                        except Exception:
                            pass
                    continue

            results.append(ValidationResult(memory=memory, valid=True, reason="ok"))
        return results

    def _authority_lookup(
        self, memory: RetrievedMemory
    ) -> Any | None:  # pragma: no cover - depends on DB state
        if self.authority_repository is None:
            return None
        try:
            return self.authority_repository.get(
                tenant_id=memory.tenant_id,
                user_id=memory.user_id,
                memory_id=memory.memory_id,
                include_inactive=True,
            )
        except Exception:
            return None

    def _resolve_conflicts(
        self,
        memories: list[RetrievedMemory],
        *,
        preferred_scope_level: MemoryScope | None = None,
        preferred_scope: str = "",
    ) -> tuple[list[RetrievedMemory], list[ConflictGroup], list[tuple[RetrievedMemory, str]]]:
        """Group competing memories and apply scope precedence."""
        groups = self._build_conflict_groups(memories)
        selected: list[RetrievedMemory] = []
        dropped: list[tuple[RetrievedMemory, str]] = []

        for group in groups:
            if len(group.memories) <= 1:
                selected.extend(group.memories)
                continue

            winner, drops, resolution = self._pick_winner(
                group.memories,
                preferred_scope_level=preferred_scope_level,
                preferred_scope=preferred_scope,
            )
            if winner is None:
                # All members conflict and none should be promoted.
                for memory in group.memories:
                    dropped.append((memory, f"conflict group {group.identity_key}: no safe winner"))
                continue

            selected.append(winner)
            for memory in drops:
                dropped.append((memory, f"conflict group {group.identity_key}: {resolution}"))

        return selected, groups, dropped

    def _build_conflict_groups(self, memories: list[RetrievedMemory]) -> list[ConflictGroup]:
        """Group by the conceptual identity key: memory_type + normalized content key."""
        by_key: dict[str, list[RetrievedMemory]] = {}
        for memory in memories:
            key = self._identity_key(memory)
            by_key.setdefault(key, []).append(memory)

        groups: list[ConflictGroup] = []
        for key, items in by_key.items():
            groups.append(
                ConflictGroup(
                    identity_key=key,
                    memories=list(items),
                    resolution="",
                )
            )
        return groups

    @staticmethod
    def _identity_key(memory: RetrievedMemory) -> str:
        """A stable key for conflict grouping."""
        normalized = memory.content.get("normalized_key") or memory.memory_id
        return f"{memory.memory_type.value}:{normalized}"

    def _pick_winner(
        self,
        memories: list[RetrievedMemory],
        *,
        preferred_scope_level: MemoryScope | None = None,
        preferred_scope: str = "",
    ) -> tuple[RetrievedMemory | None, list[RetrievedMemory], str]:
        """Select one memory from a conflict group with explainable precedence."""
        if not memories:
            return None, [], "empty group"

        # Priority 1: exact preferred scope match.
        if preferred_scope_level is not None:
            preferred_scope_value = preferred_scope.split(":", 1)[-1]
            exact = [
                m
                for m in memories
                if m.scope_level == preferred_scope_level
                and (not preferred_scope or m.scope.split(":", 1)[-1] == preferred_scope_value)
            ]
            if exact:
                winner = self._newest_in_scope(exact)
                return (
                    winner,
                    [m for m in memories if m is not winner],
                    "exact preferred scope match",
                )

        # Priority 2: scope precedence (narrower beats broader).
        def precedence_rank(m: RetrievedMemory) -> int:
            try:
                return self.SCOPE_PRECEDENCE.index(m.scope_level)
            except ValueError:
                return len(self.SCOPE_PRECEDENCE)

        best_rank = min(precedence_rank(m) for m in memories)
        narrowest = [m for m in memories if precedence_rank(m) == best_rank]
        winner = self._newest_in_scope(narrowest)
        return winner, [m for m in memories if m is not winner], "narrower scope wins"

    @staticmethod
    def _newest_in_scope(memories: list[RetrievedMemory]) -> RetrievedMemory:
        """Within a scope-equivalent subset, prefer the newest content_version."""
        return max(memories, key=lambda m: (m.content_version, m.score))


def filter_blocked_statuses(
    candidates: list[RetrievedMemory],
) -> tuple[list[RetrievedMemory], list[tuple[RetrievedMemory, str]]]:
    """Standalone helper: drop DELETED/SUPERSEDED candidates."""
    selected: list[RetrievedMemory] = []
    dropped: list[tuple[RetrievedMemory, str]] = []
    blocked = {EvolutionStatus.DELETED.value, EvolutionStatus.SUPERSEDED.value}
    for candidate in candidates:
        if candidate.evolution_status.upper() in blocked:
            dropped.append((candidate, f"{candidate.evolution_status} memory is not retrievable"))
        else:
            selected.append(candidate)
    return selected, dropped


__all__ = [
    "ConflictGroup",
    "ScopeResolution",
    "ScopeResolver",
    "ValidationResult",
    "filter_blocked_statuses",
]
