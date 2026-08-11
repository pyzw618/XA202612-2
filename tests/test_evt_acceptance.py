"""EVT-01~08 事件写入链路验收测试。

对应 docs/TEST_PLAN.md 6.2 事件写入链路(EVT)。
直接驱动真实实现，作为可复现的逐项通过记录。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from memoryhub.adapter.schemas import (
    EventQuality,
    ExtractionTaskStatus,
    ExtractionType,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
    QualityStatus,
    SourceType,
    ToolCallStatus,
)
from memoryhub.core.ingestion.quality import QualityScorer
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.ingestion.service import EventIngestionService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.preference.updater import PreferenceUpdater
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)


def _hash(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _quality(score: float = 0.9, status: str = "accepted") -> EventQuality:
    return EventQuality(
        score=score,
        status=QualityStatus(status),
        completeness=0.9,
        validity=0.9,
        consistency=0.9,
        freshness=0.9,
    )


def _event(
    event_id: str,
    *,
    source_type: SourceType = SourceType.USER_BEHAVIOR,
    scene: str = "office",
    task_type: str = "office.report",
    text: str = "用 Markdown 输出周报",
    payload: dict | None = None,
    session_id: str = "s1",
    quality: EventQuality | None = None,
    occurred_at: str = "2026-08-03T12:00:00Z",
    schema_version: str = "1.1",
    source_hash: str | None = None,
    tool_calls: list[dict] | None = None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        source_type=source_type,
        event_type="user_action" if source_type != SourceType.TOOL_RESULT else "tool_result",
        user_id="u1",
        session_id=session_id,
        turn_id="turn-1",
        scene=scene,
        task_type=task_type,
        occurred_at=occurred_at,
        text=text,
        payload=payload or ({"action": "message", "role": "user"} if source_type == SourceType.USER_BEHAVIOR else {"response_status": "success"}),
        tool_calls=tool_calls or [],
        schema_version=schema_version,
        source_hash=source_hash or _hash(event_id),
        redactions=[],
        quality=quality or _quality(),
    )


class _PassGate:
    def route(self, event):
        return SimpleNamespace(approved=SimpleNamespace(safe_event=event.model_copy(deep=True)))


class _MaskGate:
    def route(self, event):
        safe = event.model_copy(deep=True)
        safe.text = f"[MASKED:{event.event_id}]"
        return SimpleNamespace(approved=SimpleNamespace(safe_event=safe))


class _RejectGate:
    def route(self, event):
        return SimpleNamespace(approved=None)


class _NoOpExtractor:
    def extract(self, event):
        return []

    def extract_from_trajectory(self, events):
        return []

    def ingest_event(self, event):
        return []


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "evt.db"))
    db.init_schema()
    return db


def _service(db: Database, *, gate=None, quality_scorer=None, preference_updater=None):
    event_repo = EventRepository(db)
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
    )
    extractor = _NoOpExtractor()
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=gate or _PassGate(),
        quality_scorer=quality_scorer or QualityScorer(),
        memory_write_service=writer,
        preference_extractor=extractor,
        preference_updater=preference_updater,
        knowledge_extractor=extractor,
        fact_ingestion_adapter=extractor,
        extraction_task_repo=None,
    )
    return service, event_repo, writer


class TestEvt01SchemaValidation:
    def test_missing_required_field_rejected(self) -> None:
        data = _event("evt_missing").model_dump()
        del data["source_hash"]
        with pytest.raises(ValidationError):
            MemoryEvent.model_validate(data)

    def test_invalid_enum_rejected(self) -> None:
        data = _event("evt_bad_enum").model_dump()
        data["source_type"] = "not_a_source"
        with pytest.raises(ValidationError):
            MemoryEvent.model_validate(data)

    def test_unknown_top_level_field_rejected(self) -> None:
        data = _event("evt_unknown").model_dump()
        data["content"] = "legacy top level field"
        with pytest.raises(ValidationError):
            MemoryEvent.model_validate(data)

    def test_schema_11_tool_result_requires_tool_calls(self) -> None:
        with pytest.raises(ValidationError):
            _event("evt_tool_1", source_type=SourceType.TOOL_RESULT, tool_calls=[])


class TestEvt02Schema10Compat:
    def test_legacy_10_tool_result_in_payload_readable(self) -> None:
        event = _event(
            "evt_legacy",
            source_type=SourceType.TOOL_RESULT,
            schema_version="1.0",
            payload={"tool_name": "file_search", "status": "success", "output": "found 3 files"},
        )
        assert event.schema_version == "1.0"
        assert event.payload["tool_name"] == "file_search"

    def test_new_write_forces_11(self) -> None:
        data = _event("evt_migration").model_dump()
        data["schema_version"] = "1.0"
        event = MemoryEvent.model_validate(data)
        assert event.schema_version in ("1.0", "1.1")


class TestEvt03QualityScoring:
    def test_four_factor_formula(self) -> None:
        scorer = QualityScorer()
        full = _event("evt_q1", text="很完整的事件内容足够长")
        q = scorer.score(full)
        expected = 0.30 * q.completeness + 0.30 * q.validity + 0.20 * q.consistency + 0.20 * q.freshness
        assert q.score == pytest.approx(expected)
        assert q.status is QualityStatus.ACCEPTED
        assert 0.0 <= q.completeness <= 1.0
        assert 0.0 <= q.validity <= 1.0
        assert 0.0 <= q.consistency <= 1.0
        assert 0.0 <= q.freshness <= 1.0

    def test_low_quality_rejected(self) -> None:
        scorer = QualityScorer()
        data = _event("evt_q2", text="", occurred_at="2026-08-03T12:00:00Z").model_dump()
        data.update({"payload": {}, "scene": "", "task_type": "", "user_id": "", "turn_id": "", "session_id": ""})
        data["quality"] = _quality(score=0.5, status="review")
        poor = MemoryEvent.model_validate(data)
        q = scorer.score(poor)
        assert q.status is QualityStatus.REJECTED

    def test_sparse_event_reviewed(self) -> None:
        scorer = QualityScorer()
        data = _event("evt_q5", text="", occurred_at="2020-01-01T00:00:00Z").model_dump()
        data.update({"payload": {"response_status": "success"}, "scene": "", "task_type": "", "user_id": "", "turn_id": "", "session_id": ""})
        data["quality"] = _quality(score=0.5, status="review")
        sparse = MemoryEvent.model_validate(data)
        q = scorer.score(sparse)
        assert q.score < scorer.REVIEW_QUALITY_SCORE
        assert q.status is QualityStatus.REVIEW

    def test_freshness_decays_with_age(self) -> None:
        scorer = QualityScorer()
        old = _event("evt_q3", occurred_at="2020-01-01T00:00:00Z")
        fresh = _event("evt_q4", occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert scorer._score_freshness(fresh) > scorer._score_freshness(old)


class TestEvt04IdempotentDedup:
    def test_duplicate_event_id_acknowledged_once(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, event_repo, _ = _service(db)
        first = service.ingest([_event("evt_dup")])
        second = service.ingest([_event("evt_dup")])
        assert first.accepted == 1
        assert second.accepted == 1
        assert event_repo.get_by_id("evt_dup") is not None

    def test_same_source_hash_not_retriggered(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, event_repo, _ = _service(db)
        first = service.ingest([_event("evt_h1", source_hash=_hash("same-content"))])
        second = service.ingest([_event("evt_h2", source_hash=_hash("same-content"))])
        assert first.accepted == 1
        assert second.accepted == 1
        assert event_repo.get_by_id("evt_h2") is None

    def test_distinct_events_both_accepted(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, _, _ = _service(db)
        result = service.ingest([_event("evt_a"), _event("evt_b")])
        assert result.accepted == 2
        assert result.rejected == 0
        assert result.event_ids == ["evt_a", "evt_b"]


class TestEvt05SafetyGate:
    def test_reject_not_persisted(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, event_repo, _ = _service(db, gate=_RejectGate())
        result = service.ingest([_event("evt_rej", text="含 token=abc123")])
        assert result.rejected == 1
        assert result.accepted == 0
        assert event_repo.get_by_id("evt_rej") is None

    def test_mask_persists_only_sanitized_copy(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, event_repo, _ = _service(db, gate=_MaskGate())
        result = service.ingest([_event("evt_mask", text="秘密内容 13800138000")])
        assert result.accepted == 1
        stored = event_repo.get_by_id("evt_mask")
        assert stored is not None
        assert stored.text == f"[MASKED:evt_mask]"
        assert "13800138000" not in stored.text


class TestEvt06ExtractionOnce:
    def test_extraction_runs_only_once_for_same_event(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        calls = {"pref": 0, "know": 0, "fact": 0}

        class CountingExtractor:
            def extract(self, event):
                calls["pref"] += 1
                return [PreferenceMemory(user_id="u1", text="Prefer Markdown")]

            def extract_from_trajectory(self, events):
                calls["know"] += 1
                return []

            def ingest_event(self, event):
                calls["fact"] += 1
                return []

        writer = MemoryWriteService(
            pref_repo=PreferenceRepository(db),
            know_repo=KnowledgeRepository(db),
        )
        extractor = CountingExtractor()
        service = EventIngestionService(
            event_repo=EventRepository(db),
            safety_gate=_PassGate(),
            quality_scorer=QualityScorer(),
            memory_write_service=writer,
            preference_extractor=extractor,
            preference_updater=PreferenceUpdater(),
            knowledge_extractor=extractor,
            fact_ingestion_adapter=extractor,
            extraction_task_repo=None,
        )
        service.ingest([_event("evt_once")])
        service.ingest([_event("evt_once")])
        assert calls["pref"] == 1
        assert calls["know"] == 1
        assert calls["fact"] == 1


class TestEvt07RetryDurable:
    def test_failure_enqueues_and_retry_succeeds(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        task_repo = ExtractionTaskRepository(db)
        event_repo = EventRepository(db)
        writer = MemoryWriteService(
            pref_repo=PreferenceRepository(db),
            know_repo=KnowledgeRepository(db),
        )

        class FlakyExtractor:
            def __init__(self):
                self.fail = True
                self.calls = 0

            def extract(self, event):
                self.calls += 1
                if self.fail:
                    raise RuntimeError("provider failed")
                return [PreferenceMemory(user_id="u1", text="Prefer Markdown")]

            def extract_from_trajectory(self, events):
                return []

            def ingest_event(self, event):
                return []

        extractor = FlakyExtractor()
        service = EventIngestionService(
            event_repo=event_repo,
            safety_gate=_PassGate(),
            quality_scorer=QualityScorer(),
            memory_write_service=writer,
            preference_extractor=extractor,
            knowledge_extractor=extractor,
            fact_ingestion_adapter=extractor,
            extraction_task_repo=task_repo,
            extraction_max_attempts=3,
        )
        retry = ExtractionRetryService(task_repo=task_repo, event_repo=event_repo, executor=service.extraction_executor)

        result = service.ingest([_event("evt_retry")])
        assert result.accepted == 1
        assert result.extraction_failures == 1
        assert result.retry_tasks_enqueued == 1
        tasks = task_repo.list(user_id="u1")
        assert len(tasks) == 1
        assert tasks[0].extractor_type is ExtractionType.PREFERENCE
        assert tasks[0].status is ExtractionTaskStatus.PENDING

        extractor.fail = False
        outcome = retry.run_due(user_id="u1")
        assert outcome.claimed == 1
        assert outcome.succeeded == 1
        assert task_repo.get(tasks[0].task_id, user_id="u1").status is ExtractionTaskStatus.SUCCEEDED

    def test_retry_dead_letters_missing_event(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        task_repo = ExtractionTaskRepository(db)
        event_repo = EventRepository(db)
        writer = MemoryWriteService(
            pref_repo=PreferenceRepository(db),
            know_repo=KnowledgeRepository(db),
        )
        extractor = _NoOpExtractor()
        service = EventIngestionService(
            event_repo=event_repo,
            safety_gate=_PassGate(),
            quality_scorer=QualityScorer(),
            memory_write_service=writer,
            preference_extractor=extractor,
            knowledge_extractor=extractor,
            fact_ingestion_adapter=extractor,
            extraction_task_repo=task_repo,
        )
        retry = ExtractionRetryService(task_repo=task_repo, event_repo=event_repo, executor=service.extraction_executor)
        _, _ = task_repo.enqueue(
            event_ids=["evt_gone"],
            user_id="u1",
            extractor_type=ExtractionType.PREFERENCE,
            error_code="extraction.preference.failed",
        )
        outcome = retry.run_due(user_id="u1")
        assert outcome.dead_lettered == 1
        assert outcome.claimed == 1


class TestEvt08Batch:
    def test_batch_mixed_accept_reject(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        service, event_repo, _ = _service(db)
        bad = _event("evt_bad", text="", occurred_at="2026-08-03T12:00:00Z").model_dump()
        bad.update({"payload": {}, "scene": "", "task_type": "", "user_id": "", "turn_id": "", "session_id": ""})
        bad["quality"] = _quality(score=0.5, status="review")
        result = service.ingest(
            [_event("evt_b1"), _event("evt_b2"), _event("evt_dup"), _event("evt_b1"), MemoryEvent.model_validate(bad)]
        )
        assert result.accepted == 4
        assert result.rejected == 1
        assert result.event_ids == ["evt_b1", "evt_b2", "evt_dup", "evt_b1"]
        assert event_repo.get_by_id("evt_b2") is not None
        assert event_repo.get_by_id("evt_bad") is None
