"""Tenant-scoped repositories for the vNext Authority storage slice.

Repositories own persistence invariants and transaction boundaries only. They
do not decide Policy, formation, ranking, or promotion; those belong to the
canonical application services built in later S1/S2 tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
class CandidateView:
    candidate_id: str
    tenant_id: str
    user_id: str
    status: str
    formation_status: str
    normalized_key: str
    scope: str


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
    ) -> WorkingStateView:
        row = WorkingStateRow(
            working_state_id=working_state_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            session_id=session_id,
            state=dict(state),
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
    ) -> WorkingStateView:
        with self.db.session() as session:
            row = (
                session.query(WorkingStateRow)
                .filter_by(tenant_id=tenant_id, user_id=user_id, task_id=task_id)
                .one_or_none()
            )
            if row is None:
                raise KeyError("working state not found")
            if row.version != expected_version:
                raise VersionConflictError(
                    f"working state version {row.version} != expected {expected_version}"
                )
            row.state = dict(state)
            row.version = expected_version + 1
            row.last_event_id = event_id
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
    ) -> None:
        with self.db.session() as session:
            session.add(
                TaskEpisodeRow(
                    episode_id=episode_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    task_id=task_id,
                    session_id=session_id,
                    goal=goal,
                )
            )

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
    ) -> CandidateView:
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
            if status not in allowed:
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

    @staticmethod
    def _view(row: MemoryCandidateRow) -> CandidateView:
        return CandidateView(
            candidate_id=row.candidate_id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            status=row.status,
            formation_status=row.formation_status,
            normalized_key=row.normalized_key,
            scope=row.scope,
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
    "EpisodeRepository",
    "EpisodeSequenceConflictError",
    "EvidenceRepository",
    "EvidenceView",
    "InvalidCandidateTransitionError",
    "VersionConflictError",
    "WorkingStateRepository",
    "WorkingStateView",
]
