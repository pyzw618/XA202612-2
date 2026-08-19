"""Asynchronous Projection Outbox worker for Preference and Knowledge memories."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memoryhub.storage.memory_metadata import (
    MemoryProjectionOutboxRepository,
    ProjectionOutboxItem,
)

logger = logging.getLogger(__name__)


@dataclass
class ProjectionOutboxResult:
    """One worker pass result, suitable for metrics and replay diagnostics."""

    succeeded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: int = 0


class ProjectionOutboxWorker:
    """Project committed Domain Writer records without repeating business writes."""

    def __init__(
        self,
        *,
        pref_repo,
        know_repo,
        memory_write_service,
        outbox_repo: MemoryProjectionOutboxRepository | None = None,
        base_retry_seconds: int = 5,
        max_retry_seconds: int = 3600,
    ) -> None:
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.memory_write_service = memory_write_service
        db = getattr(pref_repo, "db", None)
        self.outbox_repo = outbox_repo or MemoryProjectionOutboxRepository(db)
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds

    def run_once(self, *, limit: int = 100) -> ProjectionOutboxResult:
        result = ProjectionOutboxResult()
        for item in self.outbox_repo.claim_ready(limit=limit):
            try:
                self._project(item)
            except Exception as exc:
                code = self._error_code(exc)
                self.outbox_repo.mark_failed(
                    item.outbox_id,
                    error_code=code,
                    base_delay_seconds=self.base_retry_seconds,
                    max_delay_seconds=self.max_retry_seconds,
                )
                result.failed.append(item.outbox_id)
                logger.warning("projection outbox %s failed: %s", item.outbox_id, code)
            else:
                self.outbox_repo.mark_succeeded(item.outbox_id)
                result.succeeded.append(item.outbox_id)
        return result

    def replay(
        self, outbox_ids: list[str] | None = None, *, limit: int = 100
    ) -> ProjectionOutboxResult:
        self.outbox_repo.replay(outbox_ids)
        return self.run_once(limit=limit)

    def _project(self, item: ProjectionOutboxItem) -> None:
        if item.memory_type == "preference":
            memory = self.pref_repo.get_by_id(item.memory_id)
        elif item.memory_type == "knowledge":
            memory = self.know_repo.get_by_id(item.memory_id)
        else:
            raise ValueError("projection.unsupported_memory_type")
        if memory is None:
            raise LookupError("projection.memory_not_found")
        if item.operation not in {"upsert", "delete"}:
            raise ValueError("projection.unsupported_operation")
        self.memory_write_service.sync_memory(
            memory,
            remove=item.operation == "delete",
        )

    @staticmethod
    def _error_code(exc: Exception) -> str:
        message = str(exc).lower()
        if "embedding" in message:
            return "projection.embedding_failed"
        if "vector" in message or "milvus" in message:
            return "projection.vector_failed"
        if "memory_not_found" in message:
            return "projection.memory_not_found"
        if "unsupported" in message:
            return "projection.unsupported_operation"
        return "projection.failed"
