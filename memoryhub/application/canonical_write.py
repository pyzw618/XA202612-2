"""Canonical vNext write orchestration for events, task state and Authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.adapter.schemas import (
    ExtractionTask,
    ExtractionType,
    MemoryDecision,
    MemoryProvenance,
    SourceType,
)
from memoryhub.application.episode_service import EpisodeService, EpisodeSnapshotResult
from memoryhub.application.event_gateway import (
    EventGateway,
    EventGatewayResult,
    GatewayStatus,
)
from memoryhub.application.working_service import WorkingPatchResult, WorkingService
from memoryhub.domain.contracts import (
    EpisodeEventContract,
    EpisodeSnapshot,
    LongTermEnvelope,
    MemoryEventContract,
    WorkingPatch,
    WorkingSnapshot,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.database import Database, ExtractionTaskRepository
from memoryhub.storage.vnext_repositories import EpisodeRepository, WorkingStateRepository


@dataclass(frozen=True, slots=True)
class CanonicalWriteResult:
    """Detached result exposing every durable step of one canonical write."""

    gateway: EventGatewayResult
    working: WorkingPatchResult | None = None
    episode_event: Any | None = None
    episode_snapshot: EpisodeSnapshotResult | None = None
    reflection_task: ExtractionTask | None = None
    long_term: LongTermEnvelope | None = None
    long_term_receipt: Any | None = None

    @property
    def status(self) -> GatewayStatus:
        return self.gateway.status

    @property
    def event_id(self) -> str:
        return self.gateway.event_id


class CanonicalWriteService:
    """Join the ordered ingress, task-state transitions and long-term writer.

    EventGateway owns policy/idempotency ingress.  Working and Episode services
    own their CAS/sequence invariants.  Long-term writes are delegated to the
    existing MemoryWriteService, whose DomainMemoryWriter commits the business
    row, Evidence, Lineage and Projection Outbox together.
    """

    def __init__(
        self,
        db: Database,
        *,
        event_gateway: EventGateway,
        working_service: WorkingService | None = None,
        episode_service: EpisodeService | None = None,
        extraction_tasks: ExtractionTaskRepository | None = None,
        authority_facade: LongTermAuthorityFacade | None = None,
        memory_write_service: Any | None = None,
    ) -> None:
        self.db = db
        self.event_gateway = event_gateway
        self.working_service = working_service or WorkingService(WorkingStateRepository(db))
        self.episode_service = episode_service or EpisodeService(EpisodeRepository(db))
        self.extraction_tasks = extraction_tasks or ExtractionTaskRepository(db)
        self.authority_facade = authority_facade
        self.memory_write_service = memory_write_service

    def write(
        self,
        event: MemoryEventContract,
        *,
        working_patch: WorkingPatch | None = None,
        working_snapshot: WorkingSnapshot | None = None,
        working_state_id: str | None = None,
        episode_event: EpisodeEventContract | None = None,
        episode_snapshot: EpisodeSnapshot | None = None,
        checkpoint: EpisodeSnapshot | None = None,
        long_term: LongTermEnvelope | None = None,
        reflection_type: ExtractionType | str | None = None,
        long_term_action: MemoryDecision | str | None = None,
    ) -> CanonicalWriteResult:
        if not isinstance(event, MemoryEventContract):
            raise TypeError("canonical write requires MemoryEventContract")
        gateway = self.event_gateway.submit(event)
        if gateway.status is not GatewayStatus.COMMITTED:
            return CanonicalWriteResult(gateway=gateway)

        working_result: WorkingPatchResult | None = None
        if working_snapshot is not None:
            if not working_state_id:
                raise ValueError("working_state_id is required for a WorkingSnapshot")
            created = self.working_service.create(
                working_snapshot,
                working_state_id=working_state_id,
            )
            working_result = WorkingPatchResult(
                working_state=created,
                applied_paths=(),
                skipped_paths=(),
                compressed_state=self.working_service.compressed_snapshot(
                    tenant_id=created.tenant_id,
                    user_id=created.user_id,
                    task_id=created.task_id,
                ),
            )
        if working_patch is not None:
            working_result = self.working_service.apply_patch(
                working_patch, event_id=event.event_id
            )

        snapshot = episode_snapshot or checkpoint
        episode_event_result = None
        if episode_event is not None:
            self._ensure_episode_exists(episode_event)
            episode_event_result = self.episode_service.append(episode_event)
        snapshot_result = None
        if snapshot is not None:
            self._ensure_episode_exists(snapshot)
            snapshot_result = self.episode_service.snapshot(snapshot)

        task = self.extraction_tasks.enqueue(
            event_ids=[event.event_id],
            user_id=event.user_id,
            extractor_type=self._reflection_type(event, reflection_type),
        )[0]

        long_term_result = None
        receipt = None
        if long_term is not None:
            long_term_result, receipt = self._write_long_term(
                event, long_term, action=long_term_action
            )

        return CanonicalWriteResult(
            gateway=gateway,
            working=working_result,
            episode_event=episode_event_result,
            episode_snapshot=snapshot_result,
            reflection_task=task,
            long_term=long_term_result,
            long_term_receipt=receipt,
        )

    submit = write
    write_event = write

    def _ensure_episode_exists(
        self,
        reference: EpisodeEventContract | EpisodeSnapshot,
    ) -> None:
        existing = self.episode_service.repository.get(
            tenant_id=reference.tenant_id,
            user_id=reference.user_id,
            episode_id=reference.episode_id,
        )
        if existing is not None:
            return
        goal = ""
        if isinstance(reference, EpisodeSnapshot):
            goal = reference.goal
        session_id = getattr(reference, "session_id", "")
        self.episode_service.create(
            episode_id=reference.episode_id,
            tenant_id=reference.tenant_id,
            user_id=reference.user_id,
            task_id=reference.task_id,
            session_id=session_id,
            goal=goal,
        )

    def _write_long_term(
        self,
        event: MemoryEventContract,
        envelope: LongTermEnvelope,
        *,
        action: MemoryDecision | str | None,
    ) -> tuple[LongTermEnvelope, Any | None]:
        if self.authority_facade is None:
            raise RuntimeError("canonical write requires a LongTermAuthorityFacade")
        validation = self.authority_facade.prepare(envelope)
        if validation.existing is not None and (
            validation.existing.model_dump(mode="json") == envelope.model_dump(mode="json")
        ):
            return envelope, None

        repository = self.authority_facade.repository
        legacy_memory = getattr(repository, "legacy_memory")(envelope)
        receipt = None
        if self.memory_write_service is not None:
            receipt = self.memory_write_service.upsert_memory(
                legacy_memory,
                action=action or self._memory_action(validation.existing, envelope),
                provenance=self._provenance(event),
                skip_write_gate=True,
            )
        else:
            repository.save(envelope)
        return envelope, receipt

    @staticmethod
    def _memory_action(
        existing: LongTermEnvelope | None, envelope: LongTermEnvelope
    ) -> MemoryDecision:
        if existing is None:
            return MemoryDecision.NEW
        if envelope.evolution_status.value == "SUPERSEDED":
            return MemoryDecision.SUPERSEDE
        if envelope.content_version > existing.content_version:
            return MemoryDecision.REVISE
        return MemoryDecision.REINFORCE

    @staticmethod
    def _provenance(event: MemoryEventContract) -> MemoryProvenance:
        source = event.source_type.lower()
        source_type = (
            SourceType.TOOL_RESULT
            if "tool" in source
            else SourceType.MANUAL_CONFIG
            if "manual" in source or "config" in source
            else SourceType.USER_BEHAVIOR
        )
        return MemoryProvenance(
            event_id=event.event_id,
            source_hash=event.source_hash,
            source_type=source_type,
        )

    @staticmethod
    def _reflection_type(
        event: MemoryEventContract, requested: ExtractionType | str | None
    ) -> ExtractionType:
        if requested is not None:
            return requested if isinstance(requested, ExtractionType) else ExtractionType(requested)
        hint = str(event.payload.get("memory_type", "") or event.event_type).lower()
        if "preference" in hint:
            return ExtractionType.PREFERENCE
        if "fact" in hint:
            return ExtractionType.FACT
        return ExtractionType.KNOWLEDGE


__all__ = ["CanonicalWriteResult", "CanonicalWriteService"]
