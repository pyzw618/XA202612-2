"""Asynchronous Projection Outbox worker for Preference and Knowledge memories."""

from __future__ import annotations

import logging
import time
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
        metrics=None,
        trace_store=None,
    ) -> None:
        self.pref_repo = pref_repo
        self.know_repo = know_repo
        self.memory_write_service = memory_write_service
        db = getattr(pref_repo, "db", None)
        self.outbox_repo = outbox_repo or MemoryProjectionOutboxRepository(db)
        self.base_retry_seconds = base_retry_seconds
        self.max_retry_seconds = max_retry_seconds
        self.metrics = metrics
        self.trace_store = trace_store

    def run_once(self, *, limit: int = 100) -> ProjectionOutboxResult:
        result = ProjectionOutboxResult()
        for item in self.outbox_repo.claim_ready(limit=limit):
            started = time.perf_counter()
            try:
                self._project(item)
            except Exception as exc:
                code = self._error_code(exc)
                self.outbox_repo.mark_failed(
                    item.outbox_id,
                    error_code=code,
                    lease_token=item.lease_token,
                )
                result.failed.append(item.outbox_id)
                if self.metrics is not None:
                    self.metrics.record_projection(success=False)
                logger.warning("projection outbox %s failed: %s", item.outbox_id, code)
            else:
                self.outbox_repo.mark_succeeded(
                    item.outbox_id, lease_token=item.lease_token
                )
                self._bump_projection_version(item)
                result.succeeded.append(item.outbox_id)
                if self.metrics is not None:
                    self.metrics.record_projection(
                        success=True,
                        lag_ms=(time.perf_counter() - started) * 1000,
                    )
            if self.trace_store is not None:
                self.trace_store.record_infrastructure(
                    trace_id=f"projection-{item.outbox_id}",
                    tenant_id=item.tenant_id or "unknown",
                    user_id=item.user_id or "unknown",
                    operation="projection",
                    outcome="succeeded" if item.outbox_id in result.succeeded else "failed",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    ids={"outbox_id": item.outbox_id, "memory_id": item.memory_id},
                )
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

    def _bump_projection_version(self, item: ProjectionOutboxItem) -> None:
        """Mirror the projected content version back to the Authority row."""
        with self.outbox_repo.db.session() as session:
            self.outbox_repo.update_projection_version(
                item.memory_id,
                item.memory_type,
                item.content_version,
                session=session,
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
