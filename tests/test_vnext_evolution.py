from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.application.evolution_service import EvolutionService, EvolutionServiceError
from memoryhub.domain.contracts import (
    EvolutionAction,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
)
from memoryhub.domain.evolution import (
    EvolutionTransitionError,
    can_evolve,
    decide_evolution_action,
    validate_evolution,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository

ROOT = Path(__file__).parents[1]
DB_PATH = ROOT / "evaluation" / "results" / "vnext_evolution_test.db"


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
def service(authority_facade: LongTermAuthorityFacade) -> EvolutionService:
    return EvolutionService(authority_facade)


def _envelope(
    *,
    memory_id: str = "pref-v1",
    memory_type: MemoryType = MemoryType.PREFERENCE,
    scope_level: MemoryScope = MemoryScope.PROJECT,
    scope: str = "PROJECT:reporting",
    content: dict | None = None,
    version: int = 1,
    status: EvolutionStatus = EvolutionStatus.ACTIVE,
    confidence: float = 0.9,
    evidence_refs: list[str] | None = None,
) -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id=memory_id,
        memory_type=memory_type,
        normalized_key="preference:format:docx",
        content=content or {"format": "DOCX"},
        scope_level=scope_level,
        scope=scope,
        evolution_status=status,
        confidence=confidence,
        utility=0.8,
        content_version=version,
        evidence_refs=evidence_refs or ["event-1"],
    )


def test_first_preference_becomes_active(service: EvolutionService) -> None:
    incoming = _envelope()
    result = service.evolve(incoming)
    assert result.action == EvolutionAction.REINFORCE.value
    assert result.new_envelope.evolution_status is EvolutionStatus.ACTIVE
    assert result.new_envelope.content_version == 1
    assert result.persisted is True


def test_reinforce_creates_new_version_and_supersedes_old(
    service: EvolutionService,
) -> None:
    existing = _envelope(memory_id="pref-v1", version=1)
    service.evolve(existing)

    incoming = _envelope(memory_id="pref-v1", version=1, confidence=0.95)
    result = service.evolve(incoming)
    assert result.action == EvolutionAction.REINFORCE.value
    assert result.new_envelope.content_version > existing.content_version
    assert result.superseded_envelope is not None
    assert result.superseded_envelope.evolution_status is EvolutionStatus.SUPERSEDED

    current = service.authority_facade.read(
        tenant_id="tenant-a", user_id="user-a", memory_id="pref-v1", include_inactive=False
    )
    assert current is not None
    assert current.evolution_status is EvolutionStatus.ACTIVE


def test_revise_updates_content_and_supersedes_old(
    service: EvolutionService,
) -> None:
    existing = _envelope(memory_id="pref-v1", version=1, content={"format": "DOCX"})
    service.evolve(existing)

    incoming = _envelope(
        memory_id="pref-v1",
        version=2,
        content={"format": "PDF"},
    )
    result = service.evolve(incoming)
    assert result.action == EvolutionAction.SUPERSEDE.value
    assert result.new_envelope.content["format"] == "PDF"
    assert result.superseded_envelope is not None


def test_different_scope_chains_both_remain_active(
    service: EvolutionService,
) -> None:
    global_pref = _envelope(
        memory_id="pref-global",
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        content={"format": "Markdown"},
    )
    service.evolve(global_pref)

    project_pref = _envelope(
        memory_id="pref-project",
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        content={"format": "DOCX"},
    )
    result = service.evolve(project_pref)
    # Different scope chains do not conflict; the second memory is created.
    assert result.action == EvolutionAction.REINFORCE.value
    assert result.new_envelope.evolution_status is EvolutionStatus.ACTIVE

    active = service.authority_facade.list_active(
        tenant_id="tenant-a", user_id="user-a"
    )
    assert len(active) == 2


def test_review_decision_is_not_persisted(service: EvolutionService) -> None:
    existing = _envelope(memory_id="pref-v1", version=2, content={"format": "DOCX"})
    service.evolve(existing)

    stale = _envelope(
        memory_id="pref-v1", version=1, content={"format": "PDF"}, confidence=0.5
    )
    result = service.evolve(stale)
    assert result.action == EvolutionAction.REVIEW.value
    assert result.persisted is False


def test_evolution_status_transitions_are_restricted() -> None:
    assert can_evolve(EvolutionStatus.ACTIVE.value, EvolutionStatus.SUPERSEDED.value) is True
    assert can_evolve(EvolutionStatus.ACTIVE.value, EvolutionStatus.ACTIVE.value) is False
    assert can_evolve(EvolutionStatus.DELETED.value, EvolutionStatus.ACTIVE.value) is False

    with pytest.raises(EvolutionTransitionError):
        validate_evolution(EvolutionStatus.SUPERSEDED.value, EvolutionStatus.ACTIVE.value)


def test_decide_action_maps_content_and_scope_correctly() -> None:
    existing = _envelope(memory_id="pref-v1", content={"format": "DOCX"})
    same = _envelope(memory_id="pref-v1", content={"format": "DOCX"})
    revised = _envelope(memory_id="pref-v1", version=2, content={"format": "PDF"})
    different_scope = _envelope(
        memory_id="pref-v2",
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
        content={"format": "DOCX"},
    )

    assert decide_evolution_action(same, existing) is EvolutionAction.REINFORCE
    assert decide_evolution_action(revised, existing) is EvolutionAction.SUPERSEDE
    assert decide_evolution_action(different_scope, existing) is EvolutionAction.COEXIST


def test_evolution_service_rejects_non_envelope_input(
    service: EvolutionService,
) -> None:
    with pytest.raises(EvolutionServiceError):
        service.evolve({})  # type: ignore[arg-type]
