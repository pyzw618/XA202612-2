"""Application service for append-only Episodes and resumable snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.domain.contracts import EpisodeEventContract, EpisodeSnapshot, EpisodeStatus
from memoryhub.domain.episode import (
    allowed_close_status,
    new_resume_token,
    replay_episode,
    stale_resource_ids,
)
from memoryhub.storage.vnext_repositories import (
    EpisodeEventView,
    EpisodeRepository,
    EpisodeSnapshotView,
)


@dataclass(frozen=True, slots=True)
class EpisodeSnapshotResult:
    snapshot: EpisodeSnapshot
    resume_token: str


@dataclass(frozen=True, slots=True)
class EpisodeResumeResult:
    snapshot: EpisodeSnapshot
    restored_state: dict[str, Any]
    stale_resources: list[str]
    required_revalidation: list[str]
    resume_token: str


class EpisodeStateService:
    """Coordinate repository CAS with domain replay and resource checks."""

    def __init__(self, repository: EpisodeRepository) -> None:
        self.repository = repository

    def create(
        self,
        *,
        episode_id: str,
        tenant_id: str,
        user_id: str,
        task_id: str,
        project_id: str = "",
        session_id: str = "",
        goal: str = "",
    ) -> EpisodeSnapshotView:
        return self.repository.create(
            episode_id=episode_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            project_id=project_id,
            session_id=session_id,
            goal=goal,
        )

    def append(
        self, event: EpisodeEventContract, *, expected_seq: int | None = None
    ) -> EpisodeEventView:
        if not isinstance(event, EpisodeEventContract):
            raise TypeError("episode append requires EpisodeEventContract")
        return self.repository.append_event(
            episode_event_id=f"{event.episode_id}:{event.seq_no}:{event.source_event_id}",
            tenant_id=event.tenant_id,
            user_id=event.user_id,
            episode_id=event.episode_id,
            task_id=event.task_id,
            event_type=event.event_type,
            payload=event.payload,
            source_event_id=event.source_event_id,
            expected_seq=expected_seq or event.seq_no,
        )

    append_event = append

    def snapshot(
        self,
        snapshot: EpisodeSnapshot,
        *,
        resume_token: str | None = None,
        expected_snapshot_version: int | None = None,
        resource_versions: dict[str, str] | None = None,
    ) -> EpisodeSnapshotResult:
        if not isinstance(snapshot, EpisodeSnapshot):
            raise TypeError("episode snapshot requires EpisodeSnapshot")
        token = resume_token or new_resume_token()
        expected = expected_snapshot_version or snapshot.snapshot_version
        stored = self.repository.save_snapshot(
            tenant_id=snapshot.tenant_id,
            user_id=snapshot.user_id,
            episode_id=snapshot.episode_id,
            task_id=snapshot.task_id,
            session_id=snapshot.session_id,
            status=snapshot.status.value,
            current_phase=snapshot.current_phase,
            goal=snapshot.goal,
            snapshot=self._snapshot_data(snapshot),
            last_event_seq=snapshot.last_event_seq,
            expected_snapshot_version=expected,
            resume_token=token,
            stale_resources=snapshot.stale_resources,
            required_revalidation=snapshot.required_revalidation,
            resource_versions=resource_versions,
        )
        return EpisodeSnapshotResult(self._to_contract(stored), token)

    save_snapshot = snapshot

    def resume(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        resume_token: str,
        expected_snapshot_version: int | None = None,
        current_resource_versions: dict[str, str] | None = None,
    ) -> EpisodeResumeResult:
        stored = self.repository.resume(
            tenant_id=tenant_id,
            user_id=user_id,
            episode_id=episode_id,
            resume_token=resume_token,
            expected_snapshot_version=expected_snapshot_version,
        )
        stale = list(stored.stale_resources)
        if current_resource_versions is not None:
            stale = sorted(
                set(stale)
                | set(stale_resource_ids(stored.resource_versions, current_resource_versions))
            )
        required = sorted(set(stored.required_revalidation) | set(stale))
        events = self.repository.list_events(
            tenant_id=tenant_id, user_id=user_id, episode_id=episode_id
        )
        restored = replay_episode(stored.snapshot, [self._event_data(event) for event in events])
        restored["status"] = stored.status
        restored["stale_resources"] = stale
        restored["required_revalidation"] = required
        contract = self._to_contract(
            stored,
            stale_resources=stale,
            required_revalidation=required,
            restored=restored,
        )
        return EpisodeResumeResult(contract, restored, stale, required, resume_token)

    def close(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        expected_snapshot_version: int,
        status: EpisodeStatus = EpisodeStatus.COMPLETED,
    ) -> EpisodeSnapshotResult:
        current = self.repository.get(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
        if current is None:
            raise KeyError("episode not found")
        if not allowed_close_status(current.status, status.value):
            raise ValueError(f"episode transition {current.status}->{status.value} is not allowed")
        token = new_resume_token()
        closed = self.repository.close(
            tenant_id=tenant_id,
            user_id=user_id,
            episode_id=episode_id,
            expected_snapshot_version=expected_snapshot_version,
            status=status.value,
            resume_token=token,
        )
        return EpisodeSnapshotResult(self._to_contract(closed), token)

    def replay(self, *, tenant_id: str, user_id: str, episode_id: str) -> dict[str, Any]:
        current = self.repository.get(tenant_id=tenant_id, user_id=user_id, episode_id=episode_id)
        if current is None:
            raise KeyError("episode not found")
        events = self.repository.list_events(
            tenant_id=tenant_id, user_id=user_id, episode_id=episode_id
        )
        return replay_episode(current.snapshot, [self._event_data(event) for event in events])

    def resume_by_task(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        resume_token: str,
        expected_snapshot_version: int | None = None,
        current_resource_versions: dict[str, str] | None = None,
    ) -> EpisodeResumeResult:
        """Resolve task_id → episode and resume; exposes version conflicts to the adapter."""
        current = self.repository.get_by_task_id(
            tenant_id=tenant_id, user_id=user_id, task_id=task_id
        )
        if current is None:
            raise KeyError("task not found")
        return self.resume(
            tenant_id=tenant_id,
            user_id=user_id,
            episode_id=current.episode_id,
            resume_token=resume_token,
            expected_snapshot_version=expected_snapshot_version,
            current_resource_versions=current_resource_versions,
        )

    @staticmethod
    def _snapshot_data(snapshot: EpisodeSnapshot) -> dict[str, Any]:
        return {
            "current_phase": snapshot.current_phase,
            "goal": snapshot.goal,
            "pending_steps": list(snapshot.pending_steps),
            "completed_steps": list(snapshot.completed_steps),
            "constraints": list(snapshot.constraints),
            "last_event_seq": snapshot.last_event_seq,
        }

    @staticmethod
    def _event_data(event: EpisodeEventView) -> dict[str, Any]:
        return {"seq_no": event.seq_no, "event_type": event.event_type, "payload": event.payload}

    @staticmethod
    def _to_contract(
        view: EpisodeSnapshotView,
        *,
        stale_resources: list[str] | None = None,
        required_revalidation: list[str] | None = None,
        restored: dict[str, Any] | None = None,
    ) -> EpisodeSnapshot:
        state = restored or view.snapshot
        return EpisodeSnapshot(
            tenant_id=view.tenant_id,
            user_id=view.user_id,
            episode_id=view.episode_id,
            task_id=view.task_id,
            session_id=view.session_id,
            status=EpisodeStatus(view.status),
            current_phase=str(state.get("current_phase") or view.current_phase or "active"),
            goal=str(state.get("goal") or view.goal or view.task_id),
            pending_steps=list(state.get("pending_steps", [])),
            completed_steps=list(state.get("completed_steps", [])),
            constraints=list(state.get("constraints", [])),
            last_event_seq=int(state.get("last_event_seq", view.last_event_seq)),
            snapshot_version=view.snapshot_version,
            stale_resources=list(stale_resources or view.stale_resources),
            required_revalidation=list(required_revalidation or view.required_revalidation),
        )


EpisodeService = EpisodeStateService


__all__ = [
    "EpisodeResumeResult",
    "EpisodeService",
    "EpisodeSnapshotResult",
    "EpisodeStateService",
]
