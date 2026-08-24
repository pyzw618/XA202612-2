"""Apply evolution decisions to the Long-Term Authority store.

The service owns the sequence of status changes required by each evolution
action.  It delegates persistence to the LongTermAuthorityFacade and records
Lineage between versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from memoryhub.domain.contracts import (
    EvolutionAction,
    EvolutionStatus,
    Lineage,
    LineageRelation,
    LongTermEnvelope,
)
from memoryhub.domain.evolution import (
    EvolutionError,
    action_to_lineage_relation,
    decide_evolution_action,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade


class EvolutionServiceError(EvolutionError):
    """An application-level evolution step failed."""


@dataclass(frozen=True, slots=True)
class EvolutionResult:
    """Outcome of applying one evolution action."""

    action: str
    new_envelope: LongTermEnvelope
    previous_envelope: LongTermEnvelope | None
    lineage: Lineage | None
    superseded_envelope: LongTermEnvelope | None = None

    @property
    def persisted(self) -> bool:
        """REVIEW decisions are not persisted."""

        return self.action != EvolutionAction.REVIEW.value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvolutionService:
    """Bridge between evolution decisions and the Authority store."""

    def __init__(self, authority_facade: LongTermAuthorityFacade) -> None:
        self.authority_facade = authority_facade

    def evolve(self, incoming: LongTermEnvelope) -> EvolutionResult:
        """Decide and apply the correct evolution action for an envelope."""

        if not isinstance(incoming, LongTermEnvelope):
            raise EvolutionServiceError("evolution requires LongTermEnvelope")

        existing = self.authority_facade.read(
            tenant_id=incoming.tenant_id,
            user_id=incoming.user_id,
            memory_id=incoming.memory_id,
            include_inactive=True,
        )

        # If no exact memory_id match, check for an active sibling on the same
        # scope chain so that COEXIST/REVIEW decisions are based on the chain.
        chain_sibling = self._find_chain_sibling(incoming) if existing is None else None
        decision_input = existing or chain_sibling

        action = decide_evolution_action(incoming, decision_input)

        if action is EvolutionAction.REVIEW:
            return EvolutionResult(
                action=action.value,
                new_envelope=incoming,
                previous_envelope=existing,
                lineage=None,
            )

        if action is EvolutionAction.COEXIST:
            return self._apply_coexist(incoming, chain_sibling or existing)

        return self._apply_replace(incoming, existing, action)

    def _apply_coexist(
        self,
        incoming: LongTermEnvelope,
        existing: LongTermEnvelope | None,
    ) -> EvolutionResult:
        """COEXIST creates a new ACTIVE memory in a different scope chain."""

        envelope = incoming.model_copy(
            update={
                "content_version": 1,
                "evolution_status": EvolutionStatus.ACTIVE,
            }
        )
        saved = self.authority_facade.write(envelope)
        lineage = self._lineage(saved, existing, LineageRelation.COEXISTS_WITH)
        return EvolutionResult(
            action=EvolutionAction.COEXIST.value,
            new_envelope=saved,
            previous_envelope=existing,
            lineage=lineage,
        )

    def _find_chain_sibling(
        self, incoming: LongTermEnvelope
    ) -> LongTermEnvelope | None:
        """Return an active sibling with the same chain key but a different memory_id."""

        chain_key = LongTermAuthorityFacade.chain_key(incoming)
        for sibling in self.authority_facade.list_active(
            tenant_id=incoming.tenant_id, user_id=incoming.user_id
        ):
            if (
                sibling.memory_id != incoming.memory_id
                and LongTermAuthorityFacade.chain_key(sibling) == chain_key
            ):
                return sibling
        return None

    def _apply_replace(
        self,
        incoming: LongTermEnvelope,
        existing: LongTermEnvelope | None,
        action: EvolutionAction,
    ) -> EvolutionResult:
        """REINFORCE, REVISE and SUPERSEDE replace the existing chain head."""

        if existing is not None:
            # Supersede the existing chain head, then create a strictly newer version.
            superseded_version = existing.content_version + 1
            superseded = existing.model_copy(
                update={
                    "evolution_status": EvolutionStatus.SUPERSEDED,
                    "content_version": superseded_version,
                    "updated_at": _utc_now(),
                }
            )
            self.authority_facade.write(superseded)

            incoming_version = max(
                incoming.content_version, superseded_version + 1
            )
            incoming = incoming.model_copy(
                update={"content_version": incoming_version}
            )
        else:
            superseded = None

        incoming = incoming.model_copy(
            update={"evolution_status": EvolutionStatus.ACTIVE}
        )
        saved = self.authority_facade.write(incoming)

        relation = action_to_lineage_relation(action.value)
        lineage = self._lineage(saved, existing, relation) if relation else None

        return EvolutionResult(
            action=action.value,
            new_envelope=saved,
            previous_envelope=existing,
            superseded_envelope=superseded,
            lineage=lineage,
        )

    def _lineage(
        self,
        new_envelope: LongTermEnvelope,
        previous: LongTermEnvelope | None,
        relation: LineageRelation | None,
    ) -> Lineage | None:
        if previous is None or relation is None:
            return None
        return Lineage(
            tenant_id=new_envelope.tenant_id,
            user_id=new_envelope.user_id,
            lineage_id=f"lineage-{new_envelope.memory_id}-{new_envelope.content_version}",
            from_id=previous.memory_id,
            to_id=new_envelope.memory_id,
            relation=relation,
            evidence_id=new_envelope.evidence_refs[0] if new_envelope.evidence_refs else "",
            reason=f"{relation.value} during evolution",
        )


__all__ = ["EvolutionResult", "EvolutionService", "EvolutionServiceError"]
