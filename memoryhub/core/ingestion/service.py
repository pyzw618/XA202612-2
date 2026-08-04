"""Event ingestion orchestration with quality, safety, and extraction boundaries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from memoryhub.adapter.schemas import ExtractionType, MemoryEvent, QualityStatus
from memoryhub.core.ingestion.extraction import ExtractionExecutor


@dataclass(slots=True)
class EventIngestionResult:
    accepted: int = 0
    rejected: int = 0
    event_ids: list[str] = field(default_factory=list)
    extraction_failures: int = 0
    retry_tasks_enqueued: int = 0
    retry_queue_failures: int = 0


class EventIngestionService:
    """Persist only quality-approved, gate-approved events and extract once."""

    def __init__(
        self,
        *,
        event_repo,
        safety_gate,
        quality_scorer,
        memory_write_service,
        preference_extractor=None,
        preference_updater=None,
        knowledge_extractor=None,
        fact_ingestion_adapter=None,
        extraction_task_repo=None,
        extraction_executor=None,
        extraction_max_attempts: int = 3,
    ) -> None:
        self.event_repo = event_repo
        self.safety_gate = safety_gate
        self.quality_scorer = quality_scorer
        self.memory_write_service = memory_write_service
        self.preference_extractor = preference_extractor
        self.preference_updater = preference_updater
        self.knowledge_extractor = knowledge_extractor
        self.fact_ingestion_adapter = fact_ingestion_adapter
        self.extraction_task_repo = extraction_task_repo
        self.extraction_max_attempts = max(1, int(extraction_max_attempts))
        self.extraction_executor = extraction_executor or ExtractionExecutor(
            memory_write_service=memory_write_service,
            preference_extractor=preference_extractor,
            preference_updater=preference_updater,
            knowledge_extractor=knowledge_extractor,
            fact_ingestion_adapter=fact_ingestion_adapter,
        )

    def ingest(self, events: list[MemoryEvent]) -> EventIngestionResult:
        result = EventIngestionResult()
        newly_saved: list[MemoryEvent] = []
        pending_by_id: dict[str, MemoryEvent] = {}

        for event in events:
            existing = self.event_repo.get_by_id(event.event_id) or pending_by_id.get(
                event.event_id
            )
            if existing is not None:
                if existing.source_hash == event.source_hash:
                    result.accepted += 1
                    result.event_ids.append(event.event_id)
                else:
                    result.rejected += 1
                continue

            quality = self.quality_scorer.score(event)
            if quality.status != QualityStatus.ACCEPTED:
                result.rejected += 1
                continue
            scored_event = event.model_copy(update={"quality": quality})
            outcome = self.safety_gate.route(scored_event)
            approved = getattr(outcome, "approved", None)
            if approved is None:
                result.rejected += 1
                continue

            safe_event = approved.safe_event
            newly_saved.append(safe_event)
            pending_by_id[safe_event.event_id] = safe_event
            result.accepted += 1
            result.event_ids.append(safe_event.event_id)

        if newly_saved:
            self.event_repo.batch_save(newly_saved)

        self._extract_preferences(newly_saved, result)
        self._extract_knowledge(newly_saved, result)
        self._extract_facts(newly_saved, result)
        return result

    def _extract_preferences(self, events: list[MemoryEvent], result: EventIngestionResult) -> None:
        if not self.extraction_executor.supports(ExtractionType.PREFERENCE):
            return
        for event in events:
            try:
                self.extraction_executor.run_preference(event)
            except Exception:
                self._record_extraction_failure(ExtractionType.PREFERENCE, [event], result)

    def _extract_knowledge(self, events: list[MemoryEvent], result: EventIngestionResult) -> None:
        if not self.extraction_executor.supports(ExtractionType.KNOWLEDGE):
            return
        trajectories: dict[tuple[str, str, str], list[MemoryEvent]] = defaultdict(list)
        for event in events:
            trajectories[(event.user_id, event.session_id, event.task_type)].append(event)
        for (user_id, session_id, task_type), new_events in trajectories.items():
            trajectory = new_events
            if session_id:
                loader = getattr(self.event_repo, "get_trajectory", None)
                if loader is not None:
                    trajectory = loader(user_id, session_id, task_type)
            try:
                self.extraction_executor.run_knowledge(trajectory)
            except Exception:
                self._record_extraction_failure(ExtractionType.KNOWLEDGE, trajectory, result)

    def _extract_facts(self, events: list[MemoryEvent], result: EventIngestionResult) -> None:
        if not self.extraction_executor.supports(ExtractionType.FACT):
            return
        for event in events:
            try:
                self.extraction_executor.run_fact(event)
            except Exception:
                self._record_extraction_failure(ExtractionType.FACT, [event], result)

    def _record_extraction_failure(
        self,
        extractor_type: ExtractionType,
        events: list[MemoryEvent],
        result: EventIngestionResult,
    ) -> None:
        """Keep event acceptance durable and enqueue only safe event references."""
        result.extraction_failures += 1
        if self.extraction_task_repo is None:
            result.retry_queue_failures += 1
            return
        try:
            _, created = self.extraction_task_repo.enqueue(
                event_ids=[event.event_id for event in events],
                user_id=events[0].user_id,
                extractor_type=extractor_type,
                max_attempts=self.extraction_max_attempts,
                error_code=f"extraction.{extractor_type.value}.failed",
            )
        except Exception:
            # Never expose or persist exception text; accepted events remain committed.
            result.retry_queue_failures += 1
        else:
            if created:
                result.retry_tasks_enqueued += 1
