from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from memoryhub.adapter.schemas import (
    EventQuality,
    ExtractionTaskStatus,
    ExtractionType,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
    QualityStatus,
)
from memoryhub.core.ingestion.extraction import ExtractionExecutor
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.ingestion.service import EventIngestionService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "extraction-retry.db"))
    db.init_schema()
    return db


def _event(event_id: str, *, text: str = "raw secret", session_id: str = "s1") -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        source_type="user_behavior",
        event_type="preference_signal",
        user_id="u1",
        session_id=session_id,
        scene="office",
        task_type="office.report",
        occurred_at="2026-08-03T12:00:00Z",
        text=text,
        payload={"status": "SUCCESS"},
        source_hash=(event_id.encode("utf-8").hex() + "0" * 64)[:64],
        quality=EventQuality(
            score=0.9,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )


class _AcceptedQuality:
    def score(self, event):
        return event.quality


class _MaskingGate:
    def route(self, event):
        safe = event.model_copy(update={"text": f"safe:{event.event_id}"})
        return SimpleNamespace(approved=SimpleNamespace(safe_event=safe))


class _FlakyPreferenceExtractor:
    def __init__(self) -> None:
        self.fail = True
        self.calls = 0

    def extract(self, event):
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider response included sensitive prompt")
        return [PreferenceMemory(user_id=event.user_id, text="Prefer Markdown")]


class _FlakyKnowledgeExtractor:
    def __init__(self) -> None:
        self.fail = True
        self.seen_texts: list[list[str]] = []

    def extract_from_trajectory(self, events):
        self.seen_texts.append([event.text for event in events])
        if self.fail:
            raise RuntimeError("remote knowledge failure with secret")
        return [KnowledgeMemory(
            user_id=events[0].user_id,
            name="Safe workflow",
            content="Use the admitted event sequence",
        )]


def _service(
    *,
    db: Database,
    preference_extractor=None,
    knowledge_extractor=None,
):
    event_repo = EventRepository(db)
    task_repo = ExtractionTaskRepository(db)
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
    )
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=_MaskingGate(),
        quality_scorer=_AcceptedQuality(),
        memory_write_service=writer,
        preference_extractor=preference_extractor,
        knowledge_extractor=knowledge_extractor,
        extraction_task_repo=task_repo,
    )
    retry = ExtractionRetryService(
        task_repo=task_repo,
        event_repo=event_repo,
        executor=service.extraction_executor,
    )
    return service, retry, task_repo, event_repo, writer


def test_preference_failure_is_durable_and_retry_is_idempotent(tmp_path: Path) -> None:
    extractor = _FlakyPreferenceExtractor()
    service, retry, task_repo, event_repo, writer = _service(
        db=_db(tmp_path), preference_extractor=extractor
    )

    first = service.ingest([_event("evt-pref")])
    duplicate = service.ingest([_event("evt-pref")])

    assert first.accepted == 1
    assert first.extraction_failures == 1
    assert first.retry_tasks_enqueued == 1
    assert first.retry_queue_failures == 0
    assert duplicate.retry_tasks_enqueued == 0
    tasks = task_repo.list(user_id="u1")
    assert len(tasks) == 1
    assert tasks[0].extractor_type == ExtractionType.PREFERENCE
    assert tasks[0].last_error_code == "extraction.preference.failed"
    assert "sensitive" not in tasks[0].last_error_code
    assert event_repo.get_by_id("evt-pref").text == "safe:evt-pref"

    extractor.fail = False
    outcome = retry.run_due(user_id="u1")
    assert outcome.claimed == 1 and outcome.succeeded == 1
    task = task_repo.get(tasks[0].task_id, user_id="u1")
    assert task.status == ExtractionTaskStatus.SUCCEEDED
    memories = writer.pref_repo.list_all(user_id="u1")
    assert len(memories) == 1
    assert memories[0].memory_id.startswith("pref_")
    assert retry.run_due(user_id="u1").claimed == 0


def test_knowledge_retry_reloads_only_safe_persisted_trajectory(tmp_path: Path) -> None:
    extractor = _FlakyKnowledgeExtractor()
    service, retry, task_repo, _, writer = _service(
        db=_db(tmp_path), knowledge_extractor=extractor
    )
    events = [_event("evt-k1"), _event("evt-k2")]

    result = service.ingest(events)
    task = task_repo.list(user_id="u1")[0]
    assert result.retry_tasks_enqueued == 1
    assert task.extractor_type == ExtractionType.KNOWLEDGE
    assert task.event_ids == ["evt-k1", "evt-k2"]

    extractor.fail = False
    assert retry.run_due(user_id="u1").succeeded == 1
    assert extractor.seen_texts[-1] == ["safe:evt-k1", "safe:evt-k2"]
    assert len(writer.know_repo.list_all(user_id="u1")) == 1


def test_exponential_backoff_dead_letter_and_owner_isolation(tmp_path: Path) -> None:
    repo = ExtractionTaskRepository(_db(tmp_path))
    start = datetime(2026, 8, 3, 12, 0, 0)
    task, created = repo.enqueue(
        event_ids=["evt-dead"],
        user_id="u1",
        extractor_type=ExtractionType.FACT,
        max_attempts=2,
        now=start,
    )
    assert created is True
    assert repo.list(user_id="u2") == []
    assert repo.get(task.task_id, user_id="u2") is None

    first_claim = repo.claim_due(user_id="u1", now=start)
    assert first_claim[0].attempt_count == 1
    retry_task = repo.mark_failed(
        task.task_id,
        error_code="extraction.fact.failed",
        now=start,
        base_delay_seconds=10,
    )
    assert retry_task.status == ExtractionTaskStatus.RETRY
    assert retry_task.next_retry_at == start + timedelta(seconds=10)
    assert repo.claim_due(user_id="u1", now=start + timedelta(seconds=9)) == []

    second_claim = repo.claim_due(user_id="u1", now=start + timedelta(seconds=10))
    assert second_claim[0].attempt_count == 2
    dead = repo.mark_failed(
        task.task_id,
        error_code="extraction.fact.failed",
        now=start + timedelta(seconds=10),
        base_delay_seconds=10,
    )
    assert dead.status == ExtractionTaskStatus.DEAD_LETTER
    assert dead.next_retry_at is None
    assert repo.retry_dead(task.task_id, user_id="u2", now=start) is None
    reset = repo.retry_dead(task.task_id, user_id="u1", now=start)
    assert reset.status == ExtractionTaskStatus.RETRY
    assert reset.attempt_count == 0


def test_retry_dead_letters_missing_or_cross_owner_events_without_exposing_text(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    event_repo = EventRepository(db)
    task_repo = ExtractionTaskRepository(db)
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db), know_repo=KnowledgeRepository(db)
    )

    class _NoOpPref:
        def extract(self, event):
            return []

    executor = ExtractionExecutor(
        memory_write_service=writer,
        preference_extractor=_NoOpPref(),
    )
    retry = ExtractionRetryService(
        task_repo=task_repo, event_repo=event_repo, executor=executor
    )
    missing, _ = task_repo.enqueue(
        event_ids=["evt-missing"], user_id="u1", extractor_type=ExtractionType.PREFERENCE
    )

    outcome = retry.run_due(user_id="u1")
    task = task_repo.get(missing.task_id, user_id="u1")
    assert outcome.dead_lettered == 1
    assert task.status == ExtractionTaskStatus.DEAD_LETTER
    assert task.last_error_code == "extraction.event_missing"
    assert "secret" not in task.last_error_code


class _FailAfterFirstPersistWriter(MemoryWriteService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.fail_once = True

    def upsert_memory(self, memory, *args, **kwargs) -> None:
        super().upsert_memory(memory, *args, **kwargs)
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("index synchronization failed with sensitive detail")


def test_retry_repairs_partial_preference_write_without_duplicate(tmp_path: Path) -> None:
    db = _db(tmp_path)
    event_repo = EventRepository(db)
    task_repo = ExtractionTaskRepository(db)
    pref_repo = PreferenceRepository(db)
    writer = _FailAfterFirstPersistWriter(
        pref_repo=pref_repo,
        know_repo=KnowledgeRepository(db),
    )
    extractor = _FlakyPreferenceExtractor()
    extractor.fail = False
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=_MaskingGate(),
        quality_scorer=_AcceptedQuality(),
        memory_write_service=writer,
        preference_extractor=extractor,
        extraction_task_repo=task_repo,
    )
    retry = ExtractionRetryService(
        task_repo=task_repo,
        event_repo=event_repo,
        executor=service.extraction_executor,
    )

    result = service.ingest([_event("evt-partial-pref")])
    before = pref_repo.list_all(user_id="u1")
    assert result.extraction_failures == 1
    assert result.retry_tasks_enqueued == 1
    assert len(before) == 1

    outcome = retry.run_due(user_id="u1")
    after = pref_repo.list_all(user_id="u1")
    assert outcome.succeeded == 1
    assert len(after) == 1
    assert after[0].memory_id == before[0].memory_id
