from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from memoryhub.adapter.api import submit_feedback
from memoryhub.adapter.schemas import (
    EventQuality,
    Evidence,
    ExtractionType,
    FeedbackRequest,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryStatus,
    QualityStatus,
    ToolCallResult,
    ToolCallStatus,
)
from memoryhub.core.forget.auto_forget import AutoForgetEngine
from memoryhub.core.ingestion.service import EventIngestionService
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.evidence_store import EvidenceStore


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "knowledge-data-flow.db"))
    db.init_schema()
    return db


def _quality() -> EventQuality:
    return EventQuality(
        score=0.9,
        status=QualityStatus.ACCEPTED,
        completeness=1.0,
        validity=1.0,
        consistency=1.0,
        freshness=1.0,
    )


def _event(
    event_id: str,
    *,
    occurred_at: str,
    payload: dict,
    tool_name: str = "",
    session_id: str = "session-1",
) -> MemoryEvent:
    tool_calls = []
    source_type = "user_behavior"
    if tool_name:
        source_type = "tool_result"
        tool_calls = [
            ToolCallResult(
                call_id=f"call-{event_id}",
                tool_name=tool_name,
                arguments={},
                result={"ok": True},
                status=ToolCallStatus.SUCCESS,
                sequence=1,
            )
        ]
    return MemoryEvent(
        event_id=event_id,
        source_type=source_type,
        event_type="task_trajectory",
        user_id="user-1",
        session_id=session_id,
        turn_id=f"turn-{event_id}",
        scene="office",
        task_type="office.weekly_report",
        occurred_at=occurred_at,
        text=f"safe text {event_id}",
        payload=payload,
        tool_calls=tool_calls,
        source_hash=hashlib.sha256(event_id.encode()).hexdigest(),
        quality=_quality(),
    )


class _IdentityGate:
    def route(self, event):
        return SimpleNamespace(approved=SimpleNamespace(safe_event=event))


class _AcceptedQuality:
    def score(self, event):
        return event.quality


def _service(tmp_path: Path, extractor=None):
    db = _db(tmp_path)
    event_repo = EventRepository(db)
    task_repo = ExtractionTaskRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=know_repo,
    )
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=_IdentityGate(),
        quality_scorer=_AcceptedQuality(),
        memory_write_service=writer,
        knowledge_extractor=extractor or KnowledgeExtractor(),
        extraction_task_repo=task_repo,
    )
    return service, event_repo, task_repo, know_repo, writer


def test_ordinary_safe_event_is_not_promoted_to_knowledge() -> None:
    event = MemoryEvent(
        event_id="ordinary-1",
        source_type="user_behavior",
        event_type="user_note",
        user_id="user-1",
        occurred_at="2026-08-03T01:00:00Z",
        text="remember to buy coffee",
        payload={"note": "remember to buy coffee", "status": "success"},
        source_hash="a" * 64,
        quality=_quality(),
    )
    assert KnowledgeExtractor().extract_from_trajectory([event]) == []


def test_cross_request_trajectory_consolidates_and_keeps_tool_chain(tmp_path: Path) -> None:
    service, event_repo, _, know_repo, _ = _service(tmp_path)
    first = _event(
        "trajectory-1",
        occurred_at="2026-08-03T01:00:00Z",
        payload={
            "task_name": "Build weekly report",
            "steps": ["Collect data"],
            "status": "running",
        },
    )
    second = _event(
        "trajectory-2",
        occurred_at="2026-08-03T01:01:00Z",
        payload={"steps": ["Draft report"], "status": "success", "result": "Report completed"},
        tool_name="file_search",
    )
    third = _event(
        "trajectory-3",
        occurred_at="2026-08-03T01:02:00Z",
        payload={"steps": ["Draft report"], "status": "success", "result": "Report completed"},
        tool_name="document_writer",
    )

    assert service.ingest([first]).accepted == 1
    assert know_repo.list_all(user_id="user-1") == []
    assert service.ingest([second]).extraction_failures == 0
    memories = know_repo.list_all(user_id="user-1")
    assert {item.knowledge_type for item in memories} == {
        KnowledgeType.WORKFLOW,
        KnowledgeType.CASE,
        KnowledgeType.TEMPLATE,
    }
    assert all("file_search" in item.tools for item in memories)
    assert [
        e.event_id for e in event_repo.get_trajectory("user-1", "session-1", "office.weekly_report")
    ] == ["trajectory-1", "trajectory-2"]

    assert service.ingest([third]).extraction_failures == 0
    evolved = know_repo.list_all(user_id="user-1")
    assert len(evolved) == 3
    # The third event completes the same session trajectory: evolve the
    # knowledge version without counting another reuse.
    assert all(item.total_count == 1 for item in evolved)
    assert all(item.version == 2 for item in evolved)
    assert all("document_writer" in item.tools for item in evolved)
    assert all(
        {"trajectory-1", "trajectory-2", "trajectory-3"}.issubset(
            {e.event_id for e in item.evidences}
        )
        for item in evolved
    )


def test_updater_retry_is_idempotent_and_evidence_store_does_not_append_duplicates(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    evidence_store = EvidenceStore(str(tmp_path / "evidence"))
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
        evidence_store=evidence_store,
    )
    updater = KnowledgeUpdater(write_service=writer)
    memory = KnowledgeMemory(
        memory_id="know-stable",
        user_id="user-1",
        knowledge_type=KnowledgeType.WORKFLOW,
        name="Report workflow",
        content="Collect and write",
        steps=["Collect data", "Write report"],
        total_count=1,
        success_count=1,
        evidences=[Evidence(event_id="event-1", content="first run")],
    )
    updater.add(memory)
    updater.add(memory)
    stored = writer.know_repo.get_by_id(memory.memory_id)
    assert stored.total_count == 1
    assert len(evidence_store.load(memory.memory_id)) == 1

    evolved = memory.model_copy(deep=True)
    evolved.evidences.append(Evidence(event_id="event-2", content="second run"))
    updater.add(evolved)
    updater.add(evolved)
    stored = writer.know_repo.get_by_id(memory.memory_id)
    assert stored.total_count == 1
    assert stored.version == 2
    assert {e.event_id for e in evidence_store.load(memory.memory_id)} == {"event-1", "event-2"}


def test_disjoint_trajectory_evidence_increments_support_once(tmp_path: Path) -> None:
    db = _db(tmp_path)
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
    )
    updater = KnowledgeUpdater(write_service=writer)
    first = KnowledgeMemory(
        user_id="user-1",
        knowledge_type=KnowledgeType.WORKFLOW,
        name="Report workflow",
        content="Collect and write",
        steps=["Collect data", "Write report"],
        total_count=1,
        success_count=1,
        evidences=[Evidence(event_id="session-one", content="first execution")],
    )
    second = first.model_copy(deep=True)
    second.memory_id = "know_second_observation"
    second.evidences = [Evidence(event_id="session-two", content="independent execution")]

    updater.add(first)
    updater.add(second)
    stored = writer.know_repo.list_all(user_id="user-1")
    assert len(stored) == 1
    assert stored[0].total_count == 2
    assert stored[0].success_count == 2
    assert stored[0].version == 2


def test_scope_and_owner_filters_are_optional_but_safe(tmp_path: Path) -> None:
    repo = KnowledgeRepository(_db(tmp_path))
    repo.save(
        KnowledgeMemory(
            memory_id="know-u1",
            user_id="user-1",
            name="Shared report workflow",
            content="u1",
            scope={"scene": "office", "task_type": "office.report"},
        )
    )
    repo.save(
        KnowledgeMemory(
            memory_id="know-u2",
            user_id="user-2",
            name="Shared report workflow",
            content="u2",
            scope={"scene": "office", "task_type": "office.report"},
        )
    )
    assert [m.memory_id for m in repo.get_by_scope("user-1", "office", "")] == ["know-u1"]
    assert [m.memory_id for m in repo.search_by_name("report", user_id="user-2")] == ["know-u2"]
    repo.increment_usage("know-u1", True, user_id="user-2")
    assert repo.get_by_id("know-u1").total_count == 0
    repo.increment_usage("know-u1", True, user_id="user-1")
    assert repo.get_by_id("know-u1").total_count == 1


class _FailingLLM:
    def is_available(self):
        return True

    def generate(self, **kwargs):
        raise RuntimeError("provider unavailable")

    def generate_json(self, **kwargs):
        raise RuntimeError("provider unavailable")


def test_required_llm_failure_enters_existing_retry_queue(tmp_path: Path) -> None:
    service, _, task_repo, _, _ = _service(tmp_path, KnowledgeExtractor(llm_client=_FailingLLM()))
    event = _event(
        "llm-required",
        occurred_at="2026-08-03T02:00:00Z",
        payload={
            "task_name": "Sparse task",
            "steps": ["Only structured step"],
            "status": "success",
            "result": "Completed",
        },
    )
    result = service.ingest([event])
    assert result.accepted == 1
    assert result.extraction_failures == 1
    assert result.retry_tasks_enqueued == 1
    tasks = task_repo.list(user_id="user-1")
    assert len(tasks) == 1
    assert tasks[0].extractor_type == ExtractionType.KNOWLEDGE
    assert tasks[0].event_ids == ["llm-required"]


def test_index_text_and_lifecycle_archive_cover_all_knowledge_fields(tmp_path: Path) -> None:
    db = _db(tmp_path)
    know_repo = KnowledgeRepository(db)
    keyword = KeywordSearcher()
    lookup = {}
    evidence_store = EvidenceStore(str(tmp_path / "lifecycle-evidence"))
    writer = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=know_repo,
        keyword_search=keyword,
        memory_lookup=lookup,
        evidence_store=evidence_store,
    )
    know_repo.write_service = writer
    memory = KnowledgeMemory(
        memory_id="know-index",
        user_id="user-1",
        name="Weekly report",
        content="Reusable process",
        steps=["collect_metrics"],
        tools=["file_search"],
        template_body="template_marker",
        evidences=[Evidence(event_id="index-event", content="proof")],
    )
    text = writer.index_text(memory)
    assert all(
        value in text
        for value in (
            "Weekly report",
            "Reusable process",
            "collect_metrics",
            "file_search",
            "template_marker",
        )
    )
    writer.upsert_memory(memory)
    assert keyword.search("template_marker", top_k=5)[0].memory_id == memory.memory_id

    AutoForgetEngine(know_repo=know_repo)._update_status(memory, MemoryStatus.ARCHIVED, 0.1)
    assert know_repo.get_by_id(memory.memory_id).status == MemoryStatus.ARCHIVED
    assert memory.memory_id not in lookup
    assert keyword.search("template_marker", top_k=5) == []
    assert evidence_store.load(memory.memory_id)


def test_feedback_keeps_contract_and_updates_knowledge_metrics(tmp_path: Path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(pref_repo=pref_repo, know_repo=know_repo)
    memory = KnowledgeMemory(
        memory_id="know-feedback",
        user_id="user-1",
        name="Workflow",
        content="Old",
    )
    writer.upsert_memory(memory)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                pref_repo=pref_repo,
                know_repo=know_repo,
                memory_write_service=writer,
            )
        )
    )
    response = asyncio.run(
        submit_feedback(
            FeedbackRequest(user_id="user-1", memory_id=memory.memory_id, action="confirm"),
            request,
        )
    )
    assert response == {"status": "ok", "action": "confirm"}
    confirmed = know_repo.get_by_id(memory.memory_id)
    assert (confirmed.total_count, confirmed.success_count) == (1, 1)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            submit_feedback(
                FeedbackRequest(user_id="user-2", memory_id=memory.memory_id, action="reject"),
                request,
            )
        )
    assert exc.value.status_code == 404
