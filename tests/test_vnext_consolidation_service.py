from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.application.consolidation_service import (
    ConsolidationContext,
    ConsolidationService,
    PromotionDecision,
)
from memoryhub.domain.contracts import (
    CandidateStatus,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.vnext_repositories import CandidateView

ROOT = Path(__file__).parents[1]
DB_PATH = ROOT / "evaluation" / "results" / "vnext_consolidation_test.db"


@pytest.fixture()
def db() -> Database:
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)
    database = Database(str(DB_PATH))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        DB_PATH.with_name(DB_PATH.name + suffix).unlink(missing_ok=True)


@pytest.fixture()
def authority_facade(db: Database) -> LongTermAuthorityFacade:
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    return LongTermAuthorityFacade(authority)


@pytest.fixture()
def service(authority_facade: LongTermAuthorityFacade) -> ConsolidationService:
    return ConsolidationService(authority_facade)


@pytest.fixture()
def plain_service() -> ConsolidationService:
    return ConsolidationService()


def _candidate_view(
    *,
    memory_type: str = "PREFERENCE",
    confidence: float = 0.9,
    utility: float = 0.8,
    stability: float = 0.8,
    frequency: int = 1,
    scope_level: str = "PROJECT",
    scope: str = "PROJECT:reporting",
    normalized_key: str = "preference:format:docx",
    claim: dict | None = None,
) -> CandidateView:
    return CandidateView(
        candidate_id="candidate-1",
        tenant_id="tenant-a",
        user_id="user-a",
        memory_type=memory_type,
        status=CandidateStatus.ACCUMULATING.value,
        formation_status="CANDIDATE",
        normalized_key=normalized_key,
        scope_level=scope_level,
        scope=scope,
        claim=claim or {"format": "DOCX"},
        confidence=confidence,
        utility=utility,
        stability=stability,
        frequency=frequency,
        evidence_refs=["event-1"],
        supporting_episode_ids=["episode-1"],
    )


def _event(
    *,
    event_id: str = "event-1",
    source_type: str = "USER_BEHAVIOR",
    payload: dict | None = None,
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        event_id=event_id,
        event_type="USER_MESSAGE",
        source_type=source_type,
        task_id="task-a",
        session_id="session-a",
        occurred_at="2026-08-24T08:00:00+00:00",
        payload=payload or {},
        policy_action="ALLOW",
        source_hash=f"hash-{event_id}",
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def test_low_score_candidate_is_rejected(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(confidence=0.2, utility=0.2, stability=0.2, frequency=0)
    result = plain_service.consolidate(candidate, memory_id="memory-1")
    assert result.decision == PromotionDecision.REJECT
    assert result.score < 0.3
    assert "SCORE_BELOW_REVIEW_THRESHOLD" in result.reasons
    assert result.envelope is None


def test_mid_score_candidate_goes_to_review(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(confidence=0.6, utility=0.5, stability=0.5, frequency=1)
    result = plain_service.consolidate(candidate, memory_id="memory-1")
    assert result.decision == PromotionDecision.REVIEW
    assert "SCORE_IN_REVIEW_BAND" in result.reasons
    assert result.envelope is None


def test_high_confidence_preference_promotes(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.95,
        utility=0.8,
        stability=0.85,
        frequency=2,
    )
    result = plain_service.consolidate(candidate, memory_id="memory-1")
    assert result.decision == PromotionDecision.PROMOTE
    assert result.score >= 0.7
    assert "HIGH_CONFIDENCE" in result.reasons
    assert result.envelope is not None
    assert result.envelope.memory_type is MemoryType.PREFERENCE


def test_semantic_fact_needs_more_evidence_than_preference(
    plain_service: ConsolidationService,
) -> None:
    pref = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.9,
        utility=0.8,
        stability=0.7,
        frequency=1,
    )
    sem = _candidate_view(
        memory_type="SEMANTIC",
        confidence=0.9,
        utility=0.8,
        stability=0.7,
        frequency=1,
    )
    pref_result = plain_service.consolidate(pref, memory_id="memory-1")
    sem_result = plain_service.consolidate(sem, memory_id="memory-2")
    assert pref_result.decision == PromotionDecision.PROMOTE
    assert sem_result.decision == PromotionDecision.REVIEW


def test_procedural_needs_high_score_to_promote(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(
        memory_type="PROCEDURAL",
        confidence=0.8,
        utility=0.7,
        stability=0.7,
        frequency=1,
    )
    result = plain_service.consolidate(candidate, memory_id="memory-1")
    assert result.decision == PromotionDecision.REVIEW


def test_explicit_preference_can_use_fast_path(
    service: ConsolidationService,
) -> None:
    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.95,
        utility=0.9,
        stability=0.9,
        frequency=1,
    )
    context = ConsolidationContext(
        source_event=_event(payload={"explicit_long_term": True}),
        explicit_long_term=True,
    )
    result = service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.decision == PromotionDecision.PROMOTE
    assert result.fast_path is True
    assert "FAST_PATH_EXPLICIT" in result.reasons


def test_high_trust_tool_fact_can_use_fast_path(
    service: ConsolidationService,
) -> None:
    candidate = _candidate_view(
        memory_type="SEMANTIC",
        confidence=0.95,
        utility=0.8,
        stability=0.85,
        frequency=2,
        normalized_key="fact:python.version",
        claim={"statement": "Python 3.11"},
    )
    context = ConsolidationContext(
        source_event=_event(source_type="TOOL_RESULT"),
        tool_trust="high",
    )
    result = service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.decision == PromotionDecision.PROMOTE
    assert result.fast_path is True
    assert "FAST_PATH_HIGH_TRUST_TOOL" in result.reasons


def test_low_confidence_blocks_fast_path(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.8,
        utility=0.8,
        stability=0.8,
        frequency=2,
    )
    context = ConsolidationContext(
        source_event=_event(payload={"explicit_long_term": True}),
        explicit_long_term=True,
    )
    result = plain_service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.decision == PromotionDecision.PROMOTE
    assert result.fast_path is False


def test_sensitive_content_blocks_fast_path(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.95,
        utility=0.9,
        stability=0.9,
        frequency=2,
    )
    context = ConsolidationContext(
        source_event=_event(payload={"explicit_long_term": True}),
        explicit_long_term=True,
        sensitivity_level="HIGH",
    )
    result = plain_service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.fast_path is False


def test_session_scope_blocks_fast_path(plain_service: ConsolidationService) -> None:
    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.95,
        utility=0.9,
        stability=0.9,
        frequency=2,
        scope_level="SESSION",
        scope="SESSION:session-a",
    )
    context = ConsolidationContext(
        source_event=_event(payload={"explicit_long_term": True}),
        explicit_long_term=True,
    )
    result = plain_service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.fast_path is False


def test_existing_active_memory_blocks_fast_path(
    service: ConsolidationService,
    authority_facade: LongTermAuthorityFacade,
) -> None:
    existing = LongTermEnvelope(
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id="existing-1",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="preference:format:docx",
        content={"format": "DOCX"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        evolution_status=EvolutionStatus.ACTIVE,
        confidence=0.9,
        utility=0.8,
        evidence_refs=["event-old"],
    )
    authority_facade.write(existing)

    candidate = _candidate_view(
        memory_type="PREFERENCE",
        confidence=0.95,
        utility=0.9,
        stability=0.9,
        frequency=2,
    )
    context = ConsolidationContext(
        source_event=_event(payload={"explicit_long_term": True}),
        explicit_long_term=True,
    )
    result = service.consolidate(candidate, memory_id="memory-1", context=context)
    assert result.decision == PromotionDecision.PROMOTE
    assert result.fast_path is False


def test_fast_path_only_for_preference_and_semantic(
    plain_service: ConsolidationService,
) -> None:
    for memory_type in ("PROCEDURAL", "EPISODIC"):
        candidate = _candidate_view(
            memory_type=memory_type,
            confidence=0.99,
            utility=0.95,
            stability=0.95,
            frequency=5,
        )
        context = ConsolidationContext(
            source_event=_event(payload={"explicit_long_term": True}),
            explicit_long_term=True,
        )
        result = plain_service.consolidate(
            candidate, memory_id=f"memory-{memory_type}", context=context
        )
        assert result.decision == PromotionDecision.PROMOTE
        assert result.fast_path is False
