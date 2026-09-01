"""Apply evolution decisions to the Long-Term Authority store.

The service owns the sequence of status changes required by each evolution
action.  It delegates persistence to the LongTermAuthorityFacade and records
Lineage between versions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

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
    validate_evolution,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.observability.trace_models import TraceSpan, TraceSpanKind
from memoryhub.observability.trace_policy import TraceCategory
from memoryhub.observability.trace_store import TraceStore


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
        """REVIEW / NOOP / REJECTED decisions are not persisted here."""

        return self.action not in {
            EvolutionAction.REVIEW.value,
            "NOOP",
            "REJECTED",
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvolutionService:
    """Bridge between evolution decisions and the Authority store."""

    def __init__(
        self,
        authority_facade: LongTermAuthorityFacade,
        lineage_repository: Any | None = None,
        db: Any | None = None,
        trace_store: TraceStore | None = None,
    ) -> None:
        self.authority_facade = authority_facade
        self.lineage_repository = lineage_repository
        self.db = db
        self.trace_store = trace_store
        self._applied_feedback_ids: set[str] = set()

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

        # A replacement must carry an explicit evidence reference.  Without
        # one, keep the old version reviewable instead of silently superseding
        # it based on content/version shape alone.
        if action is EvolutionAction.SUPERSEDE and not incoming.evidence_refs:
            return EvolutionResult(
                action=EvolutionAction.REVIEW.value,
                new_envelope=incoming,
                previous_envelope=existing,
                lineage=None,
            )

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

    def apply_feedback_signal(
        self,
        item: Any,
        current: LongTermEnvelope,
    ) -> EvolutionResult:
        """Apply a feedback-derived evolution signal to an existing memory.

        The decision is deterministic and bounded.  Terminal statuses are never
        revived; DELETED memories reject the signal explicitly.
        """

        if not isinstance(current, LongTermEnvelope):
            raise EvolutionServiceError("feedback signal requires LongTermEnvelope")

        feedback_id = getattr(item, "feedback_id", "")
        if feedback_id in self._applied_feedback_ids:
            return EvolutionResult(
                action="NOOP",
                new_envelope=current,
                previous_envelope=current,
                lineage=None,
            )

        if current.evolution_status is EvolutionStatus.DELETED:
            return EvolutionResult(
                action="REJECTED",
                new_envelope=current,
                previous_envelope=current,
                lineage=None,
            )

        target_status = self._feedback_target_status(item, current)
        if target_status is None or target_status is current.evolution_status:
            return EvolutionResult(
                action="NOOP",
                new_envelope=current,
                previous_envelope=current,
                lineage=None,
            )

        validate_evolution(current.evolution_status.value, target_status.value)

        relation = self._feedback_relation(
            current.evolution_status, target_status
        )

        result = self._apply_status_transition(
            current, current, target_status, relation
        )
        if feedback_id:
            self._applied_feedback_ids.add(feedback_id)
        return result

    def _feedback_target_status(
        self, item: Any, current: LongTermEnvelope
    ) -> EvolutionStatus | None:
        from memoryhub.application.feedback_service import FeedbackType

        feedback_type = getattr(item, "feedback_type", None)
        # The updater has already persisted the new score before this method
        # is called.  Evolution decisions must use that current state, never
        # the feedback delta/signal itself.
        utility = getattr(current, "utility", 0.0)
        stability = getattr(current, "stability", 0.0)

        # Long-term low value + low stability demotes to DORMANT first.
        if current.evolution_status is EvolutionStatus.ACTIVE:
            if (
                utility < 0.2
                and stability < 0.2
                and feedback_type
                not in {
                    FeedbackType.EXPLICIT_POSITIVE,
                    FeedbackType.USER_CONFIRMATION,
                }
            ):
                return EvolutionStatus.DORMANT
            # Explicit negative / correction pushes an ACTIVE memory into REVIEW.
            if feedback_type in {
                FeedbackType.EXPLICIT_NEGATIVE,
                FeedbackType.USER_CORRECTION,
            }:
                return EvolutionStatus.REVIEW

        # Strong positive feedback can reactivate a DORMANT memory.
        if current.evolution_status is EvolutionStatus.DORMANT:
            if feedback_type in {
                FeedbackType.EXPLICIT_POSITIVE,
                FeedbackType.USER_CONFIRMATION,
            }:
                return EvolutionStatus.ACTIVE

        return None

    @staticmethod
    def _feedback_relation(
        current: EvolutionStatus, target: EvolutionStatus
    ) -> LineageRelation:
        if current is EvolutionStatus.ACTIVE and target is EvolutionStatus.DORMANT:
            return LineageRelation.DEACTIVATED_BY
        if current is EvolutionStatus.DORMANT and target is EvolutionStatus.ACTIVE:
            return LineageRelation.REACTIVATED_BY
        if target is EvolutionStatus.REVIEW:
            return LineageRelation.REVIEWED_BY
        return LineageRelation.DERIVED_FROM

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
        relation = LineageRelation.COEXISTS_WITH
        lineage = self._lineage(saved, existing, relation)
        self._persist_lineage(saved, existing, relation)
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
        self._persist_lineage(saved, existing, relation)

        return EvolutionResult(
            action=action.value,
            new_envelope=saved,
            previous_envelope=existing,
            superseded_envelope=superseded,
            lineage=lineage,
        )

    def _apply_status_transition(
        self,
        incoming: LongTermEnvelope,
        existing: LongTermEnvelope | None,
        target_status: EvolutionStatus,
        relation: LineageRelation,
    ) -> EvolutionResult:
        """Apply a status-only evolution transition and persist lineage."""

        envelope = incoming.model_copy(
            update={
                "evolution_status": target_status,
                "content_version": incoming.content_version + 1,
                "updated_at": _utc_now(),
            }
        )
        saved = self.authority_facade.write(envelope)
        lineage = self._lineage(saved, existing, relation)
        self._persist_lineage(saved, existing, relation)
        return EvolutionResult(
            action=relation.value,
            new_envelope=saved,
            previous_envelope=existing,
            lineage=lineage,
        )

    def _persist_lineage(
        self,
        new_envelope: LongTermEnvelope,
        previous: LongTermEnvelope | None,
        relation: LineageRelation | None,
    ) -> None:
        if self.lineage_repository is None or relation is None:
            return
        db = getattr(self.lineage_repository, "db", None) or self.db
        if db is None:
            return
        try:
            with db.session() as session:
                self._record_lineage_in_session(
                    session, new_envelope, previous, relation
                )
                session.commit()
        except Exception:
            # Lineage is audit-only; never fail the evolution transaction, but
            # make the loss observable instead of reporting a silent success.
            if self.trace_store is not None:
                self.trace_store.record(
                    TraceSpan(
                        span_id=f"span-lineage-error-{new_envelope.memory_id}-{new_envelope.content_version}",
                        trace_id=f"lineage-{new_envelope.memory_id}",
                        kind=TraceSpanKind.EVOLUTION,
                        layer="LINEAGE_PERSISTENCE",
                        category=TraceCategory.EVOLUTION,
                        tenant_id=new_envelope.tenant_id,
                        user_id=new_envelope.user_id,
                        ids={"memory_id": new_envelope.memory_id},
                        classification={
                            "outcome": "ERROR",
                            "reason": "lineage_persistence_failed",
                            "transition_action": relation.value,
                        },
                        status="FAILED",
                    )
                )

    def _record_lineage_in_session(
        self,
        session: Session,
        new_envelope: LongTermEnvelope,
        previous: LongTermEnvelope | None,
        relation: LineageRelation,
    ) -> None:
        parent_memory_id = previous.memory_id if previous else None
        root_memory_id = parent_memory_id or new_envelope.memory_id
        self.lineage_repository.record(
            session=session,
            memory_id=new_envelope.memory_id,
            memory_type=new_envelope.memory_type.value,
            parent_memory_id=parent_memory_id,
            root_memory_id=root_memory_id,
            semantic_version=new_envelope.content_version,
            content_version=new_envelope.content_version,
            transition_action=relation.value,
            tenant_id=new_envelope.tenant_id,
            user_id=new_envelope.user_id,
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
