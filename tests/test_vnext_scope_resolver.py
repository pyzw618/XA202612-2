"""Tests for S3-05 Authority validation and Scope-aware Conflict Resolver."""

from __future__ import annotations

from unittest.mock import MagicMock

from memoryhub.adapter.vnext_schemas import RetrievedMemory
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LifecycleLayer,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
)
from memoryhub.retrieval.scope_resolver import ScopeResolver, filter_blocked_statuses


def _memory(
    memory_id: str,
    *,
    version: int = 1,
    status: str = "ACTIVE",
    layer: LifecycleLayer = LifecycleLayer.LONG_TERM,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
    normalized_key: str | None = None,
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=memory_type,
        layer=layer,
        scope_level=scope_level,
        scope=scope,
        content_version=version,
        evolution_status=status,
        content={
            "text": f"content of {memory_id}",
            "normalized_key": normalized_key or memory_id,
        },
        score=0.5,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


class TestFilterBlockedStatuses:
    def test_deleted_dropped(self):
        deleted = _memory("m1", status=EvolutionStatus.DELETED.value)
        active = _memory("m2", status=EvolutionStatus.ACTIVE.value)
        selected, dropped = filter_blocked_statuses([deleted, active])
        assert len(selected) == 1
        assert selected[0].memory_id == "m2"
        assert len(dropped) == 1
        assert "DELETED" in dropped[0][1]

    def test_superseded_dropped(self):
        superseded = _memory("m1", status=EvolutionStatus.SUPERSEDED.value)
        active = _memory("m2", status=EvolutionStatus.ACTIVE.value)
        selected, dropped = filter_blocked_statuses([superseded, active])
        assert len(selected) == 1
        assert selected[0].memory_id == "m2"


class TestScopeResolver:
    def test_no_conflicts_single_selected(self):
        m = _memory("m1")
        resolver = ScopeResolver()
        result = resolver.resolve([m])
        assert len(result.selected) == 1
        assert len(result.conflict_groups) == 1

    def test_scope_precedence_task_wins(self):
        task = _memory(
            "m1",
            scope_level=MemoryScope.TASK,
            scope="TASK:t1",
            normalized_key="k1",
        )
        project = _memory(
            "m2",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p1",
            normalized_key="k1",
        )
        global_mem = _memory(
            "m3",
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            normalized_key="k1",
        )
        resolver = ScopeResolver()
        result = resolver.resolve([global_mem, project, task])
        assert len(result.selected) == 1
        assert result.selected[0].memory_id == "m1"
        assert len(result.dropped) == 2

    def test_project_wins_over_global(self):
        project = _memory(
            "m1",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p1",
            normalized_key="k1",
        )
        global_mem = _memory(
            "m2",
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            normalized_key="k1",
        )
        resolver = ScopeResolver()
        result = resolver.resolve([global_mem, project])
        assert result.selected[0].memory_id == "m1"

    def test_preferred_scope_exact_match(self):
        p1 = _memory(
            "m1",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p1",
            normalized_key="k1",
            version=1,
        )
        p2 = _memory(
            "m2",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p2",
            normalized_key="k1",
            version=2,
        )
        resolver = ScopeResolver()
        result = resolver.resolve(
            [p1, p2],
            preferred_scope_level=MemoryScope.PROJECT,
            preferred_scope="PROJECT:p2",
        )
        assert len(result.selected) == 1
        assert result.selected[0].memory_id == "m2"

    def test_newest_version_wins_within_same_scope(self):
        old = _memory("m1", version=1, normalized_key="k1")
        new = _memory("m2", version=2, normalized_key="k1")
        resolver = ScopeResolver()
        result = resolver.resolve([old, new])
        assert result.selected[0].memory_id == "m2"


class TestAuthorityValidation:
    def test_authority_checked_rejects_stale_version(self):
        projection = _memory("m1", version=1)
        authority = LongTermEnvelope(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id="m1",
            memory_type=MemoryType.SEMANTIC,
            normalized_key="m1",
            content={"text": "content of m1"},
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            evolution_status=EvolutionStatus.ACTIVE,
            content_version=3,
            evidence_refs=["e1"],
            confidence=0.9,
            utility=0.8,
        )
        repo = MagicMock()
        repo.get.return_value = authority
        resolver = ScopeResolver(authority_repository=repo, authority_checked=True)
        result = resolver.resolve([projection])
        assert len(result.selected) == 0
        assert len(result.invalid) == 1
        assert "older than Authority" in result.invalid[0].reason
        assert result.invalid[0].authority_version == 3

    def test_authority_checked_rejects_deleted_in_authority(self):
        projection = _memory("m1", version=2, status="ACTIVE")
        authority = LongTermEnvelope(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id="m1",
            memory_type=MemoryType.SEMANTIC,
            normalized_key="m1",
            content={"text": "content of m1"},
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
            evolution_status=EvolutionStatus.DELETED,
            content_version=2,
            evidence_refs=["e1"],
            confidence=0.9,
            utility=0.8,
        )
        repo = MagicMock()
        repo.get.return_value = authority
        resolver = ScopeResolver(authority_repository=repo, authority_checked=True)
        result = resolver.resolve([projection])
        assert len(result.selected) == 0
        assert len(result.invalid) == 1
        assert "DELETED" in result.invalid[0].reason

    def test_eventual_mode_does_not_call_authority(self):
        projection = _memory("m1", version=1, status="ACTIVE")
        repo = MagicMock()
        resolver = ScopeResolver(authority_repository=repo, authority_checked=False)
        result = resolver.resolve([projection])
        assert len(result.selected) == 1
        repo.get.assert_not_called()
