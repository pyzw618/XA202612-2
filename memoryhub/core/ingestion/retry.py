"""Explicit durable retry runner for preference, knowledge, and fact extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from memoryhub.adapter.schemas import ExtractionTask, ExtractionTaskStatus, ExtractionType


class ExtractionPermanentError(RuntimeError):
    """A stable terminal task error with no sensitive exception context."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class ExtractionRetryRunResult:
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0


class ExtractionRetryService:
    """Claim tasks and replay only already persisted, gate-approved events."""

    def __init__(self, *, task_repo, event_repo, executor) -> None:
        self.task_repo = task_repo
        self.event_repo = event_repo
        self.executor = executor

    def run_due(
        self,
        *,
        user_id: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> ExtractionRetryRunResult:
        tasks = self.task_repo.claim_due(user_id=user_id, limit=limit, now=now)
        result = ExtractionRetryRunResult(claimed=len(tasks))
        for task in tasks:
            try:
                self._execute(task)
            except ExtractionPermanentError as exc:
                self.task_repo.mark_dead(task.task_id, error_code=exc.code, now=now)
                result.dead_lettered += 1
            except Exception:
                updated = self.task_repo.mark_failed(
                    task.task_id,
                    error_code=f"extraction.{task.extractor_type.value}.failed",
                    now=now,
                )
                if updated.status == ExtractionTaskStatus.DEAD_LETTER:
                    result.dead_lettered += 1
                else:
                    result.retried += 1
            else:
                self.task_repo.mark_succeeded(task.task_id, now=now)
                result.succeeded += 1
        return result

    def _execute(self, task: ExtractionTask) -> None:
        if not self.executor.supports(task.extractor_type):
            raise ExtractionPermanentError("extraction.executor_unavailable")
        events = []
        for event_id in task.event_ids or [task.event_id]:
            event = self.event_repo.get_by_id(event_id)
            if event is None:
                raise ExtractionPermanentError("extraction.event_missing")
            if event.user_id != task.user_id:
                raise ExtractionPermanentError("extraction.owner_mismatch")
            events.append(event)
        if task.extractor_type == ExtractionType.PREFERENCE:
            if len(events) != 1:
                raise ExtractionPermanentError("extraction.invalid_event_set")
            self.executor.run_preference(events[0])
        elif task.extractor_type == ExtractionType.KNOWLEDGE:
            anchor = events[0]
            loader = getattr(self.event_repo, "get_trajectory", None)
            if loader is not None and anchor.session_id:
                events = loader(anchor.user_id, anchor.session_id, anchor.task_type)
                if not events:
                    raise ExtractionPermanentError("extraction.event_missing")
            self.executor.run_knowledge(events)
        elif task.extractor_type == ExtractionType.FACT:
            if len(events) != 1:
                raise ExtractionPermanentError("extraction.invalid_event_set")
            self.executor.run_fact(events[0])
        else:
            raise ExtractionPermanentError("extraction.unsupported_type")
