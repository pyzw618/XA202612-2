from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from memoryhub.storage.database import Database
from memoryhub.storage.models import Base
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
    CandidateRepository,
    EpisodeRepository,
    EpisodeSequenceConflictError,
    EvidenceRepository,
    InvalidCandidateTransitionError,
    VersionConflictError,
    WorkingStateRepository,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture()
def db() -> Database:
    db_path = ROOT / "evaluation" / "results" / "vnext_repository_test.db"
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    database = Database(str(db_path))
    database.init_schema()
    yield database
    database.close()
    for suffix in ("", "-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)


def test_working_state_compare_and_set_is_tenant_scoped(db: Database) -> None:
    repository = WorkingStateRepository(db)
    repository.create(
        working_state_id="working-a",
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-1",
        state={"current_step": "draft"},
    )
    repository.create(
        working_state_id="working-b",
        tenant_id="tenant-b",
        user_id="user-b",
        task_id="task-1",
        state={"current_step": "other"},
    )

    updated = repository.compare_and_set(
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-1",
        expected_version=1,
        state={"current_step": "review"},
        event_id="evt-1",
    )
    assert updated.version == 2
    assert repository.get(tenant_id="tenant-b", user_id="user-a", task_id="task-1") is None

    with pytest.raises(VersionConflictError):
        repository.compare_and_set(
            tenant_id="tenant-a",
            user_id="user-a",
            task_id="task-1",
            expected_version=1,
            state={"current_step": "stale"},
        )
    assert repository.get(
        tenant_id="tenant-a", user_id="user-a", task_id="task-1"
    ).state == {"current_step": "review"}


def test_init_schema_adds_project_scope_to_existing_working_and_episode_tables() -> None:
    database = Database(":memory:")
    database.engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE working_states")
        connection.exec_driver_sql("DROP TABLE task_episodes")
        connection.exec_driver_sql(
            """
            CREATE TABLE working_states (
                working_state_id VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                task_id VARCHAR(128) NOT NULL,
                session_id VARCHAR(128) NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                state JSON NOT NULL DEFAULT '{}',
                field_sources JSON NOT NULL DEFAULT '{}',
                last_event_id VARCHAR(64),
                schema_version VARCHAR(16) NOT NULL DEFAULT 'vnext/v1',
                content_version INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE task_episodes (
                episode_id VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL,
                user_id VARCHAR(64) NOT NULL,
                task_id VARCHAR(128) NOT NULL,
                session_id VARCHAR(128) NOT NULL DEFAULT '',
                status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
                current_phase VARCHAR(64) NOT NULL DEFAULT '',
                goal TEXT NOT NULL DEFAULT '',
                snapshot JSON NOT NULL DEFAULT '{}',
                snapshot_version INTEGER NOT NULL DEFAULT 1,
                last_event_seq INTEGER NOT NULL DEFAULT 0,
                resume_token_hash VARCHAR(128),
                stale_resources JSON NOT NULL DEFAULT '[]',
                required_revalidation JSON NOT NULL DEFAULT '[]',
                resource_versions JSON NOT NULL DEFAULT '{}',
                schema_version VARCHAR(16) NOT NULL DEFAULT 'vnext/v1',
                content_version INTEGER NOT NULL DEFAULT 1,
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )

    database._ensure_compatible_schema()
    with database.engine.connect() as connection:
        working_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(working_states)")
        }
        episode_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(task_episodes)")
        }
    assert "project_id" in working_columns
    assert "project_id" in episode_columns
    database.close()


def test_episode_append_assigns_monotonic_sequence_and_rejects_stale_expected_seq(
    db: Database,
) -> None:
    repository = EpisodeRepository(db)
    repository.create(
        episode_id="episode-1",
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-1",
        goal="complete report",
    )
    first = repository.append_event(
        episode_event_id="episode-event-1",
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-1",
        task_id="task-1",
        event_type="PHASE_CHANGED",
        payload={"phase": "draft"},
        source_event_id="evt-1",
        expected_seq=1,
    )
    second = repository.append_event(
        episode_event_id="episode-event-2",
        tenant_id="tenant-a",
        user_id="user-a",
        episode_id="episode-1",
        task_id="task-1",
        event_type="PHASE_CHECKPOINT",
        payload={"phase": "review"},
        source_event_id="evt-2",
        expected_seq=2,
    )
    assert (first.seq_no, second.seq_no) == (1, 2)
    assert [event.seq_no for event in repository.list_events(
        tenant_id="tenant-a", user_id="user-a", episode_id="episode-1"
    )] == [1, 2]

    with pytest.raises(EpisodeSequenceConflictError):
        repository.append_event(
            episode_event_id="episode-event-stale",
            tenant_id="tenant-a",
            user_id="user-a",
            episode_id="episode-1",
            task_id="task-1",
            event_type="STALE",
            payload={},
            source_event_id="evt-stale",
            expected_seq=2,
        )


def test_candidate_status_transition_is_closed_and_tenant_scoped(db: Database) -> None:
    repository = CandidateRepository(db)
    repository.create(
        candidate_id="candidate-1",
        tenant_id="tenant-a",
        user_id="user-a",
        memory_type="PREFERENCE",
        normalized_key="format.report",
        claim={"value": "DOCX"},
        scope_level="PROJECT",
        scope="PROJECT:reporting",
    )
    assert repository.transition(
        tenant_id="tenant-a", user_id="user-a", candidate_id="candidate-1", status="REVIEW"
    ).status == "REVIEW"
    assert repository.transition(
        tenant_id="tenant-a", user_id="user-a", candidate_id="candidate-1", status="CONFIRMED"
    ).status == "CONFIRMED"
    with pytest.raises(InvalidCandidateTransitionError):
        repository.transition(
            tenant_id="tenant-a", user_id="user-a", candidate_id="candidate-1", status="REJECTED"
        )
    assert repository.get(
        tenant_id="tenant-b", user_id="user-b", candidate_id="candidate-1"
    ) is None


def test_evidence_dedup_returns_existing_reference_without_raw_content(db: Database) -> None:
    repository = EvidenceRepository(db)
    first, created = repository.record(
        evidence_id="evidence-1",
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id="memory-1",
        memory_type="PREFERENCE",
        event_id="event-1",
        source_hash="a" * 64,
        content_ref="sha256:" + "b" * 64,
        source_type="user_explicit",
    )
    retry, retry_created = repository.record(
        evidence_id="evidence-retry",
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id="memory-1",
        memory_type="PREFERENCE",
        event_id="event-1",
        source_hash="a" * 64,
        content_ref="sha256:" + "b" * 64,
        source_type="user_explicit",
    )
    assert created is True
    assert retry_created is False
    assert retry.evidence_id == first.evidence_id
    assert retry.content_ref.startswith("sha256:")


def test_activation_is_unique_per_tenant_query_memory_version(db: Database) -> None:
    repository = ActivationRepository(db)
    kwargs = dict(
        tenant_id="tenant-a",
        user_id="user-a",
        query_id="query-1",
        memory_id="memory-1",
        task_id="task-1",
        intent="PREFERENCE",
        status="IN_CONTEXT",
        rank=1,
        initial_score=0.7,
        reranked_score=0.8,
        content_version=1,
    )
    first = repository.record(activation_id="activation-1", **kwargs)
    # ActivationRepository intentionally upserts per (tenant, user, query, memory, version).
    duplicate = repository.record(activation_id="activation-duplicate", **kwargs)
    assert duplicate.activation_id == first.activation_id
    newer = repository.record(
        activation_id="activation-2", **{**kwargs, "content_version": 2}
    )
    other_tenant = repository.record(
        activation_id="activation-3", **{**kwargs, "tenant_id": "tenant-b", "user_id": "user-b"}
    )
    assert newer.content_version == 2
    assert newer.activation_id != first.activation_id
    assert other_tenant.tenant_id == "tenant-b"
    assert other_tenant.activation_id != first.activation_id
