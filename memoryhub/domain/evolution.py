"""Evolution decisions and state transitions for Long-Term memories.

Actions (REINFORCE, REVISE, SUPERSEDE, COEXIST, REVIEW) are separate from
EvolutionStatus (ACTIVE, DORMANT, SUPERSEDED, ARCHIVED, DELETED).  The domain
engine decides the action; the application service applies the corresponding
status changes through the Authority facade.
"""

from __future__ import annotations

from memoryhub.domain.contracts import (
    EvolutionAction,
    EvolutionStatus,
    LineageRelation,
    LongTermEnvelope,
)


class EvolutionError(ValueError):
    """An evolution decision or transition is invalid."""


class EvolutionTransitionError(EvolutionError):
    """The requested status transition is not allowed."""


# Allowed transitions for EvolutionStatus.
ALLOWED_EVOLUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    EvolutionStatus.ACTIVE.value: frozenset(
        {
            EvolutionStatus.SUPERSEDED.value,
            EvolutionStatus.ARCHIVED.value,
            EvolutionStatus.DELETED.value,
        }
    ),
    EvolutionStatus.DORMANT.value: frozenset(
        {
            EvolutionStatus.ACTIVE.value,
            EvolutionStatus.ARCHIVED.value,
            EvolutionStatus.DELETED.value,
        }
    ),
    EvolutionStatus.SUPERSEDED.value: frozenset({EvolutionStatus.SUPERSEDED.value}),
    EvolutionStatus.ARCHIVED.value: frozenset(
        {
            EvolutionStatus.ACTIVE.value,
            EvolutionStatus.DELETED.value,
        }
    ),
    EvolutionStatus.DELETED.value: frozenset({EvolutionStatus.DELETED.value}),
}


# Terminal statuses cannot be revived through normal evolution.
TERMINAL_EVOLUTION_STATUSES: frozenset[str] = frozenset(
    {EvolutionStatus.SUPERSEDED.value, EvolutionStatus.DELETED.value}
)


def can_evolve(current: str, target: str) -> bool:
    """Return whether a status transition is legal."""

    return target in ALLOWED_EVOLUTION_TRANSITIONS.get(current, frozenset())


def validate_evolution(current: str, target: str) -> None:
    """Raise if the status transition is not legal."""

    if not can_evolve(current, target):
        raise EvolutionTransitionError(
            f"evolution transition {current}->{target} is not allowed"
        )


def _chain_key(envelope: LongTermEnvelope) -> tuple[str, str, str, str, str]:
    """Authority chain key used to detect scope collisions."""

    return (
        envelope.tenant_id,
        envelope.user_id,
        envelope.memory_type.value,
        envelope.normalized_key,
        f"{envelope.scope_level.value}:{envelope.scope}",
    )


def _content_equivalent(
    left: LongTermEnvelope, right: LongTermEnvelope
) -> bool:
    """Compare the content maps of two envelopes."""

    return left.model_dump(mode="json")["content"] == right.model_dump(mode="json")["content"]


def _scope_compatible(left: LongTermEnvelope, right: LongTermEnvelope) -> bool:
    """Two memories can coexist when they have different scope chains."""

    return _chain_key(left) != _chain_key(right)


def decide_evolution_action(
    incoming: LongTermEnvelope,
    existing: LongTermEnvelope | None,
) -> EvolutionAction:
    """Decide the evolution action without touching storage.

    The decision is based on the incoming envelope and the existing ACTIVE or
    inactive version for the same memory_id.  When no existing memory is found,
    the caller should treat the result as an implicit CREATE.
    """

    if existing is None:
        # Caller materializes the first ACTIVE version.
        return EvolutionAction.REINFORCE

    if existing.evolution_status.value in TERMINAL_EVOLUTION_STATUSES:
        # Cannot modify a terminal version; create a new chain entry.
        return EvolutionAction.REVISE

    same_id = existing.memory_id == incoming.memory_id
    same_chain = _chain_key(existing) == _chain_key(incoming)

    if not same_chain:
        # Different scope chains can both remain ACTIVE.
        return EvolutionAction.COEXIST

    # From here on the two envelopes share the same authority chain.
    if not same_id:
        # A different memory_id on the same chain is a conflict that needs review.
        return EvolutionAction.REVIEW

    if _content_equivalent(existing, incoming):
        # Same content strengthens the existing memory.
        return EvolutionAction.REINFORCE

    if incoming.content_version <= existing.content_version:
        # Incoming version is stale; route to review.
        return EvolutionAction.REVIEW

    # Same chain, newer version, different content: explicit replacement.
    return EvolutionAction.SUPERSEDE


def action_to_lineage_relation(action: str) -> LineageRelation | None:
    """Map an evolution action to the lineage relation recorded between versions."""

    mapping: dict[str, LineageRelation] = {
        EvolutionAction.REINFORCE.value: LineageRelation.REINFORCES,
        EvolutionAction.REVISE.value: LineageRelation.REVISES,
        EvolutionAction.SUPERSEDE.value: LineageRelation.SUPERSEDES,
        EvolutionAction.COEXIST.value: LineageRelation.COEXISTS_WITH,
    }
    return mapping.get(action)


__all__ = [
    "ALLOWED_EVOLUTION_TRANSITIONS",
    "TERMINAL_EVOLUTION_STATUSES",
    "EvolutionError",
    "EvolutionTransitionError",
    "action_to_lineage_relation",
    "can_evolve",
    "decide_evolution_action",
    "validate_evolution",
]
