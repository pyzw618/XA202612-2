"""Tenant-scoped repositories for the vNext Authority storage slice.

Repositories own persistence invariants and transaction boundaries only. They
do not decide Policy, formation, ranking, or promotion; those belong to the
canonical application services built in later S1/S2 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from memoryhub.domain.candidate import can_transition
from memoryhub.domain.episode import hash_resume_token, resume_token_matches
from memoryhub.storage.database import Database
from memoryhub.storage.models import (
    EpisodeEventRow,
    MemoryActivationRow,
    MemoryCandidateRow,
    MemoryEvidenceRow,
    TaskEpisodeRow,
    WorkingStateRow,
)


class VersionConflictError(RuntimeError):
    """The caller attempted to update state from an obsolete version."""


class EpisodeResumeTokenError(VersionConflictError):
    """The caller supplied an invalid or stale episode resume token."""


class EpisodeSequenceConflictError(RuntimeError):
    """An episode append did not use the next sequence number."""


class InvalidCandidateTransitionError(ValueError):
    """A candidate status transition is not allowed by the storage contract."""


@dataclass(frozen=True, slots=True)
class WorkingStateView:
    working_state_id: str
    tenant_id: str
    user_id: str
    task_id: str
    version: int
    state: dict[str, Any]
    field_sources: dict[str, str]
    last_event_id: str | None


@dataclass(frozen=True, slots=True)
class EpisodeEventView:
    episode_event_id: str
    tenant_id: str
    user_id: str
    episode_id: str
    task_id: str
    seq_no: int
    event_type: str
    payload: dict[str, Any]
    source_event_id: str


@dataclass(frozen=True, slots=True)
class EpisodeSnapshotView:
    episode_id: str
    tenant_id: str
    user_id: str
    task_id: str
    session_id: str
    status: str
    current_phase: str
    goal: str
    snapshot: dict[str, Any]
    snapshot_version: int
    last_event_seq: int
    stale_resources: list[str]
    required_revalidation: list[str]
    resource_versions: dict[str, str]


@dataclass(frozen=True, slots=True)
class CandidateView:
    candidate_id: str
    tenant_id: str
    user_id: str
    status: str
    formation_status: str
    normalized_key: str
    scope_level: str
    scope: str
    claim: dict[str, Any]
    confidence: float
    utility: float
    stability: float
    frequency: int
    evidence_refs: list[str]
    supporting_episode_ids: list[str]


@dataclass(frozen=True, slots=True)
class EvidenceView:
    evidence_id: str
    tenant_id: str
    user_id: str
    memory_id: str
    event_id: str
    source_hash: str
    content_ref: str | None


@dataclass(frozen=True, slots=True)
class ActivationView:
    activation_id: str
    tenant_id: str
    user_id: str
    query_id: str
    memory_id: str
    content_version: int


class WorkingStateRepository:
    """CRUD plus compare-and-set for one tenant/user/task working state."""

    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        *,
        working_state_id: str,
        tenant_id: str,
        user_id: str,
        task_id: str,
        state: dict[str, Any],
        session_id: str = "",
        version: int = 1,
        field_sources: dict[str, str] | None = None,
    ) -> WorkingStateView:
        row = WorkingStateRow(
            working_state_id=working_state_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            session_id=session_id,
            state=dict(state),
            field_sources=dict(field_sources or {}),
            version=version,
        )
        with self.db.session() as session:
            session.add(row)
            session.flush()
            return self._view(row)

    def get(self, *, tenant_id: str, user_id: str, task_id: str) -> WorkingStateView | None:
        with self.db.session() as session:
            row = (
                session.query(WorkingStateRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, task_id=task_id)
                .one_or_none()
            )
            return self._view(row) if row is not None else None

    def compare_and_set(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        expected_version: int,
        state: dict[str, Any],
        event_id: str | None = None,
        field_sources: dict[str, str] | None = None,
    ) -> WorkingStateView:
        with self.db.session() as session:
            row = session.query(WorkingStateRow).filter_by(
                tenant_id=tenant_id, user_id=user_id, task_id=task_id
            ).one_or_none()
            if row is None:
                raise KeyError("working state not found")
            if row.version != expected_version:
                raise VersionConflictError(
                    f"working state version {row.version} != expected {expected_version}"
                )
            values: dict[str, Any] = {
                "state": dict(state),
                "version": expected_version + 1,
                "last_event_id": event_id,
            }
            if field_sources is not None:
                values["field_sources"] = dict(field_sources)
            updated_count = (
                session.query(WorkingStateRow)
                .filter_by(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    task_id=task_id,
                    version=expected_version,
                )
                .update(values, synchronize_session=False)
            )
            if updated_count != 1:
                raise VersionConflictError(
                    f"working state version changed while updating expected {expected_version}"
                )
            session.expire(row)
            session.refresh(row)
            session.flush()
            return self._view(row)

    @staticmethod
    def _view(row: WorkingStateRow) -> WorkingStateView:
        return WorkingStateView(
            working_state_id=row.working_state_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            task_id=row.task_id,
            version=row.version,
            state=dict(row.state or {}),
            field_sources=dict(row.field_sources or {}),
            last_event_id=row.last_event_id,
        )


class EpisodeRepository:
    """Episode snapshot/event persistence with tenant-bound monotonic sequence."""

    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        *,
        episode_id: str,
        tenant_id: str,
        user_id: str,
        task_id: str,
        session_id: str = "",
        goal: str = "",
    ) -> EpisodeSnapshotView:
        with self.db.session() as session:
            row = TaskEpisodeRow(
                    episode_id=episode_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    task_id=task_id,
                    session_id=session_id,
                    goal=goal,
                )
            session.add(row)
            session.flush()
            return self._snapshot_view(row)

    def get(
        self, *, tenant_id: str, user_id: str, episode_id: str
    ) -> EpisodeSnapshotView | None:
        with self.db.session() as session:
            row = (
                session.query(TaskEpisodeRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
                .one_or_none()
            )
            return self._snapshot_view(row) if row is not None else None

    def get_by_task_id(
        self, *, tenant_id: str, user_id: str, task_id: str, status: str | None = "ACTIVE"
    ) -> EpisodeSnapshotView | None:
        """Resolve a task to its active episode for the resume endpoint.

        The (tenant_id, user_id, task_id) tuple is the user-facing task key.
        When multiple rows exist, the most recently updated active episode wins.
        """
        with self.db.session() as session:
            query = session.query(TaskEpisodeRow).filter_by(
                tenant_id=tenant_id, user_id=user_id, task_id=task_id
            )
            if status is not None:
                query = query.filter_by(status=status)
            row = (
                query.order_by(
                    TaskEpisodeRow.status.desc(), TaskEpisodeRow.updated_at.desc()
                ).first()
            )
            return self._snapshot_view(row) if row is not None else None

    def append_event(
        self,
        *,
        episode_event_id: str,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        task_id: str,
        event_type: str,
        payload: dict[str, Any],
        source_event_id: str,
        expected_seq: int | None = None,
    ) -> EpisodeEventView:
        with self.db.session() as session:
            episode = (
                session.query(TaskEpisodeRow)
                .filter_by(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    episode_id=episode_id,
                    task_id=task_id,
                )
                .one_or_none()
            )
            if episode is None:
                raise KeyError("episode not found")
            existing = (
                session.query(EpisodeEventRow)
                .filter_by(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    episode_id=episode_id,
                    source_event_id=source_event_id,
                )
                .one_or_none()
            )
            if existing is not None:
                return self._view(existing)
            next_seq = episode.last_event_seq + 1
            if expected_seq is not None and expected_seq != next_seq:
                raise EpisodeSequenceConflictError(
                    f"episode next sequence {next_seq} != expected {expected_seq}"
                )
            row = EpisodeEventRow(
                episode_event_id=episode_event_id,
                tenant_id=tenant_id,
                user_id=user_id,
                episode_id=episode_id,
                task_id=task_id,
                seq_no=next_seq,
                event_type=event_type,
                payload=dict(payload),
                source_event_id=source_event_id,
            )
            session.add(row)
            episode.last_event_seq = next_seq
            session.flush()
            return self._view(row)

    def save_snapshot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        task_id: str,
        session_id: str,
        status: str,
        current_phase: str,
        goal: str,
        snapshot: dict[str, Any],
        last_event_seq: int,
        expected_snapshot_version: int,
        resume_token: str,
        stale_resources: list[str] | None = None,
        required_revalidation: list[str] | None = None,
        resource_versions: dict[str, str] | None = None,
    ) -> EpisodeSnapshotView:
        with self.db.session() as session:
            row = (
                session.query(TaskEpisodeRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
                .one_or_none()
            )
            if row is None:
                raise KeyError("episode not found")
            if row.task_id != task_id:
                raise KeyError("episode task mismatch")
            if row.snapshot_version != expected_snapshot_version:
                raise VersionConflictError(
                    "episode snapshot version "
                    f"{row.snapshot_version} != expected {expected_snapshot_version}"
                )
            if last_event_seq < row.last_event_seq:
                raise VersionConflictError("episode snapshot cannot move backwards")
            row.session_id = session_id
            row.status = status
            row.current_phase = current_phase
            row.goal = goal
            row.snapshot = dict(snapshot)
            row.snapshot_version = expected_snapshot_version + 1
            row.last_event_seq = last_event_seq
            row.resume_token_hash = hash_resume_token(resume_token)
            row.stale_resources = list(stale_resources or [])
            row.required_revalidation = list(required_revalidation or [])
            row.resource_versions = dict(resource_versions or {})
            session.flush()
            return self._snapshot_view(row)

    def resume(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        resume_token: str,
        expected_snapshot_version: int | None = None,
    ) -> EpisodeSnapshotView:
        with self.db.session() as session:
            row = (
                session.query(TaskEpisodeRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
                .one_or_none()
            )
            if row is None:
                raise KeyError("episode not found")
            if (
                expected_snapshot_version is not None
                and row.snapshot_version != expected_snapshot_version
            ):
                raise VersionConflictError(
                    "episode snapshot version "
                    f"{row.snapshot_version} != expected {expected_snapshot_version}"
                )
            if not resume_token_matches(resume_token, row.resume_token_hash):
                raise EpisodeResumeTokenError("invalid or stale resume token")
            return self._snapshot_view(row)

    def close(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        expected_snapshot_version: int,
        status: str,
        resume_token: str,
    ) -> EpisodeSnapshotView:
        with self.db.session() as session:
            row = (
                session.query(TaskEpisodeRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
                .one_or_none()
            )
            if row is None:
                raise KeyError("episode not found")
            if row.snapshot_version != expected_snapshot_version:
                raise VersionConflictError(
                    "episode snapshot version "
                    f"{row.snapshot_version} != expected {expected_snapshot_version}"
                )
            row.status = status
            row.snapshot_version = expected_snapshot_version + 1
            row.resume_token_hash = hash_resume_token(resume_token)
            session.flush()
            return self._snapshot_view(row)

    def list_events(
        self, *, tenant_id: str, user_id: str, episode_id: str
    ) -> list[EpisodeEventView]:
        with self.db.session() as session:
            rows = (
                session.query(EpisodeEventRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
                .order_by(EpisodeEventRow.seq_no.asc())
                .all()
            )
            return [self._view(row) for row in rows]

    @staticmethod
    def _view(row: EpisodeEventRow) -> EpisodeEventView:
        return EpisodeEventView(
            episode_event_id=row.episode_event_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            episode_id=row.episode_id,
            task_id=row.task_id,
            seq_no=row.seq_no,
            event_type=row.event_type,
            payload=dict(row.payload or {}),
            source_event_id=row.source_event_id,
        )

    @staticmethod
    def _snapshot_view(row: TaskEpisodeRow) -> EpisodeSnapshotView:
        view = EpisodeSnapshotView(
            episode_id=row.episode_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            task_id=row.task_id,
            session_id=row.session_id,
            status=row.status,
            current_phase=row.current_phase,
            goal=row.goal,
            snapshot=dict(row.snapshot or {}),
            snapshot_version=row.snapshot_version,
            last_event_seq=row.last_event_seq,
            stale_resources=list(row.stale_resources or []),
            required_revalidation=list(row.required_revalidation or []),
            resource_versions=dict(row.resource_versions or {}),
        )
        # A private attribute cannot be added to a frozen slots dataclass. The
        # public resume path therefore reads the row directly below.
        return view


class CandidateRepository:
    """Candidate staging access with a closed status transition table."""

    _TRANSITIONS = {
        "ACCUMULATING": {"ACCUMULATING", "CONFIRMED", "REJECTED", "REVIEW"},
        "REVIEW": {"REVIEW", "CONFIRMED", "REJECTED"},
        "CONFIRMED": {"CONFIRMED"},
        "REJECTED": {"REJECTED"},
    }

    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        *,
        candidate_id: str,
        tenant_id: str,
        user_id: str,
        memory_type: str,
        normalized_key: str,
        claim: dict[str, Any],
        scope_level: str,
        scope: str,
        status: str = "ACCUMULATING",
        evidence_refs: list[str] | None = None,
        supporting_episode_ids: list[str] | None = None,
        frequency: int = 1,
    ) -> CandidateView:
        if status not in CandidateRepository._TRANSITIONS:
            raise InvalidCandidateTransitionError(f"unknown candidate status: {status}")
        row = MemoryCandidateRow(
            candidate_id=candidate_id,
            tenant_id=tenant_id,
            user_id=user_id,
            memory_type=memory_type,
            normalized_key=normalized_key,
            claim=dict(claim),
            scope_level=scope_level,
            scope=scope,
            status=status,
            evidence_refs=list(evidence_refs or []),
            supporting_episode_ids=list(supporting_episode_ids or []),
            frequency=frequency,
        )
        with self.db.session() as session:
            session.add(row)
            session.flush()
            return self._view(row)

    def transition(
        self, *, tenant_id: str, user_id: str, candidate_id: str, status: str
    ) -> CandidateView:
        with self.db.session() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter_by(
                    tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id
                )
                .one_or_none()
            )
            if row is None:
                raise KeyError("candidate not found")
            allowed = self._TRANSITIONS.get(row.status, set())
            if status not in allowed or not can_transition(row.status, status):
                raise InvalidCandidateTransitionError(
                    f"candidate transition {row.status}->{status} is not allowed"
                )
            row.status = status
            session.flush()
            return self._view(row)

    def get(
        self, *, tenant_id: str, user_id: str, candidate_id: str
    ) -> CandidateView | None:
        with self.db.session() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter_by(
                    tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id
                )
                .one_or_none()
            )
            return self._view(row) if row is not None else None

    def list_for_review(
        self, *, tenant_id: str, user_id: str, status: str | None = None
    ) -> list[CandidateView]:
        """Return staging rows only through an explicit candidate-review path."""

        with self.db.session() as session:
            query = session.query(MemoryCandidateRow).filter_by(
                tenant_id=tenant_id, user_id=user_id, formation_status="CANDIDATE"
            )
            if status is not None:
                query = query.filter_by(status=status)
            return [self._view(row) for row in query.order_by(MemoryCandidateRow.created_at).all()]

    def find_by_key(
        self,
        *,
        tenant_id: str,
        user_id: str,
        normalized_key: str,
    ) -> CandidateView | None:
        """Return the most recent candidate with the same normalized key."""

        with self.db.session() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter_by(
                    tenant_id=tenant_id, user_id=user_id, normalized_key=normalized_key
                )
                .order_by(MemoryCandidateRow.created_at.desc())
                .first()
            )
            return self._view(row) if row is not None else None

    def search(
        self,
        *,
        tenant_id: str,
        user_id: str,
        normalized_key: str | None = None,
        include_candidates: bool = False,
    ) -> list[CandidateView]:
        """Search the repository with a safe default of no ordinary recall.

        Candidate rows are formation staging data.  Callers must opt in and
        use the returned rows as review input; the default path cannot recall
        them as normal memories.
        """

        if not include_candidates:
            return []
        with self.db.session() as session:
            query = session.query(MemoryCandidateRow).filter_by(
                tenant_id=tenant_id, user_id=user_id, formation_status="CANDIDATE"
            )
            if normalized_key:
                query = query.filter_by(normalized_key=normalized_key)
            return [self._view(row) for row in query.order_by(MemoryCandidateRow.created_at).all()]

    list_for_retrieval = search

    def add_evidence(
        self,
        *,
        tenant_id: str,
        user_id: str,
        candidate_id: str,
        event_id: str,
        episode_id: str,
        is_independent: bool = True,
    ) -> CandidateView:
        """Append an evidence reference to a candidate and optionally bump frequency.

        Independent evidence increments frequency; repeated statements from the
        same event/episode do not fabricate independent support.
        """

        with self.db.session() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter_by(
                    tenant_id=tenant_id, user_id=user_id, candidate_id=candidate_id
                )
                .one_or_none()
            )
            if row is None:
                raise KeyError("candidate not found")
            refs = set(row.evidence_refs or [])
            refs.add(event_id)
            row.evidence_refs = sorted(refs)
            episodes = set(row.supporting_episode_ids or [])
            episodes.add(episode_id)
            row.supporting_episode_ids = sorted(episodes)
            if is_independent:
                row.frequency = (row.frequency or 0) + 1
            session.flush()
            return self._view(row)

    @staticmethod
    def _view(row: MemoryCandidateRow) -> CandidateView:
        return CandidateView(
            candidate_id=row.candidate_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            status=row.status,
            formation_status=row.formation_status,
            normalized_key=row.normalized_key,
            scope_level=row.scope_level,
            scope=row.scope,
            claim=dict(row.claim or {}),
            confidence=row.confidence,
            utility=row.utility,
            stability=row.stability,
            frequency=row.frequency or 0,
            evidence_refs=list(row.evidence_refs or []),
            supporting_episode_ids=list(row.supporting_episode_ids or []),
        )


class EvidenceRepository:
    """Tenant-scoped evidence deduplication; stores references, not raw content."""

    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        evidence_id: str,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        memory_type: str,
        event_id: str,
        source_hash: str,
        content_ref: str,
        source_type: str,
    ) -> tuple[EvidenceView, bool]:
        with self.db.session() as session:
            existing = (
                session.query(MemoryEvidenceRow)
                .filter_by(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    memory_id=memory_id,
                    event_id=event_id,
                    source_hash=source_hash,
                )
                .one_or_none()
            )
            if existing is not None:
                return self._view(existing), False
            row = MemoryEvidenceRow(
                evidence_id=evidence_id,
                tenant_id=tenant_id,
                user_id=user_id,
                memory_id=memory_id,
                memory_type=memory_type,
                event_id=event_id,
                source_hash=source_hash,
                content_ref=content_ref,
                source_type=source_type,
                excerpt="",
                occurred_at=datetime.now(),
            )
            session.add(row)
            session.flush()
            return self._view(row), True

    @staticmethod
    def _view(row: MemoryEvidenceRow) -> EvidenceView:
        return EvidenceView(
            evidence_id=row.evidence_id,
            tenant_id=row.tenant_id or "",
            user_id=row.user_id or "",
            memory_id=row.memory_id,
            event_id=row.event_id,
            source_hash=row.source_hash,
            content_ref=row.content_ref,
        )


class ActivationRepository:
    """Tenant-scoped activation writes with memory version uniqueness."""

    def __init__(self, db: Database):
        self.db = db

    def record(
        self,
        *,
        activation_id: str,
        tenant_id: str,
        user_id: str,
        query_id: str,
        memory_id: str,
        task_id: str,
        intent: str,
        status: str,
        rank: int,
        initial_score: float,
        reranked_score: float,
        content_version: int,
        included_in_context: bool = False,
    ) -> ActivationView:
        row = MemoryActivationRow(
            activation_id=activation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            query_id=query_id,
            memory_id=memory_id,
            task_id=task_id,
            intent=intent,
            status=status,
            rank=rank,
            initial_score=initial_score,
            reranked_score=reranked_score,
            content_version=content_version,
            included_in_context=included_in_context,
        )
        with self.db.session() as session:
            session.add(row)
            session.flush()
            return self._view(row)

    @staticmethod
    def _view(row: MemoryActivationRow) -> ActivationView:
        return ActivationView(
            activation_id=row.activation_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            query_id=row.query_id,
            memory_id=row.memory_id,
            content_version=row.content_version,
        )


__all__ = [
    "ActivationRepository",
    "ActivationView",
    "CandidateRepository",
    "CandidateView",
    "EpisodeEventView",
    "EpisodeResumeTokenError",
    "EpisodeRepository",
    "EpisodeSnapshotView",
    "EpisodeSequenceConflictError",
    "EvidenceRepository",
    "EvidenceView",
    "InvalidCandidateTransitionError",
    "VersionConflictError",
    "WorkingStateRepository",
    "WorkingStateView",
]
