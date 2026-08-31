"""Tests for S3-08 unified Retrieval Service, Activation and Retrieval Log."""

from __future__ import annotations

import pytest

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.retrieval_service import RetrievalResult, RetrievalService
from memoryhub.domain.contracts import (
    ActivationStatus,
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.planner import RetrievalPlan
from memoryhub.storage.database import Database
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
    RetrievalLogRepository,
)


def _memory(
    memory_id: str,
    *,
    score: float = 0.5,
    version: int = 1,
    layer: LifecycleLayer = LifecycleLayer.LONG_TERM,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
    status: str = "ACTIVE",
    content: dict | None = None,
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
        content=content or {"text": f"content of {memory_id}"},
        score=score,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


@pytest.fixture
def request_obj():
    return MemoryRetrievalRequest(
        request_id="r1",
        tenant_id="tenant-1",
        user_id="user-1",
        query="how to format report",
        task_id="task-1",
        intent_hint=RetrievalIntent.PREFERENCE,
        token_budget=1000,
    )


@pytest.fixture
def plan():
    return RetrievalPlan(
        intent=RetrievalIntent.PREFERENCE,
        enabled_channels=["metadata"],
        top_k=5,
    )


def _fixed_channel_executor(candidates: dict[str, list[RetrievedMemory]]):
    def executor(request, plan, channel):
        return candidates.get(channel, [])
    return executor


class TestRetrievalService:
    def test_retrieve_records_activation_and_trace(self, request_obj):
        candidates = {
            "metadata": [
                _memory("m1", score=0.9, memory_type=MemoryType.PREFERENCE),
                _memory("m2", score=0.7, memory_type=MemoryType.SEMANTIC),
            ]
        }
        service = RetrievalService(
            channel_executors={"metadata": _fixed_channel_executor(candidates)}
        )
        result = service.retrieve(request_obj)

        assert isinstance(result, RetrievalResult)
        assert result.response.request_id == request_obj.request_id
        assert result.response.trace_id == request_obj.request_id
        assert result.response.intent is RetrievalIntent.PREFERENCE
        assert result.retrieval_log_id.startswith("rl-")
        assert result.activations
        assert any(a.memory_id == "m1" for a in result.activations)
        assert result.response.context.rendered_context
        assert result.response.total_count > 0

    def test_retrieve_degrades_missing_channel(self, request_obj):
        service = RetrievalService(channel_executors={})
        result = service.retrieve(request_obj)

        # Missing executor returns empty channel, no crash.
        assert result.response.completeness in ("PARTIAL", "NONE")
        assert result.response.total_count == 0
        assert result.retrieval_log_id.startswith("rl-")

    def test_retrieval_log_persisted(self, request_obj, tmp_path):
        db = Database(db_path=str(tmp_path / "retrieval_test.db"))
        db.init_schema()
        log_repo = RetrievalLogRepository(db)
        act_repo = ActivationRepository(db)

        candidates = {
            "metadata": [
                _memory("m1", score=0.9, memory_type=MemoryType.PREFERENCE),
            ]
        }
        service = RetrievalService(
            channel_executors={"metadata": _fixed_channel_executor(candidates)},
            activation_repository=act_repo,
            retrieval_log_repository=log_repo,
        )
        service.retrieve(request_obj)

        # Verify retrieval log row exists.
        with db.session() as session:
            from memoryhub.storage.models import RetrievalLogRow

            rows = session.query(RetrievalLogRow).all()
            assert len(rows) == 1
            log = rows[0]
            assert log.query_id == request_obj.request_id
            assert log.trace_id == request_obj.request_id
            assert log.intent == RetrievalIntent.PREFERENCE.value
            assert log.candidate_count > 0
            assert log.latency_ms >= 0
            assert log.plan["selected_memory_ids"] == ["m1"]

        # Verify activation rows.
        with db.session() as session:
            from memoryhub.storage.models import MemoryActivationRow

            acts = session.query(MemoryActivationRow).all()
            assert len(acts) >= 1
            assert any(a.memory_id == "m1" for a in acts)
            assert all(a.status in {s.value for s in ActivationStatus} for a in acts)

    def test_search_and_context_convenience_methods(self, request_obj):
        candidates = {
            "metadata": [
                _memory("m1", score=0.9, memory_type=MemoryType.PREFERENCE),
            ]
        }
        service = RetrievalService(
            channel_executors={"metadata": _fixed_channel_executor(candidates)}
        )

        response = service.search(request_obj)
        assert response.request_id == request_obj.request_id
        assert response.context.relevant_memory_ids

        payload = service.context(request_obj)
        assert payload.rendered_context
        assert payload.relevant_memory_ids

    def test_retrieval_trace_span_recorded(self, request_obj):
        from memoryhub.observability.trace_store import TraceStore

        trace_store = TraceStore()
        candidates = {
            "metadata": [
                _memory("m1", score=0.9, memory_type=MemoryType.PREFERENCE),
            ]
        }
        service = RetrievalService(
            channel_executors={"metadata": _fixed_channel_executor(candidates)},
            trace_store=trace_store,
        )
        service.retrieve(request_obj)

        spans = trace_store.list_by_trace(request_obj.request_id)
        assert len(spans) == 1
        span = spans[0]
        assert span.kind == "RETRIEVAL"
        assert span.tenant_id == "tenant-1"
        assert span.ids["query_id"] == request_obj.request_id
        assert "intent" in span.classification
        assert "latency_ms" in span.scores

    def test_dropped_deleted_memories_not_activated(self, request_obj):
        candidates = {
            "metadata": [
                _memory("m1", status="DELETED"),
                _memory("m2", status="ACTIVE"),
            ]
        }
        service = RetrievalService(
            channel_executors={"metadata": _fixed_channel_executor(candidates)}
        )
        result = service.retrieve(request_obj)

        activated_ids = {a.memory_id for a in result.activations}
        assert "m1" not in activated_ids
        assert "m2" in activated_ids
