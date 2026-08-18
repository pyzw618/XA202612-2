"""Event ingestion orchestration with quality, safety, and extraction boundaries."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from memoryhub.adapter.schemas import ExtractionType, MemoryEvent, QualityStatus
from memoryhub.core.ingestion.extraction import ExtractionExecutor

logger = logging.getLogger(__name__)


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
        short_term_repo=None,
        short_ttl_hours: float = 24.0,
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
        self.short_term_repo = short_term_repo
        self.short_ttl_hours = float(short_ttl_hours)
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
        pending_hashes: set[str] = set()

        for event in events:
            existing = self.event_repo.get_by_id(event.event_id) or pending_by_id.get(
                event.event_id
            )
            if existing is not None:
                if existing.source_hash == event.source_hash:
                    # 重复 event_id + 相同 source_hash：幂等确认，不重复持久化、不触发下游
                    result.accepted += 1
                    result.event_ids.append(event.event_id)
                else:
                    # 同一 event_id 但内容指纹不一致：视为冲突，拒绝
                    result.rejected += 1
                continue

            if event.source_hash in pending_hashes:
                # 批内已出现相同 source_hash：幂等确认，不重复持久化、不触发下游
                result.accepted += 1
                result.event_ids.append(event.event_id)
                continue
            existing_hash = self.event_repo.get_by_source_hash(event.source_hash)
            if existing_hash is not None:
                # 相同 source_hash（不同 event_id）：幂等确认，不重复持久化、不触发下游
                result.accepted += 1
                result.event_ids.append(event.event_id)
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
            safe_payload = dict(safe_event.payload)
            audit_id = str(getattr(outcome, "audit_id", "") or "")
            action = getattr(outcome, "action", "")
            action_value = str(getattr(action, "value", action) or "")
            audit_hash = str(getattr(approved, "audit_record_hash", "") or "")
            if audit_id or action_value or audit_hash:
                safe_payload["_safety"] = {
                    "audit_id": audit_id,
                    "action": action_value,
                    "audit_record_hash": audit_hash,
                }
            safe_event = safe_event.model_copy(update={"payload": safe_payload})
            newly_saved.append(safe_event)
            pending_by_id[safe_event.event_id] = safe_event
            pending_hashes.add(safe_event.source_hash)
            result.accepted += 1
            result.event_ids.append(safe_event.event_id)

        if newly_saved:
            self.event_repo.batch_save(newly_saved)
            if self.short_term_repo is not None:
                self._buffer_short_term(newly_saved)

        self._extract_preferences(newly_saved, result)
        self._extract_knowledge(newly_saved, result)
        self._extract_facts(newly_saved, result)
        return result

    def _buffer_short_term(self, events: list[MemoryEvent]) -> None:
        """短期记忆缓冲：把安全事件写一份到 short_term_memory（TTL 到期清理）。"""
        ttl = datetime.now(timezone.utc) + timedelta(hours=self.short_ttl_hours)
        for event in events:
            try:
                self.short_term_repo.add(
                    user_id=event.user_id or "default",
                    session_id=event.session_id or "",
                    event_id=event.event_id,
                    source_type=(
                        event.source_type.value
                        if hasattr(event.source_type, "value")
                        else str(event.source_type or "")
                    ),
                    text=event.text or "",
                    payload=dict(event.payload or {}),
                    scene=event.scene or "",
                    task_type=event.task_type or "",
                    ttl_until=ttl,
                )
            except Exception:
                logger.exception("short-term buffer write failed for %s", event.event_id)

    def _extract_preferences(
        self, events: list[MemoryEvent], result: EventIngestionResult
    ) -> None:
        if not self.extraction_executor.supports(ExtractionType.PREFERENCE):
            return
        for event in events:
            try:
                self.extraction_executor.run_preference(event)
            except Exception:
                logger.exception(
                    "preference extraction failed for event %s user=%s",
                    event.event_id,
                    event.user_id,
                )
                self._record_extraction_failure(
                    ExtractionType.PREFERENCE, [event], result
                )

    def _extract_knowledge(
        self, events: list[MemoryEvent], result: EventIngestionResult
    ) -> None:
        if not self.extraction_executor.supports(ExtractionType.KNOWLEDGE):
            return
        trajectories: dict[tuple[str, str, str], list[MemoryEvent]] = defaultdict(list)
        for event in events:
            trajectories[(event.user_id, event.session_id, event.task_type)].append(
                event
            )
        logger.info(
            "_extract_knowledge: %d trajectories from %d events",
            len(trajectories),
            len(events),
        )
        for (user_id, session_id, task_type), new_events in trajectories.items():
            trajectory = new_events
            if session_id:
                loader = getattr(self.event_repo, "get_trajectory", None)
                if loader is not None:
                    trajectory = loader(user_id, session_id, task_type)
            logger.info(
                "_extract_knowledge: trajectory user=%s session=%s task=%s events=%d",
                user_id, session_id, task_type, len(trajectory),
            )
            try:
                self.extraction_executor.run_knowledge(trajectory)
            except Exception:
                logger.exception(
                    "_extract_knowledge: failed for trajectory user=%s session=%s task=%s",
                    user_id, session_id, task_type,
                )
                self._record_extraction_failure(
                    ExtractionType.KNOWLEDGE, trajectory, result
                )

    def _extract_facts(
        self, events: list[MemoryEvent], result: EventIngestionResult
    ) -> None:
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
