from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.application.episode_service import EpisodeStateService
from memoryhub.application.working_service import WorkingStateService
from memoryhub.domain.contracts import (
    CandidateStatus,
    EpisodeEventContract,
    EpisodeSnapshot,
    EpisodeStatus,
    WorkingPatch,
    WorkingPatchOperation,
    WorkingSnapshot,
)
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import (
    CandidateRepository,
    EpisodeRepository,
    EpisodeResumeTokenError,
    VersionConflictError,
    WorkingStateRepository,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db() -> Database:
    db_path = ROOT / "evaluation" / "results" / "vnext_task_state_test.db"
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    database = Database(str(db_path))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def _working_patch(base_version: int, *operations: WorkingPatchOperation) -> WorkingPatch:
    return WorkingPatch(
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-a",
        base_version=base_version,
        operations=list(operations),
        event_refs=["event-working"],
        reason="test",
    )


def test_working_patch_merges_lists_honors_source_priority_and_cas(db: Database) -> None:
    service = WorkingStateService(WorkingStateRepository(db))
    service.create(
        WorkingSnapshot(
            tenant_id="tenant-a",
            user_id="user-a",
            task_id="task-a",
            session_id="session-a",
            current_goal="ship report",
            current_step="draft",
            pending_steps=["review"],
            constraints=["DOCX"],
        ),
        working_state_id="working-a",
        field_sources={"current_step": "user_explicit"},
    )

    merged = service.apply_patch(
        _working_patch(
            1,
            WorkingPatchOperation(
                op="replace", path="/current_step", value="inferred", source="inferred"
            ),
            WorkingPatchOperation(
                op="replace", path="/pending_steps", value=["export"], source="tool"
            ),
            WorkingPatchOperation(
                op="replace", path="/constraints", value=["no tables"], source="user_explicit"
            ),
        )
    )

    assert merged.version == 2
    assert merged.state["current_step"] == "draft"
    assert merged.state["pending_steps"] == ["review", "export"]
    assert merged.state["constraints"] == ["DOCX", "no tables"]
    assert merged.skipped_paths == ("/current_step",)
    assert merged.compressed_state["schema_version"] == "vnext/working-summary/v1"

    with pytest.raises(VersionConflictError):
        service.apply_patch(
            _working_patch(
                1,
                WorkingPatchOperation(op="replace", path="/current_step", value="stale"),
            )
        )


def _episode_snapshot(*, version: int, seq: int, phase: str = "draft") -> EpisodeSnapshot:
    return EpisodeSnapshot(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-a",
        task_id="task-a",
        session_id="session-a",
        status=EpisodeStatus.ACTIVE,
        current_phase=phase,
        goal="ship report",
        pending_steps=["review"],
        constraints=["DOCX"],
        last_event_seq=seq,
        snapshot_version=version,
    )


def test_episode_snapshot_resume_replays_events_and_surfaces_stale_resources(db: Database) -> None:
    service = EpisodeStateService(EpisodeRepository(db))
    service.create(
        episode_id="episode-a",
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-a",
        session_id="session-a",
        goal="ship report",
    )
    saved = service.snapshot(
        _episode_snapshot(version=1, seq=0),
        resource_versions={"doc": "v1", "schema": "v2"},
    )
    event = EpisodeEventContract(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-a",
        task_id="task-a",
        seq_no=1,
        event_type="PHASE_CHANGED",
        payload={"phase": "review", "pending_steps": ["export"]},
        source_event_id="event-episode-1",
    )
    service.append(event)
    resumed = service.resume(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-a",
        resume_token=saved.resume_token,
        current_resource_versions={"doc": "v2", "schema": "v2"},
    )
    assert resumed.snapshot.current_phase == "review"
    assert resumed.restored_state["current_phase"] == "review"
    assert resumed.restored_state["last_event_seq"] == 1
    assert resumed.stale_resources == ["doc"]
    assert resumed.required_revalidation == ["doc"]

    with pytest.raises(EpisodeResumeTokenError):
        service.resume(
            tenant_id="tenant-a",
            user_id="user-a",
            episode_id="episode-a",
            resume_token="wrong-token",
        )

    closed = service.close(
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-a",
        expected_snapshot_version=2,
    )
    assert closed.snapshot.status is EpisodeStatus.COMPLETED
    assert closed.snapshot.snapshot_version == 3


def test_candidate_transitions_and_default_retrieval_isolation(db: Database) -> None:
    repository = CandidateRepository(db)
    repository.create(
        candidate_id="candidate-a",
        tenant_id="tenant-a",
        user_id="user-a",
        memory_type="PREFERENCE",
        normalized_key="format.report",
        claim={"value": "DOCX"},
        scope_level="PROJECT",
        scope="PROJECT:reporting",
    )
    assert repository.transition(
        tenant_id="tenant-a",
        user_id="user-a",
        candidate_id="candidate-a",
        status=CandidateStatus.REVIEW.value,
    ).status == CandidateStatus.REVIEW.value
    assert repository.search(
        tenant_id="tenant-a", user_id="user-a", normalized_key="format.report"
    ) == []
    assert len(
        repository.search(
            tenant_id="tenant-a",
            user_id="user-a",
            normalized_key="format.report",
            include_candidates=True,
        )
    ) == 1
    assert len(repository.list_for_review(tenant_id="tenant-a", user_id="user-a")) == 1
