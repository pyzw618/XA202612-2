from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.application.candidate_service import CandidateService
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.core.reflection.schema import ReflectionInput
from memoryhub.domain.candidate import normalize_claim_key
from memoryhub.domain.contracts import (
    Candidate,
    CandidateStatus,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
)
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import CandidateRepository


@pytest.fixture()
def db() -> Database:
    db_path = (
        Path(__file__).parents[1]
        / "evaluation"
        / "results"
        / "vnext_candidate_service_test.db"
    )
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    database = Database(str(db_path))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


@pytest.fixture()
def service(db: Database) -> CandidateService:
    return CandidateService(CandidateRepository(db))


def _candidate(
    *,
    candidate_id: str = "candidate-1",
    user_id: str = "user-a",
    claim: dict | None = None,
) -> Candidate:
    return Candidate(
        tenant_id="tenant-a",
        user_id=user_id,
        candidate_id=candidate_id,
        memory_type=MemoryType.PREFERENCE,
        normalized_key="format:docx",
        claim=claim or {"format": "DOCX"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        status=CandidateStatus.ACCUMULATING,
        confidence=0.8,
        utility=0.7,
        stability=0.6,
        evidence_refs=["event-1"],
        supporting_episode_ids=["episode-1"],
    )


def _event(event_id: str, episode_id: str, payload: dict | None = None) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        event_id=event_id,
        event_type="USER_MESSAGE",
        source_type="USER_BEHAVIOR",
        task_id="task-a",
        session_id="session-a",
        occurred_at="2026-08-24T07:00:00+00:00",
        payload=payload or {},
        policy_action="ALLOW",
        source_hash=f"hash-{event_id}",
        idempotency_key=f"idem-{event_id}",
        trace_id="trace-a",
    )


def test_stage_creates_new_candidate(service: CandidateService) -> None:
    candidate = _candidate()
    event = _event("event-1", "episode-1")
    result = service.stage(candidate, source_event=event, episode_id="episode-1")
    assert result.created is True
    assert result.merged is False
    assert result.candidate.normalized_key == "preference:format:docx"
    assert result.candidate.frequency == 1  # initial independent evidence


def test_same_event_does_not_create_independent_evidence(service: CandidateService) -> None:
    first = _candidate(candidate_id="candidate-1")
    event = _event("event-1", "episode-1")
    service.stage(first, source_event=event, episode_id="episode-1")

    duplicate = _candidate(candidate_id="candidate-2")
    result = service.stage(duplicate, source_event=event, episode_id="episode-1")
    assert result.merged is True
    assert result.is_independent_evidence is False
    assert result.candidate.frequency == 1  # creation already counted the first group


def test_different_episode_same_claim_adds_independent_evidence(service: CandidateService) -> None:
    first = _candidate(candidate_id="candidate-1")
    service.stage(first, source_event=_event("event-1", "episode-1"), episode_id="episode-1")

    second = _candidate(candidate_id="candidate-2")
    result = service.stage(
        second,
        source_event=_event("event-2", "episode-2"),
        episode_id="episode-2",
    )
    assert result.merged is True
    assert result.is_independent_evidence is True
    assert result.candidate.frequency == 2  # two independent episodes


def test_scope_never_auto_promoted_to_global(service: CandidateService) -> None:
    candidate = Candidate(
        tenant_id="tenant-a",
        user_id="user-a",
        candidate_id="candidate-global",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="format:docx",
        claim={"format": "DOCX"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        status=CandidateStatus.ACCUMULATING,
        confidence=0.8,
        utility=0.7,
        stability=0.6,
    )
    # Without explicit payload, the candidate's scope is respected.
    result = service.stage(
        candidate,
        source_event=_event("event-global", "episode-global"),
        episode_id="episode-global",
    )
    assert result.candidate.scope_level == MemoryScope.GLOBAL.value


def test_event_payload_scope_takes_precedence(service: CandidateService) -> None:
    candidate = _candidate()
    event = _event(
        "event-scope",
        "episode-scope",
        payload={"scope_level": "TASK", "scope": "TASK:special"},
    )
    result = service.stage(candidate, source_event=event, episode_id="episode-scope")
    assert result.candidate.scope_level == "TASK"
    assert result.candidate.scope == "TASK:special"


def test_normalize_claim_key_is_stable_and_case_insensitive() -> None:
    key1 = normalize_claim_key({"format": "DOCX", "Context": "Reports"}, "PREFERENCE")
    key2 = normalize_claim_key({"format": "docx", "context": "reports"}, "PREFERENCE")
    assert key1 == key2


def test_reflection_output_flows_through_candidate_service_without_authority(
    service: CandidateService,
) -> None:
    reflection = ReflectionService(model=DeterministicReflectionModel())
    candidate = reflection.run(
        ReflectionInput(
            tenant_id="tenant-a",
            user_id="user-a",
            task_id="task-a",
            episode_id="episode-reflection",
            event_id="event-reflection",
            payload_summary={"text": "Use DOCX for Project-A reports."},
        )
    )
    event = MemoryEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        event_id="event-reflection",
        event_type="USER_MESSAGE",
        source_type="USER_BEHAVIOR",
        task_id="task-a",
        session_id="session-a",
        occurred_at="2026-08-24T07:00:00+00:00",
        payload={},
        policy_action="ALLOW",
        source_hash="hash-reflection",
        idempotency_key="idem-reflection",
        trace_id="trace-reflection",
    )
    result = service.stage(candidate, source_event=event, episode_id="episode-reflection")
    assert result.created is True
    assert result.candidate.normalized_key.startswith("preference:")
    assert "format:docx" in result.candidate.normalized_key
    assert result.candidate.scope_level == "PROJECT"
    # The candidate is staging data, not a long-term Authority row.
    assert result.candidate.formation_status == "CANDIDATE"
