"""Application service for Working State patch/CAS semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.domain.contracts import WorkingPatch, WorkingSnapshot
from memoryhub.domain.working import (
    DEFAULT_SOURCE_PRIORITIES,
    apply_operations,
    compress_working_state,
)
from memoryhub.storage.vnext_repositories import WorkingStateRepository, WorkingStateView


@dataclass(frozen=True, slots=True)
class WorkingPatchResult:
    working_state: WorkingStateView
    applied_paths: tuple[str, ...]
    skipped_paths: tuple[str, ...]
    compressed_state: dict[str, Any]

    @property
    def version(self) -> int:
        return self.working_state.version

    @property
    def state(self) -> dict[str, Any]:
        return dict(self.working_state.state)


class WorkingStateService:
    """Apply field patches and let the repository enforce optimistic locking."""

    def __init__(
        self,
        repository: WorkingStateRepository,
        *,
        source_priorities: dict[str, int] | None = None,
    ) -> None:
        self.repository = repository
        self.source_priorities = dict(source_priorities or DEFAULT_SOURCE_PRIORITIES)

    def create(
        self,
        snapshot: WorkingSnapshot,
        *,
        working_state_id: str,
        project_id: str = "",
        field_sources: dict[str, str] | None = None,
    ) -> WorkingStateView:
        if not isinstance(snapshot, WorkingSnapshot):
            raise TypeError("working state creation requires WorkingSnapshot")
        return self.repository.create(
            working_state_id=working_state_id,
            tenant_id=snapshot.tenant_id,
            user_id=snapshot.user_id,
            task_id=snapshot.task_id,
            project_id=project_id,
            session_id=snapshot.session_id,
            version=snapshot.snapshot_version,
            state=self._snapshot_state(snapshot),
            field_sources=field_sources,
        )

    def apply_patch(
        self, patch: WorkingPatch, *, event_id: str | None = None
    ) -> WorkingPatchResult:
        if not isinstance(patch, WorkingPatch):
            raise TypeError("working state patch requires WorkingPatch")
        current = self.repository.get(
            tenant_id=patch.tenant_id, user_id=patch.user_id, task_id=patch.task_id
        )
        if current is None:
            raise KeyError("working state not found")
        # The repository performs the authoritative version check. Reading it
        # first lets us report source-priority skips without mutating storage.
        if current.version != patch.base_version:
            from memoryhub.storage.vnext_repositories import VersionConflictError

            raise VersionConflictError(
                f"working state version {current.version} != expected {patch.base_version}"
            )
        application = apply_operations(
            current.state,
            patch.operations,
            field_sources=current.field_sources,
            priorities=self.source_priorities,
        )
        if application.applied_paths:
            updated = self.repository.compare_and_set(
                tenant_id=patch.tenant_id,
                user_id=patch.user_id,
                task_id=patch.task_id,
                expected_version=patch.base_version,
                state=application.state,
                field_sources=application.field_sources,
                event_id=event_id or (patch.event_refs[-1] if patch.event_refs else None),
            )
        else:
            updated = current
        return WorkingPatchResult(
            working_state=updated,
            applied_paths=application.applied_paths,
            skipped_paths=application.skipped_paths,
            compressed_state=compress_working_state(updated.state),
        )

    # Short aliases keep the service ergonomic for adapters while the explicit
    # method remains the canonical name in the task contract.
    patch = apply_patch

    def compressed_snapshot(
        self, *, tenant_id: str, user_id: str, task_id: str, max_items: int = 32
    ) -> dict[str, Any]:
        current = self.repository.get(tenant_id=tenant_id, user_id=user_id, task_id=task_id)
        if current is None:
            raise KeyError("working state not found")
        return compress_working_state(current.state, max_items=max_items)

    @staticmethod
    def _snapshot_state(snapshot: WorkingSnapshot) -> dict[str, Any]:
        return {
            "current_goal": snapshot.current_goal,
            "current_step": snapshot.current_step,
            "pending_steps": list(snapshot.pending_steps),
            "completed_steps": list(snapshot.completed_steps),
            "constraints": list(snapshot.constraints),
            "active_entities": list(snapshot.active_entities),
            "blockers": list(snapshot.blockers),
            "recent_findings": list(snapshot.recent_findings),
            "recent_failures": list(snapshot.recent_failures),
            "next_action": snapshot.next_action,
        }


WorkingService = WorkingStateService


__all__ = ["WorkingPatchResult", "WorkingService", "WorkingStateService"]
