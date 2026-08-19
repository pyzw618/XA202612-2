from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from memoryhub.adapter.api import (
    _record_search_access,
    get_preference,
    submit_feedback,
)
from memoryhub.adapter.schemas import (
    ConflictDecision,
    ConflictRecord,
    EventQuality,
    Evidence,
    FeedbackRequest,
    ForgetRequest,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    SearchRequest,
    ToolCallResult,
    ToolCallStatus,
)
from memoryhub.core.forget.auto_forget import AutoForgetEngine
from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.core.ingestion.normalizer import EventNormalizer
from memoryhub.core.ingestion.service import EventIngestionService
from memoryhub.core.lifecycle.manager import LifecycleManager
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.updater import ConflictDetector, PreferenceUpdater
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.detector import SensitiveDetector
from memoryhub.core.safety.gate import SafetyWriteGate
from memoryhub.core.safety.quarantine import ReviewQuarantineStore
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.storage.database import (
    ConflictRepository,
    Database,
    EventRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.evidence_store import EvidenceStore


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "data-flow.db"))
    db.init_schema()
    return db


def _safety_gate(tmp_path: Path) -> SafetyWriteGate:
    """Use the real mandatory write gate for direct API mutation tests."""
    return SafetyWriteGate(
        SensitiveDetector(),
        SafetyAuditLog(tmp_path / "safety-audit", fingerprint_key=b"a" * 32),
        quarantine=ReviewQuarantineStore(
            tmp_path / "review-quarantine",
            encryption_key=b"q" * 32,
        ),
    )


def test_event_repository_round_trips_schema_11(tmp_path: Path) -> None:
    event = MemoryEvent(
        event_id="evt_roundtrip",
        source_type="tool_result",
        event_type="agent_response",
        user_id="u1",
        session_id="s1",
        turn_id="t1",
        occurred_at="2026-08-03T09:00:00Z",
        text="done",
        tool_calls=[
            ToolCallResult(
                call_id="c1",
                sequence=1,
                tool_name="writer",
                status=ToolCallStatus.SUCCESS,
                arguments={"format": "md"},
                result={"ok": True},
            )
        ],
        schema_version="1.1",
        source_hash="a" * 64,
        redactions=["/payload/token"],
        quality=EventQuality(
            score=0.9,
            status=QualityStatus.ACCEPTED,
            completeness=1,
            validity=1,
            consistency=1,
            freshness=1,
        ),
    )
    repo = EventRepository(_db(tmp_path))
    repo.save(event)
    assert repo.get_by_id(event.event_id) == event


def test_hybrid_retrieval_isolates_users() -> None:
    memory = PreferenceMemory(memory_id="pref_u1", user_id="u1", text="secretblue")
    keyword = KeywordSearcher()
    keyword.build_index(
        [
            (
                memory.memory_id,
                memory.text,
                '{"memory_type":"preference","user_id":"u1","content":"secretblue","confidence":1.0,"scope":{}}',
            )
        ]
    )
    retriever = HybridRetriever(
        keyword_search=keyword, memory_lookup={memory.memory_id: memory}
    )
    assert (
        retriever.search(SearchRequest(user_id="u2", query="secretblue")).results == []
    )


def test_forget_enforces_owner_and_reports_actual_count(tmp_path: Path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    pref_repo.save(PreferenceMemory(memory_id="pref_owned", user_id="u1", text="x"))
    forgetter = MemoryForgetter(pref_repo=pref_repo, know_repo=KnowledgeRepository(db))
    assert forgetter.delete_memories(["pref_owned"], user_id="u2") == 0
    assert forgetter.delete_memories(["missing"], user_id="u1") == 0
    assert forgetter.delete_memories(["pref_owned"], user_id="u1") == 1


class _RecordingRepo:
    def __init__(self):
        self.saved = []

    def save(self, memory):
        self.saved.append(memory)


class _FakeVectorStore:
    def __init__(self):
        self.updated = []
        self.deleted = []
        self.save_count = 0

    def update(self, memory_id, vector):
        self.updated.append((memory_id, vector))

    def delete(self, memory_id):
        self.deleted.append(memory_id)
        return True

    def save(self):
        self.save_count += 1


class _FakeEmbedding:
    def embed(self, text):
        return [float(len(text))]


class _FakeCache:
    def __init__(self):
        self.clear_count = 0

    def clear(self):
        self.clear_count += 1


def _request_with_state(**values):
    defaults = {
        "vector_store": None,
        "vector_engine": None,
        "keyword_search": None,
        "memory_lookup": {},
        "search_cache": None,
        "embedding_client": None,
    }
    defaults.update(values)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(**defaults)))


def test_feedback_update_synchronizes_all_runtime_indexes(tmp_path: Path) -> None:
    repo = PreferenceRepository(_db(tmp_path))
    memory = PreferenceMemory(memory_id="pref_sync", user_id="u1", text="old text")
    repo.save(memory)
    keyword = KeywordSearcher()
    keyword.build_index([(memory.memory_id, memory.text, "{}")])
    vector = _FakeVectorStore()
    cache = _FakeCache()
    lookup = {memory.memory_id: memory}
    request = _request_with_state(
        pref_repo=repo,
        vector_store=vector,
        keyword_search=keyword,
        memory_lookup=lookup,
        search_cache=cache,
        embedding_client=_FakeEmbedding(),
        safety_gate=_safety_gate(tmp_path),
    )

    result = asyncio.run(
        submit_feedback(
            FeedbackRequest(
                user_id="u1",
                memory_id=memory.memory_id,
                feedback_text="new searchable wording",
                action="update",
            ),
            request,
        )
    )

    assert result["status"] == "ok"
    assert repo.get_by_id(memory.memory_id).text == "new searchable wording"
    assert vector.updated[0][0] == memory.memory_id
    assert vector.save_count == 1
    assert keyword.search("searchable", top_k=5)[0].memory_id == memory.memory_id
    assert lookup[memory.memory_id].text == "new searchable wording"
    assert cache.clear_count == 1


def test_feedback_reject_removes_indexes_and_enforces_owner(tmp_path: Path) -> None:
    repo = PreferenceRepository(_db(tmp_path))
    memory = PreferenceMemory(memory_id="pref_reject", user_id="u1", text="private")
    repo.save(memory)
    keyword = KeywordSearcher()
    keyword.build_index([(memory.memory_id, memory.text, "{}")])
    vector = _FakeVectorStore()
    lookup = {memory.memory_id: memory}
    request = _request_with_state(
        pref_repo=repo,
        vector_store=vector,
        keyword_search=keyword,
        memory_lookup=lookup,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            submit_feedback(
                FeedbackRequest(
                    user_id="u2", memory_id=memory.memory_id, action="reject"
                ),
                request,
            )
        )
    assert exc.value.status_code == 404

    asyncio.run(
        submit_feedback(
            FeedbackRequest(user_id="u1", memory_id=memory.memory_id, action="reject"),
            request,
        )
    )
    assert vector.deleted == [memory.memory_id]
    assert keyword.search("private", top_k=5) == []
    assert memory.memory_id not in lookup


def test_conflict_repository_resolve_reports_truth_and_result_id(
    tmp_path: Path,
) -> None:
    repo = ConflictRepository(_db(tmp_path))
    record = ConflictRecord(
        conflict_id="conf_data_flow",
        old_memory_id="old",
        new_memory_id="new",
        memory_type="preference",
        decision=ConflictDecision.PENDING,
    )
    repo.save(record)

    assert repo.resolve(record.conflict_id, "override", "confirmed", "result-1") is True
    resolved = repo.list_all("override")
    assert len(resolved) == 1
    assert resolved[0].result_memory_id == "result-1"
    assert resolved[0].resolved_at is not None
    assert repo.resolve("missing", "override", "", "") is False


def test_lifecycle_and_auto_forget_use_the_correct_repository() -> None:
    pref_repo = _RecordingRepo()
    know_repo = _RecordingRepo()
    pref = PreferenceMemory(memory_id="pref_life", user_id="u1", text="x")
    know = KnowledgeMemory(memory_id="know_life", user_id="u1", name="n", content="c")
    manager = LifecycleManager(pref_repo=pref_repo, know_repo=know_repo)

    manager._save(pref)
    manager._save(know)
    assert pref_repo.saved == [pref]
    assert know_repo.saved == [know]

    engine = AutoForgetEngine(pref_repo=pref_repo, know_repo=know_repo)
    engine._update_level(know, MemoryLevel.SHORT, 0.3)
    assert know.level == MemoryLevel.SHORT
    assert know_repo.saved[-1] is know
    assert pref_repo.saved == [pref]


class _FakeLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def generate(self, prompt, system_prompt="", **kwargs):
        self.calls.append((prompt, system_prompt))
        return SimpleNamespace(content=self.content)


def test_preference_llm_callers_use_prompt_and_response_content() -> None:
    detector_llm = _FakeLLM('{"conflict": true}')
    detector = ConflictDetector(detector_llm)
    old = PreferenceMemory(memory_id="old", user_id="u1", text="prefer concise")
    new = PreferenceMemory(memory_id="new", user_id="u1", text="prefer detailed")
    assert detector._is_semantic_conflict(old, new) is True
    assert detector_llm.calls[0][0].startswith("Compare these two")
    assert detector_llm.calls[0][1] == "You are a semantic evaluator."

    extractor_llm = _FakeLLM(
        '{"implicit_pref":"Prefer concise technical summaries",'
        '"preference_type":"output_style","action_payload":{},"tags":["concise"]}'
    )
    event = MemoryEvent(
        event_id="evt_llm",
        source_type="user_behavior",
        event_type="response",
        user_id="u1",
        text="The user repeatedly accepts concise answers.",
        occurred_at="2026-08-03T10:00:00Z",
        payload={"status": "SUCCESS"},
        source_hash="b" * 64,
        quality=EventQuality(
            score=0.9,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )
    extracted = PreferenceExtractor(extractor_llm)._llm_extract(event)
    assert extracted[0].text == "Prefer concise technical summaries"
    assert "Execution Context" in extractor_llm.calls[0][0]
    assert extractor_llm.calls[0][1].startswith(
        "You are a Preference Abstraction Engine"
    )


class _FakeVectorEngine:
    def __init__(self):
        self.deleted = []
        self.persist_count = 0

    def delete(self, memory_id):
        self.deleted.append(memory_id)

    def persist(self):
        self.persist_count += 1


def test_forget_reports_actual_ids_and_persists_vector_engine(tmp_path: Path) -> None:
    db = _db(tmp_path)
    repo = PreferenceRepository(db)
    repo.save(PreferenceMemory(memory_id="other_first", user_id="u2", text="x"))
    repo.save(PreferenceMemory(memory_id="owned_second", user_id="u1", text="y"))
    engine = _FakeVectorEngine()
    forgetter = MemoryForgetter(
        pref_repo=repo,
        know_repo=KnowledgeRepository(db),
        vector_engine=engine,
    )

    response = forgetter.execute(
        ForgetRequest(user_id="u1", target_memory_ids=["other_first", "owned_second"])
    )

    assert response.deleted_count == 1
    assert response.deleted_ids == ["owned_second"]
    assert engine.deleted == ["owned_second"]
    assert engine.persist_count == 1


def test_preference_detail_read_enforces_user_boundary(tmp_path: Path) -> None:
    repo = PreferenceRepository(_db(tmp_path))
    repo.save(PreferenceMemory(memory_id="pref_detail", user_id="u1", text="private"))
    request = _request_with_state(pref_repo=repo)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_preference("pref_detail", request, user_id="u2"))
    assert exc.value.status_code == 404
    assert (
        asyncio.run(get_preference("pref_detail", request, user_id="u1")).text
        == "private"
    )


class _FixedQualityScorer:
    def __init__(self, status: QualityStatus):
        self.status = status

    def score(self, _event):
        accepted = self.status == QualityStatus.ACCEPTED
        return EventQuality(
            score=0.9 if accepted else 0.1,
            status=self.status,
            completeness=1.0 if accepted else 0.0,
            validity=1.0 if accepted else 0.0,
            consistency=1.0 if accepted else 0.0,
            freshness=1.0 if accepted else 0.0,
        )


class _FakeGate:
    def __init__(self, *, approved=True, masked_text=None):
        self.approved = approved
        self.masked_text = masked_text
        self.calls = 0

    def route(self, event):
        self.calls += 1
        if not self.approved:
            return SimpleNamespace(approved=None)
        safe_event = event
        if self.masked_text is not None:
            safe_event = event.model_copy(update={"text": self.masked_text})
        return SimpleNamespace(approved=SimpleNamespace(safe_event=safe_event))


class _RecordingPreferenceExtractor:
    def __init__(self):
        self.calls = 0

    def extract(self, event):
        self.calls += 1
        return [
            PreferenceMemory(
                memory_id="pref_ingested",
                user_id=event.user_id,
                text="Prefer Markdown",
                confidence=0.9,
            )
        ]


class _RecordingKnowledgeExtractor:
    def __init__(self):
        self.calls = 0

    def extract_from_trajectory(self, events):
        self.calls += 1
        return [
            KnowledgeMemory(
                memory_id="know_ingested",
                user_id=events[0].user_id,
                name="Workflow",
                content="Do the steps",
                confidence=0.8,
            )
        ]


def _ingestion_event(event_id="evt_ingest", source_hash="c" * 64):
    return MemoryEvent(
        event_id=event_id,
        source_type="user_behavior",
        event_type="preference_signal",
        user_id="u1",
        session_id="s1",
        scene="office",
        task_type="office.report",
        occurred_at="2026-08-03T12:00:00Z",
        text="Always use markdown",
        payload={"status": "SUCCESS"},
        source_hash=source_hash,
        quality=EventQuality(
            score=0.9,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )


def test_event_ingestion_applies_gate_extracts_and_is_idempotent(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    event_repo = EventRepository(db)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    writer = MemoryWriteService(pref_repo=pref_repo, know_repo=know_repo)
    gate = _FakeGate(masked_text="[MASKED]")
    pref_extractor = _RecordingPreferenceExtractor()
    know_extractor = _RecordingKnowledgeExtractor()
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=gate,
        quality_scorer=_FixedQualityScorer(QualityStatus.ACCEPTED),
        memory_write_service=writer,
        preference_extractor=pref_extractor,
        knowledge_extractor=know_extractor,
    )

    first = service.ingest([_ingestion_event()])
    duplicate = service.ingest([_ingestion_event()])
    collision = service.ingest([_ingestion_event(source_hash="d" * 64)])

    assert first.accepted == 1 and first.rejected == 0
    assert event_repo.get_by_id("evt_ingest").text == "[MASKED]"
    assert pref_repo.get_by_id("pref_ingested") is not None
    assert know_repo.get_by_id("know_ingested") is not None
    assert duplicate.accepted == 1 and duplicate.rejected == 0
    assert collision.accepted == 0 and collision.rejected == 1
    assert gate.calls == 1
    assert pref_extractor.calls == 1
    assert know_extractor.calls == 1


def test_event_ingestion_rejects_quality_and_review_without_storage(
    tmp_path: Path,
) -> None:
    event_repo = EventRepository(_db(tmp_path))
    writer = SimpleNamespace(upsert_memory=lambda _memory: None)
    quality_gate = _FakeGate()
    low_quality = EventIngestionService(
        event_repo=event_repo,
        safety_gate=quality_gate,
        quality_scorer=_FixedQualityScorer(QualityStatus.REJECTED),
        memory_write_service=writer,
    )
    reviewed = EventIngestionService(
        event_repo=event_repo,
        safety_gate=_FakeGate(approved=False),
        quality_scorer=_FixedQualityScorer(QualityStatus.ACCEPTED),
        memory_write_service=writer,
    )

    assert low_quality.ingest([_ingestion_event("evt_low")]).rejected == 1
    assert quality_gate.calls == 0
    assert reviewed.ingest([_ingestion_event("evt_review")]).rejected == 1
    assert event_repo.get_by_id("evt_low") is None
    assert event_repo.get_by_id("evt_review") is None


def test_retrieval_access_stats_round_trip_with_owner_boundary(tmp_path: Path) -> None:
    repo = PreferenceRepository(_db(tmp_path))
    repo.save(PreferenceMemory(memory_id="pref_access", user_id="u1", text="x"))

    assert repo.record_access("pref_access", user_id="u2") is False
    assert repo.record_access("pref_access", user_id="u1") is True
    loaded = repo.get_by_id("pref_access")
    assert loaded.access_count_30d == 1
    assert loaded.last_accessed_at is not None


def test_forget_cascades_evidence_and_conflicts(tmp_path: Path) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    conflict_repo = ConflictRepository(db)
    evidence_store = EvidenceStore(str(tmp_path / "evidence"))
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        evidence_store=evidence_store,
    )
    memory = PreferenceMemory(
        memory_id="pref_cascade",
        user_id="u1",
        text="private",
        evidences=[Evidence(event_id="evt1", content="source")],
    )
    writer.upsert_memory(memory)
    conflict_repo.save(
        ConflictRecord(
            conflict_id="conf_cascade",
            old_memory_id=memory.memory_id,
            new_memory_id="pref_new",
            memory_type="preference",
        )
    )
    forgetter = MemoryForgetter(
        pref_repo=pref_repo,
        know_repo=know_repo,
        evidence_store=evidence_store,
        conflict_repo=conflict_repo,
    )

    assert evidence_store.load(memory.memory_id)
    assert forgetter.delete_memories([memory.memory_id], user_id="u1") == 1
    assert evidence_store.load(memory.memory_id) == []
    assert conflict_repo.list_all() == []


def test_preference_updater_persists_conflict_and_syncs_versions(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    conflict_repo = ConflictRepository(db)
    lookup = {}
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=KnowledgeRepository(db),
        memory_lookup=lookup,
    )
    old = PreferenceMemory(
        memory_id="pref_old_version",
        user_id="u1",
        text="Use JSON",
        payload={"target": "format", "value": "json"},
        confidence=0.7,
    )
    writer.upsert_memory(old)
    updater = PreferenceUpdater(
        pref_repo=pref_repo,
        conflict_repo=conflict_repo,
        write_service=writer,
    )
    new = PreferenceMemory(
        memory_id="pref_new_version",
        user_id="u1",
        text="Use Markdown",
        payload={"target": "format", "value": "markdown"},
        confidence=0.95,
        extract_source="explicit_feedback",
    )

    result_id = updater.add(new)
    archived = pref_repo.get_by_id(old.memory_id)
    active = pref_repo.get_by_id(result_id)
    conflicts = conflict_repo.list_all()

    assert archived.status.value == "archived"
    assert active.status.value == "active"
    assert active.parent_id == old.memory_id
    assert active.version == old.version + 1
    assert old.memory_id not in lookup and result_id in lookup
    assert conflicts[0].result_memory_id == result_id


def test_event_normalizer_emits_complete_schema_11_event() -> None:
    event = EventNormalizer().normalize(
        {
            "event_id": "evt_normalized",
            "source_type": "user_behavior",
            "event_type": "preference_signal",
            "user_id": "u1",
            "session_id": "s1",
            "turn_id": "t1",
            "scene": "office",
            "task_type": "office.report",
            "occurred_at": "2026-08-03T12:30:00Z",
            "text": "Use Markdown",
            "payload": {"format": "markdown"},
            "redactions": ["/payload/token"],
        }
    )
    assert event.schema_version == "1.1"
    assert event.turn_id == "t1"
    assert len(event.source_hash) == 64
    assert event.redactions == ["/payload/token"]
    # Normalization is deterministic; EventIngestionService owns authoritative scoring.
    assert event.quality.status == QualityStatus.REVIEW


def test_event_normalizer_builds_valid_tool_result() -> None:
    event = EventNormalizer().normalize_tool_result(
        "writer", {"output": "done", "arguments": {"format": "md"}}
    )
    assert event.source_type.value == "tool_result"
    assert event.payload["output"] == "done"
    assert event.tool_calls[0].tool_name == "writer"
    assert event.tool_calls[0].result == "done"


def test_conflict_repository_enforces_user_dimension(tmp_path: Path) -> None:
    repo = ConflictRepository(_db(tmp_path))
    repo.save(
        ConflictRecord(
            conflict_id="conf_u1",
            user_id="u1",
            old_memory_id="a",
            new_memory_id="b",
        )
    )
    repo.save(
        ConflictRecord(
            conflict_id="conf_u2",
            user_id="u2",
            old_memory_id="c",
            new_memory_id="d",
        )
    )

    assert [item.conflict_id for item in repo.list_all("pending", user_id="u1")] == [
        "conf_u1"
    ]
    assert repo.resolve("conf_u2", "override", "no", user_id="u1") is False
    assert repo.resolve("conf_u2", "override", "yes", user_id="u2") is True


class _RecordingFactExtractor:
    def __init__(self):
        self.events = []

    def extract_from_trajectory(self, events):
        return []

    def extract_facts(self, events):
        self.events.extend(events)
        return []


def _fact_knowledge(
    fact_id: str,
    *,
    user_id: str = "u1",
    value: str = "Alice",
    subject: str = "Project A",
    confidence: float = 0.9,
) -> KnowledgeMemory:
    return KnowledgeMemory(
        memory_id=fact_id,
        user_id=user_id,
        knowledge_type=KnowledgeType.FACT,
        subject=subject,
        predicate="owner",
        object_value=value,
        object_type="Person",
        single_value=True,
        content=f"Project owner is {value}",
        confidence=confidence,
    )


def test_event_ingestion_runs_fact_extractor_once_for_first_safe_event(
    tmp_path: Path,
) -> None:
    event_repo = EventRepository(_db(tmp_path))
    extractor = _RecordingFactExtractor()
    service = EventIngestionService(
        event_repo=event_repo,
        safety_gate=_FakeGate(masked_text="safe fact text"),
        quality_scorer=_FixedQualityScorer(QualityStatus.ACCEPTED),
        memory_write_service=SimpleNamespace(upsert_memory=lambda _memory: None),
        knowledge_extractor=extractor,
    )

    first = service.ingest([_ingestion_event("evt_fact")])
    duplicate = service.ingest([_ingestion_event("evt_fact")])

    assert first.accepted == 1 and duplicate.accepted == 1
    assert len(extractor.events) == 1
    assert extractor.events[0].text == "safe fact text"


def test_fact_retrieval_is_owner_scoped_and_records_access(tmp_path: Path) -> None:
    db = _db(tmp_path)
    know_repo = KnowledgeRepository(db)
    fact = _fact_knowledge("fact_owner_u1")
    know_repo.save(fact)
    lookup = {fact.memory_id: fact}
    keyword = KeywordSearcher()
    keyword.build_index([(fact.memory_id, fact.content, "{}")])
    retriever = HybridRetriever(
        keyword_search=keyword,
        memory_lookup=lookup,
    )

    response = retriever.search(SearchRequest(user_id="u1", query="Alice owner"))
    assert [item.memory_id for item in response.knowledge] == [fact.memory_id]
    assert (
        retriever.search(SearchRequest(user_id="u2", query="Alice owner")).knowledge
        == []
    )

    _record_search_access(_request_with_state(know_repo=know_repo), response)
    loaded = know_repo.get_by_id(fact.memory_id)
    assert loaded.access_count_30d == 1
    assert loaded.last_accessed_at is not None


def test_fact_forget_enforces_owner_and_cascades_runtime_indexes(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    know_repo = KnowledgeRepository(db)
    fact = _fact_knowledge("fact_forget")
    know_repo.save(fact)
    lookup = {fact.memory_id: fact}
    vector = _FakeVectorStore()
    forgetter = MemoryForgetter(
        pref_repo=PreferenceRepository(db),
        know_repo=know_repo,
        memory_lookup=lookup,
        vector_store=vector,
    )

    assert forgetter.delete_memories([fact.memory_id], user_id="u2") == 0
    assert forgetter.delete_memories([fact.memory_id], user_id="u1") == 1
    assert know_repo.get_by_id(fact.memory_id).status == MemoryStatus.DELETED
    assert fact.memory_id not in lookup
    assert vector.deleted == [fact.memory_id]


def test_auto_forget_archives_fact(tmp_path: Path) -> None:
    db = _db(tmp_path)
    know_repo = KnowledgeRepository(db)
    fact = _fact_knowledge("fact_stale")
    fact.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    know_repo.save(fact)
    engine = AutoForgetEngine(
        pref_repo=PreferenceRepository(db),
        know_repo=know_repo,
    )

    stats = engine.run()
    assert stats["archived"] == 1
    assert know_repo.get_by_id(fact.memory_id).status == MemoryStatus.ARCHIVED
