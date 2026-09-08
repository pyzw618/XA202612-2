"""Durable vNext Formation worker for canonical extraction tasks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from memoryhub.adapter.schemas import ExtractionTask, ExtractionType, MemoryDecision
from memoryhub.application.candidate_service import CandidateService
from memoryhub.application.consolidation_service import (
    ConsolidationContext,
    ConsolidationService,
    PromotionDecision,
)
from memoryhub.application.reflection_service import ReflectionService
from memoryhub.core.ingestion.retry import ExtractionPermanentError
from memoryhub.core.reflection.schema import ReflectionInput
from memoryhub.domain.contracts import (
    CandidateStatus,
    EvolutionAction,
    EvolutionStatus,
    MemoryEventContract,
)
from memoryhub.domain.evolution import decide_evolution_action
from memoryhub.domain.long_term import LongTermContentValidator
from memoryhub.storage.vnext_repositories import (
    CandidateRepository,
    EpisodeRepository,
    EvidenceRepository,
    WorkingStateRepository,
)


@dataclass(slots=True)
class FormationProcessResult:
    candidate_ids: list[str] = field(default_factory=list)
    candidate_statuses: dict[str, str] = field(default_factory=dict)
    memory_ids: list[str] = field(default_factory=list)


class FormationWorker:
    """Run Reflection → Candidate/Evidence → Promotion behind a retry lease.

    ``shadow`` writes no Formation state. ``candidate-only`` writes staging and
    evidence but cannot touch Authority. ``authority`` enables Consolidation;
    every resulting Authority mutation is delegated to CanonicalWriteService.
    """

    def __init__(
        self,
        db,
        *,
        task_repository=None,
        event_repository=None,
        canonical_write_service,
        mode: str = "candidate-only",
        reflection_service: ReflectionService | None = None,
        consolidation_service: ConsolidationService | None = None,
    ) -> None:
        if mode not in {"shadow", "candidate-only", "authority"}:
            raise ValueError("unsupported formation worker mode")
        self.db = db
        self.task_repository = task_repository
        self.event_repository = event_repository
        self.canonical_write_service = canonical_write_service
        self.mode = mode
        if reflection_service is None:
            raise TypeError(
                "FormationWorker requires an explicit reflection_service; "
                "use ReflectionService(StructuredReflectionModel(<configured llm>)) "
                "in production or inject a deterministic/fake ReflectionService in tests"
            )
        self.reflection = reflection_service
        self.candidates = CandidateRepository(db)
        self.candidate_service = CandidateService(self.candidates)
        self.evidence = EvidenceRepository(db)
        self.episodes = EpisodeRepository(db)
        self.working = WorkingStateRepository(db)
        self.authority = canonical_write_service.authority_facade
        self.consolidation = consolidation_service or ConsolidationService(self.authority)
        self.validator = LongTermContentValidator()

    def supports(self, extractor_type: ExtractionType | str) -> bool:
        return str(getattr(extractor_type, "value", extractor_type)) in {
            item.value for item in ExtractionType
        }

    def execute(
        self,
        task: ExtractionTask,
        events: list[MemoryEventContract],
    ) -> FormationProcessResult:
        if not events:
            raise ExtractionPermanentError("extraction.event_missing")
        if self.mode == "shadow":
            return FormationProcessResult()
        result = FormationProcessResult()
        for event in events:
            if task.tenant_id and task.tenant_id != event.tenant_id:
                raise ExtractionPermanentError("extraction.tenant_mismatch")
            episode = self.episodes.get_by_task_id(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                task_id=event.task_id,
            )
            episode_id = episode.episode_id if episode is not None else f"episode-{event.task_id}"
            working = self.working.get(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                task_id=event.task_id,
            )
            history = []
            if episode is not None:
                history = [
                    {"event_type": item.event_type, "payload": dict(item.payload)}
                    for item in self.episodes.list_events(
                        tenant_id=event.tenant_id,
                        user_id=event.user_id,
                        episode_id=episode.episode_id,
                    )
                ]
            reflection_input = ReflectionInput(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                task_id=event.task_id,
                episode_id=episode_id,
                event_id=event.event_id,
                payload_summary=dict(event.payload),
                working_state_snapshot=dict(working.state) if working is not None else {},
                episode_history_summary=history,
                requested_memory_type=str(event.payload.get("memory_type", "")) or None,
                scope_hint=str(event.payload.get("scope_level", "")) or None,
                occurred_at=event.occurred_at,
            )
            candidate = self.reflection.run(reflection_input)
            staged = self.candidate_service.stage(
                candidate, source_event=event, episode_id=episode_id
            )
            candidate_id = staged.candidate.candidate_id
            result.candidate_ids.append(candidate_id)
            result.candidate_statuses[candidate_id] = staged.candidate.status
            self._record_candidate_evidence(event, staged.candidate)

            if self.mode != "authority":
                continue
            promoted = self._promote(
                event,
                staged.candidate,
                explicit_long_term=event.payload.get("explicit_long_term") is True,
            )
            if promoted:
                result.memory_ids.append(promoted)
                result.candidate_statuses[candidate_id] = CandidateStatus.CONFIRMED.value
        if self.task_repository is not None:
            self.task_repository.record_formation_result(
                task.task_id,
                candidate_ids=result.candidate_ids,
                candidate_statuses=result.candidate_statuses,
                memory_ids=result.memory_ids,
            )
        return self._deduplicate(result)

    def run_due(self, *, user_id: str | None = None, limit: int = 20, now=None):
        """Standalone worker entry point for tests and controlled operations."""

        if self.task_repository is None:
            raise RuntimeError("formation worker requires a task repository")
        from memoryhub.core.ingestion.retry import ExtractionRetryRunResult

        tasks = self.task_repository.claim_due(user_id=user_id, limit=limit, now=now)
        outcome = ExtractionRetryRunResult(claimed=len(tasks))
        for task in tasks:
            try:
                contracts = [
                    self.event_repository.get_vnext_contract(event_id)
                    for event_id in task.event_ids or [task.event_id]
                ]
                if any(event is None for event in contracts):
                    raise ExtractionPermanentError("extraction.event_missing")
                self.execute(task, [event for event in contracts if event is not None])
                self.task_repository.mark_succeeded(task.task_id, now=now)
                outcome.succeeded += 1
            except ExtractionPermanentError as exc:
                self.task_repository.mark_dead(task.task_id, error_code=exc.code, now=now)
                outcome.dead_lettered += 1
            except Exception:
                self.task_repository.mark_failed(
                    task.task_id,
                    error_code=f"extraction.{task.extractor_type.value}.failed",
                    now=now,
                )
                outcome.retried += 1
        return outcome

    def _record_candidate_evidence(self, event: MemoryEventContract, candidate) -> None:
        evidence_id = "evidence_" + hashlib.sha256(
            f"{candidate.candidate_id}|{event.event_id}|{event.source_hash}".encode()
        ).hexdigest()[:48]
        self.evidence.record(
            evidence_id=evidence_id,
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            memory_id=candidate.candidate_id,
            memory_type=candidate.memory_type,
            event_id=event.event_id,
            source_hash=event.source_hash,
            content_ref=f"event:{event.event_id}",
            source_type=event.source_type,
        )

    def _promote(self, event, candidate, *, explicit_long_term: bool) -> str | None:
        memory_id = "memory_" + hashlib.sha256(
            f"{candidate.tenant_id}|{candidate.user_id}|{candidate.normalized_key}|{candidate.scope_level}|{candidate.scope}".encode()
        ).hexdigest()[:27]
        decision = self.consolidation.consolidate(
            candidate,
            memory_id=memory_id,
            context=ConsolidationContext(
                source_event=event,
                explicit_long_term=explicit_long_term,
                sensitivity_level=event.sensitivity_level,
                tool_trust=str(event.payload.get("tool_trust", "medium")),
            ),
        )
        if decision.decision != PromotionDecision.PROMOTE or decision.envelope is None:
            return None
        validation = self.validator.validate(decision.envelope)
        if not validation.ok:
            return None
        envelope = decision.envelope
        existing = self.authority.read(
            tenant_id=envelope.tenant_id,
            user_id=envelope.user_id,
            memory_id=envelope.memory_id,
            include_inactive=True,
        )
        action_input = existing
        if action_input is None:
            action_input = self._find_sibling(envelope)
        action = decide_evolution_action(envelope, action_input)
        if action is EvolutionAction.REVIEW:
            return None
        if existing is not None and action is EvolutionAction.REINFORCE:
            # A redelivered task must not create a new version when it carries
            # no new evidence.  When evidence did grow, append it through the
            # canonical writer without manufacturing a superseded version.
            same_content = existing.content == envelope.content
            known_evidence = set(existing.evidence_refs)
            incoming_evidence = set(envelope.evidence_refs)
            if same_content and incoming_evidence <= known_evidence:
                return envelope.memory_id
            if same_content:
                envelope = envelope.model_copy(
                    update={"content_version": existing.content_version + 1}
                )
                self.canonical_write_service.write_authority(
                    event, envelope, action=MemoryDecision.REINFORCE
                )
                self.candidates.transition(
                    tenant_id=candidate.tenant_id,
                    user_id=candidate.user_id,
                    candidate_id=candidate.candidate_id,
                    status=CandidateStatus.CONFIRMED.value,
                )
                return envelope.memory_id
        if (
            action
            in {
                EvolutionAction.SUPERSEDE,
                EvolutionAction.REVISE,
                EvolutionAction.REINFORCE,
            }
            and existing is not None
        ):
            superseded = existing.model_copy(
                update={
                    "evolution_status": EvolutionStatus.SUPERSEDED,
                    "content_version": existing.content_version + 1,
                }
            )
            self.canonical_write_service.write_authority(
                event, superseded, action=MemoryDecision.SUPERSEDE
            )
            envelope = envelope.model_copy(
                update={
                    "content_version": max(
                        envelope.content_version, existing.content_version + 2
                    )
                }
            )
        memory_action = {
            EvolutionAction.REINFORCE: MemoryDecision.REINFORCE,
            EvolutionAction.REVISE: MemoryDecision.REVISE,
            EvolutionAction.SUPERSEDE: MemoryDecision.SUPERSEDE,
            EvolutionAction.COEXIST: MemoryDecision.COEXIST,
        }.get(action, MemoryDecision.NEW)
        self.canonical_write_service.write_authority(
            event, envelope, action=memory_action
        )
        if self._is_structured_fact(envelope):
            # The semantic FACT adapter may persist a pending decision instead
            # of an ACTIVE Knowledge row.  Keep the vNext candidate pending in
            # that case; confirmation is only valid after a real commit.
            if not self._fact_is_active(envelope.memory_id):
                return None
        self.candidates.transition(
            tenant_id=candidate.tenant_id,
            user_id=candidate.user_id,
            candidate_id=candidate.candidate_id,
            status=CandidateStatus.CONFIRMED.value,
        )
        return envelope.memory_id

    @staticmethod
    def _is_structured_fact(envelope) -> bool:
        content = dict(getattr(envelope, "content", {}) or {})
        return (
            str(getattr(getattr(envelope, "memory_type", None), "value", ""))
            == "semantic"
            and all(str(content.get(field, "")).strip()
                    for field in ("subject", "predicate", "object_value"))
        )

    def _fact_is_active(self, memory_id: str) -> bool:
        service = getattr(self.canonical_write_service, "memory_write_service", None)
        repo = getattr(service, "know_repo", None)
        if repo is None:
            return False
        memory = repo.get_by_id(memory_id)
        return memory is not None and str(
            getattr(getattr(memory, "status", None), "value", getattr(memory, "status", ""))
        ) == "active"

    def _find_sibling(self, envelope):
        related = None
        for sibling in self.authority.list_active(
            tenant_id=envelope.tenant_id, user_id=envelope.user_id
        ):
            if self.authority.chain_key(sibling) == self.authority.chain_key(envelope):
                return sibling
            if (
                related is None
                and sibling.memory_type == envelope.memory_type
                and sibling.normalized_key == envelope.normalized_key
            ):
                related = sibling
        return related

    @staticmethod
    def _deduplicate(result: FormationProcessResult) -> FormationProcessResult:
        result.candidate_ids = sorted(set(result.candidate_ids))
        result.memory_ids = sorted(set(result.memory_ids))
        return result


__all__ = ["FormationProcessResult", "FormationWorker"]
