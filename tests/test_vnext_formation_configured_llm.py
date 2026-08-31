"""End-to-end Formation tests using the same production Reflection stack with a fake LLM.

These tests prove the complete Formation chain:

    Event -> Working -> Episode -> Boundary -> FormationWorker
    -> ReflectionService -> StructuredReflectionModel -> configured LLM client
    -> validated ReflectionOutput -> Candidate

The fake client only replaces the outermost model request; everything else
(the prompt rendering, schema validation, retry logic, worker staging and
candidate-only boundaries) is the production code path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import (
    ReflectionService,
    StructuredReflectionModel,
)
from memoryhub.application.working_service import WorkingService
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.llm.base import BaseLLMClient, LLMResponse
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.vnext_repositories import (
    CandidateRepository,
    EpisodeRepository,
    WorkingStateRepository,
)


class FakeConfiguredLLMClient(BaseLLMClient):
    """A fake LLM client that stands in for a real configured provider.

    It implements the same BaseLLMClient contract used by OpenAIClient, so
    StructuredReflectionModel can be exercised without network access.
    """

    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def generate(self, prompt: str, system_prompt: str = "", **kwargs: Any) -> LLMResponse:
        raise NotImplementedError("Formation uses generate_json only")

    def generate_json(
        self, prompt: str, schema: dict[str, Any], system_prompt: str = ""
    ) -> dict[str, Any]:
        self.calls.append((prompt, schema))

        if self.mode == "failure":
            raise TimeoutError("fake provider timeout")

        if self.mode == "invalid":
            return {"candidate_id": "candidate-invalid"}

        # mode == "success"
        return {
            "candidate_id": "candidate-configured",
            "memory_type": "PREFERENCE",
            "normalized_key": "format:configured",
            "claim": {"value": "Use configured LLM"},
            "scope_level": "PROJECT",
            "scope": "PROJECT:configured",
            "confidence": 0.8,
            "utility": 0.7,
            "stability": 0.6,
            "model_id": "fake-configured-llm",
            "prompt_version": "reflection/v1",
            "input_hash": "fake-input-hash",
            "reason": "configured LLM generated this candidate",
            "evidence_refs": ["event-configured"],
            "supporting_episode_ids": ["episode-configured"],
            "status": "ACCUMULATING",
        }

    def is_available(self) -> bool:
        return True


def _event(event_id: str, payload: dict, *, boundary: str | None = None) -> MemoryEventContract:
    merged = dict(payload)
    if boundary is not None:
        merged["boundary"] = boundary
    return MemoryEventContract(
        tenant_id="tenant-configured",
        user_id="user-configured",
        event_id=event_id,
        event_type="user_instruction",
        source_type="user_behavior",
        task_id="task-configured",
        session_id="session-configured",
        occurred_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        payload=merged,
        policy_action="ALLOW",
        source_hash="c" * 64,
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


@pytest.fixture()
def db() -> Database:
    database = Database(":memory:")
    database.init_schema()
    yield database
    database.close()


def _stack(db: Database) -> tuple[CanonicalWriteService, ExtractionTaskRepository]:
    pref = PreferenceRepository(db)
    know = KnowledgeRepository(db)
    authority = LongTermAuthorityFacade(
        AuthorityRepository(
            db, preference_repository=pref, knowledge_repository=know
        )
    )
    writer = MemoryWriteService(
        pref_repo=pref, know_repo=know, project_immediately=False
    )
    tasks = ExtractionTaskRepository(db)
    canonical = CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        extraction_tasks=tasks,
        authority_facade=authority,
        memory_write_service=writer,
        formation_mode="candidate-only",
    )
    return canonical, tasks


def _worker(
    db: Database,
    canonical: CanonicalWriteService,
    tasks: ExtractionTaskRepository,
    mode: str,
) -> FormationWorker:
    return FormationWorker(
        db,
        task_repository=tasks,
        event_repository=EventRepository(db),
        canonical_write_service=canonical,
        mode="candidate-only",
        reflection_service=ReflectionService(
            model=StructuredReflectionModel(FakeConfiguredLLMClient(mode=mode)),
            max_retries=1,
        ),
    )


def _retry(
    db: Database,
    worker: FormationWorker,
    tasks: ExtractionTaskRepository,
) -> ExtractionRetryService:
    return ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )


def test_success_valid_structured_response_creates_candidate(db: Database) -> None:
    """Valid configured-LLM response flows through the full chain and creates a Candidate."""
    canonical, tasks = _stack(db)
    worker = _worker(db, canonical, tasks, mode="success")
    retry = _retry(db, worker, tasks)

    canonical.write(_event("configured-goal", {"text": "Set up project build"}))
    result = canonical.write(
        _event(
            "configured-remember",
            {"text": "This project uses configured LLM"},
            boundary="explicit",
        )
    )

    assert result.reflection_task is not None
    run = retry.run_due(user_id="user-configured")

    candidates = CandidateRepository(db).list_for_review(
        tenant_id="tenant-configured", user_id="user-configured"
    )

    # Both the initial user_instruction and the explicit remember event trigger
    # reflection in this minimal stack; the configured LLM path succeeds for both.
    # The deterministic key/scope merge collapses the two reflections into one
    # Candidate with two independent evidence refs.
    assert run.succeeded == 2
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "candidate-configured"
    assert candidates[0].memory_type == "PREFERENCE"
    assert len(candidates[0].evidence_refs) == 2
    assert PreferenceRepository(db).list_all(user_id="user-configured") == []
    assert KnowledgeRepository(db).list_all(user_id="user-configured") == []


def test_invalid_structured_response_does_not_create_candidate(db: Database) -> None:
    """Invalid configured-LLM output fails schema validation and produces no dirty Candidate."""
    canonical, tasks = _stack(db)
    worker = _worker(db, canonical, tasks, mode="invalid")
    retry = _retry(db, worker, tasks)

    canonical.write(_event("configured-goal", {"text": "Set up project build"}))
    result = canonical.write(
        _event(
            "configured-remember-invalid",
            {"text": "This project uses configured LLM"},
            boundary="explicit",
        )
    )

    assert result.reflection_task is not None
    run = retry.run_due(user_id="user-configured")

    candidates = CandidateRepository(db).list_for_review(
        tenant_id="tenant-configured", user_id="user-configured"
    )

    assert run.retried == 2
    assert candidates == []
    assert PreferenceRepository(db).list_all(user_id="user-configured") == []
    assert KnowledgeRepository(db).list_all(user_id="user-configured") == []


def test_provider_failure_does_not_create_candidate(db: Database) -> None:
    """Configured-LLM exception preserves retry/failure behavior and creates no Candidate."""
    canonical, tasks = _stack(db)
    worker = _worker(db, canonical, tasks, mode="failure")
    retry = _retry(db, worker, tasks)

    canonical.write(_event("configured-goal", {"text": "Set up project build"}))
    result = canonical.write(
        _event(
            "configured-remember-failure",
            {"text": "This project uses configured LLM"},
            boundary="explicit",
        )
    )

    assert result.reflection_task is not None
    run = retry.run_due(user_id="user-configured")

    candidates = CandidateRepository(db).list_for_review(
        tenant_id="tenant-configured", user_id="user-configured"
    )

    assert run.retried == 2
    assert candidates == []
    assert PreferenceRepository(db).list_all(user_id="user-configured") == []
    assert KnowledgeRepository(db).list_all(user_id="user-configured") == []
