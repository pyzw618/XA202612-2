"""Conflict resolution primitives shared by preference and knowledge flows."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from memoryhub.adapter.schemas import ConflictDecision, ConflictRecord, MemoryStatus
from memoryhub.core.memory.evidence import EvidenceMerger


class ConflictResolver:
    """Apply deterministic conflict decisions; persistence is optional and owner-scoped."""

    def __init__(
        self, llm_client=None, *, conflict_repo=None, write_service=None
    ) -> None:
        self.llm_client = llm_client
        self.conflict_repo = conflict_repo
        self.write_service = write_service

    def resolve(
        self, conflict: ConflictRecord, old_memory, new_memory
    ) -> ConflictRecord:
        decision = self.auto_resolve(conflict)
        if decision == ConflictDecision.OVERRIDE:
            result_id = self.apply_override(old_memory, new_memory)
        elif decision == ConflictDecision.MERGE:
            merged = self.apply_merge(old_memory, new_memory)
            result_id = getattr(merged, "memory_id", "")
            if result_id and self.write_service is not None:
                self.write_service.upsert_memory(merged)
        elif decision == ConflictDecision.COEXIST:
            _, result_id = self.apply_coexist(old_memory, new_memory)
        else:
            result_id = ""
        conflict.decision = decision
        conflict.result_memory_id = result_id
        conflict.resolved_at = (
            None if decision == ConflictDecision.PENDING else datetime.now(timezone.utc)
        )
        conflict.reason = conflict.reason or f"automatic decision: {decision.value}"
        if self.conflict_repo is not None:
            self.conflict_repo.save(conflict)
        return conflict

    def auto_resolve(self, conflict: ConflictRecord) -> ConflictDecision:
        if conflict.decision != ConflictDecision.PENDING:
            return conflict.decision
        if "explicit_feedback" in (conflict.reason or ""):
            return ConflictDecision.OVERRIDE
        if (
            conflict.memory_type == "knowledge"
            and conflict.conflict_field == "semantic_equivalence"
        ):
            return ConflictDecision.MERGE
        if (
            "scope" not in (conflict.conflict_field or "")
            and conflict.old_content
            and conflict.new_content
        ):
            return ConflictDecision.OVERRIDE
        return ConflictDecision.PENDING

    def apply_override(self, old_memory, new_memory) -> str:
        """Create a versioned successor instead of writing a bare replacement."""
        old = old_memory
        if isinstance(old_memory, str):
            repo = (
                getattr(self.write_service, "pref_repo", None)
                if getattr(new_memory, "memory_type", "") == "preference"
                else getattr(self.write_service, "know_repo", None)
            )
            old = repo.get_by_id(old_memory) if repo is not None else None
        successor = deepcopy(new_memory)
        if old is not None:
            old.status = MemoryStatus.ARCHIVED
            old.updated_at = datetime.now(timezone.utc)
            successor.parent_id = old.memory_id
            if hasattr(successor, "root_id"):
                successor.root_id = getattr(old, "root_id", "") or old.memory_id
            successor.version = max(1, getattr(old, "version", 1)) + 1
            successor.evidences = EvidenceMerger().normalize_and_merge(
                [
                    *getattr(old, "evidences", []),
                    *getattr(successor, "evidences", []),
                ]
            )
            if self.write_service is not None:
                self.write_service.upsert_memory(old)
        successor.status = MemoryStatus.ACTIVE
        successor.updated_at = datetime.now(timezone.utc)
        if self.write_service is not None:
            self.write_service.upsert_memory(successor)
        return successor.memory_id

    def apply_merge(self, old_memory, new_memory):
        merged = deepcopy(new_memory)
        merged.memory_id = new_memory.memory_id
        merged.parent_id = old_memory.memory_id
        merged.root_id = getattr(old_memory, "root_id", "") or old_memory.memory_id
        merged.version = max(1, getattr(old_memory, "version", 1)) + 1
        if hasattr(old_memory, "evidences"):
            merged.evidences = EvidenceMerger().normalize_and_merge(
                [
                    *getattr(old_memory, "evidences", []),
                    *getattr(new_memory, "evidences", []),
                ]
            )
        merged.status = MemoryStatus.ACTIVE
        merged.updated_at = datetime.now(timezone.utc)
        return merged

    def apply_coexist(self, old_memory, new_memory) -> tuple[str, str]:
        if self.write_service is not None:
            self.write_service.upsert_memory(old_memory)
            self.write_service.upsert_memory(new_memory)
        return old_memory.memory_id, new_memory.memory_id

    def manual_resolve(
        self, conflict_id: str, decision: ConflictDecision, reason: str
    ) -> ConflictRecord:
        if self.conflict_repo is None:
            raise RuntimeError("conflict repository is not configured")
        pending = next(
            (
                item
                for item in self.conflict_repo.list_all(status="pending")
                if item.conflict_id == conflict_id
            ),
            None,
        )
        if pending is None:
            raise KeyError(conflict_id)
        pending.decision = decision
        pending.reason = reason
        pending.resolved_at = datetime.now(timezone.utc)
        self.conflict_repo.save(pending)
        return pending
