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
from memoryhub.application.boundary_detector import BoundaryDetector
from memoryhub.application.episode_enricher import EpisodeEventEnricher
from memoryhub.application.episode_service import EpisodeService, EpisodeSnapshotResult
from memoryhub.application.event_gateway import (
    EventGateway,
    EventGatewayResult,
    GatewayStatus,
)
from memoryhub.application.working_reducer import WorkingStateReducer
from memoryhub.application.working_service import WorkingPatchResult, WorkingService
from memoryhub.domain.contracts import (
    BoundaryCheckpointType,
    EpisodeEventContract,
    EpisodeSnapshot,
    EpisodeStatus,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    WorkingPatch,
    WorkingSnapshot,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.database import Database, ExtractionTaskRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
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
        boundary_detector: BoundaryDetector | None = None,
        working_reducer: WorkingStateReducer | None = None,
        episode_enricher: EpisodeEventEnricher | None = None,
        formation_mode: str = "candidate-only",
    ) -> None:
        self.db = db
        self.event_gateway = event_gateway
        self.working_service = working_service or WorkingService(WorkingStateRepository(db))
        self.episode_service = episode_service or EpisodeService(EpisodeRepository(db))
        self.extraction_tasks = extraction_tasks or ExtractionTaskRepository(db)
        self.authority_facade = authority_facade
        self.memory_write_service = memory_write_service
        self.boundary_detector = boundary_detector or BoundaryDetector()
        self.working_reducer = working_reducer or WorkingStateReducer()
        self.episode_enricher = episode_enricher or EpisodeEventEnricher()
        if formation_mode not in {"shadow", "candidate-only", "authority"}:
            raise ValueError("unsupported formation mode")
        self.formation_mode = formation_mode

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
            working_result = None
            snapshot_result = None
            if gateway.status is GatewayStatus.IDEMPOTENT:
                current = self.working_service.repository.get(
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    task_id=event.task_id,
                )
                if current is not None:
                    working_result = WorkingPatchResult(
                        working_state=current,
                        applied_paths=(),
                        skipped_paths=(),
                        compressed_state=self.working_service.compressed_snapshot(
                            tenant_id=event.tenant_id,
                            user_id=event.user_id,
                            task_id=event.task_id,
                        ),
                    )
                episode = self.episode_service.repository.get_by_task_id(
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    task_id=event.task_id,
                )
                if episode is not None:
                    snapshot_result = EpisodeSnapshotResult(
                        snapshot=self.episode_service._to_contract(episode),
                        resume_token="",
                    )
            return CanonicalWriteResult(
                gateway=gateway,
                working=working_result,
                episode_snapshot=snapshot_result,
                # A retry must not turn a previously low-value event into a
                # new reflection trigger. Existing boundary tasks are already
                # durable and idempotent in ExtractionTaskRepository.
                reflection_task=None,
            )

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

        # When an adapter does not provide explicit state objects, the
        # canonical service still owns the deterministic task-state update.
        # This is deliberately conservative: payload fields are only projected
        # into Working/Episode after EventGateway has accepted the event.
        if working_result is None:
            working_result = self._orchestrate_working(event)

        snapshot = episode_snapshot or checkpoint
        episode_event_result = None
        reflection_boundary = episode_event is not None or snapshot is not None
        if episode_event is not None:
            self._ensure_episode_exists(episode_event)
            episode_event_result = self.episode_service.append(episode_event)
        snapshot_result = None
        if snapshot is not None:
            self._ensure_episode_exists(snapshot)
            snapshot_result = self.episode_service.snapshot(snapshot)

        if episode_event is None and snapshot is None:
            episode_event_result, snapshot_result = self._orchestrate_episode(
                event,
                working_result=working_result,
            )
            reflection_boundary = snapshot_result is not None

        task = None
        if reflection_boundary:
            task = self.extraction_tasks.enqueue(
                event_ids=[event.event_id],
                tenant_id=event.tenant_id,
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

    def write_authority(
        self,
        event: MemoryEventContract,
        envelope: LongTermEnvelope,
        *,
        action: MemoryDecision | str | None = None,
    ) -> tuple[LongTermEnvelope, Any | None]:
        """Commit a worker promotion through the canonical Authority writer.

        A worker may retry after the event itself is already idempotent.  This
        method therefore accepts COMMITTED and IDEMPOTENT gateway results, but
        never exposes the repository as a write shortcut.
        """

        gateway = self.event_gateway.submit(event)
        if gateway.status not in {GatewayStatus.COMMITTED, GatewayStatus.IDEMPOTENT}:
            raise RuntimeError(f"authority write blocked by gateway: {gateway.reason_code}")
        return self._write_long_term(event, envelope, action=action)

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

    def _orchestrate_working(self, event: MemoryEventContract) -> WorkingPatchResult:
        current = self.working_service.repository.get(
            tenant_id=event.tenant_id, user_id=event.user_id, task_id=event.task_id
        )
        if current is None:
            created = self.working_service.create(
                self.working_reducer.initial_snapshot(event),
                working_state_id=self._working_state_id(event),
            )
            return WorkingPatchResult(
                working_state=created,
                applied_paths=(),
                skipped_paths=(),
                compressed_state=self.working_service.compressed_snapshot(
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    task_id=event.task_id,
                ),
            )
        patch = self.working_reducer.patch(
            event,
            current.state,
            base_version=current.version,
        )
        if patch is None:
            return WorkingPatchResult(
                working_state=current,
                applied_paths=(),
                skipped_paths=(),
                compressed_state=self.working_service.compressed_snapshot(
                    tenant_id=event.tenant_id,
                    user_id=event.user_id,
                    task_id=event.task_id,
                ),
            )
        return self.working_service.apply_patch(patch, event_id=event.event_id)

    def _orchestrate_episode(
        self,
        event: MemoryEventContract,
        *,
        working_result: WorkingPatchResult,
    ) -> tuple[Any, EpisodeSnapshotResult | None]:
        episode = self.episode_service.repository.get_by_task_id(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            task_id=event.task_id,
        )
        if episode is None:
            episode_id = str(event.payload.get("episode_id") or f"episode-{event.task_id}")
            self.episode_service.create(
                episode_id=episode_id,
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                task_id=event.task_id,
                session_id=event.session_id,
                goal=str(working_result.state.get("current_goal", event.event_type)),
            )
            episode = self.episode_service.repository.get(
                tenant_id=event.tenant_id, user_id=event.user_id, episode_id=episode_id
            )
        if episode is None:
            raise RuntimeError("episode orchestration failed")

        history = self.episode_service.repository.list_events(
            tenant_id=event.tenant_id, user_id=event.user_id, episode_id=episode.episode_id
        )
        decision = self.boundary_detector.detect(
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            task_id=event.task_id,
            event_type=event.event_type,
            event_payload=event.payload,
            episode_status=episode.status,
            working_state=working_result.state,
            episode_history=[{"phase": item.payload.get("phase")} for item in history],
            timestamp=event.occurred_at.timestamp(),
        )
        seq = episode.last_event_seq + 1
        event_result = self.episode_service.append(
            EpisodeEventContract(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                episode_id=episode.episode_id,
                task_id=event.task_id,
                seq_no=seq,
                event_type=(decision.checkpoint_type.value if decision else "CANONICAL_EVENT"),
                payload=self.episode_enricher.enrich(event),
                source_event_id=event.event_id,
            )
        )
        if decision is None:
            return event_result, None
        status = {
            BoundaryCheckpointType.COMPLETE: EpisodeStatus.COMPLETED,
            BoundaryCheckpointType.FAILED: EpisodeStatus.FAILED,
        }.get(decision.checkpoint_type, EpisodeStatus.ACTIVE)
        return event_result, self.episode_service.snapshot(
            EpisodeSnapshot(
                tenant_id=event.tenant_id,
                user_id=event.user_id,
                episode_id=episode.episode_id,
                task_id=event.task_id,
                session_id=event.session_id,
                status=status,
                current_phase=str(
                    event.payload.get("phase") or episode.current_phase or "active"
                ),
                goal=str(
                    working_result.state.get("current_goal", episode.goal or event.event_type)
                ),
                pending_steps=self._as_strings(working_result.state.get("pending_steps")),
                completed_steps=self._as_strings(working_result.state.get("completed_steps")),
                constraints=self._as_strings(working_result.state.get("constraints")),
                last_event_seq=event_result.seq_no,
                snapshot_version=episode.snapshot_version,
            )
        )

    @staticmethod
    def _working_state_id(event: MemoryEventContract) -> str:
        return f"working-{event.tenant_id}-{event.user_id}-{event.task_id}"[:64]

    @staticmethod
    def _as_strings(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if value not in (None, "") else []

    @staticmethod
    def _first_text(payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

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
        self._enqueue_projection_outbox(event, envelope)
        return envelope, receipt

    def _enqueue_projection_outbox(
        self, event: MemoryEventContract, envelope: LongTermEnvelope
    ) -> None:
        """Enqueue a vector projection outbox item after a successful Authority write."""
        operation = "delete" if envelope.evolution_status is EvolutionStatus.DELETED else "upsert"
        priority = 10 if operation == "delete" else 0
        payload = {
            "memory_id": envelope.memory_id,
            "memory_type": envelope.memory_type.value,
            "operation": operation,
            "content_version": envelope.content_version,
            "projection_type": "vector",
        }
        with self.db.session() as session:
            MemoryProjectionOutboxRepository(self.db).enqueue(
                memory_id=envelope.memory_id,
                memory_type=envelope.memory_type.value,
                operation=operation,
                payload=payload,
                session=session,
                tenant_id=envelope.tenant_id,
                user_id=envelope.user_id,
                event_id=event.event_id,
                content_version=envelope.content_version,
                projection_type="vector",
                priority=priority,
            )

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
