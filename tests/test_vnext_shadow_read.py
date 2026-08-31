from __future__ import annotations

from dataclasses import dataclass

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.application.shadow_read_service import ShadowReadService
from memoryhub.observability.trace_store import TraceStore


def _reflection_service() -> ReflectionService:
    return ReflectionService(model=DeterministicReflectionModel())


@dataclass
class Item:
    memory_id: str
    tenant_id: str = "tenant-1"
    user_id: str = "user-1"
    content_version: int = 1
    scope: str = "GLOBAL"
    status: str = "ACTIVE"


def _request() -> MemoryRetrievalRequest:
    return MemoryRetrievalRequest(
        request_id="request-shadow-1",
        tenant_id="tenant-1",
        user_id="user-1",
        query="private query must not be reported",
        token_budget=256,
    )


def test_dual_read_returns_legacy_and_records_redacted_deltas() -> None:
    trace_store = TraceStore()
    service = ShadowReadService(reflection_service=_reflection_service(), trace_store=trace_store)
    legacy = [Item("memory-1")]
    vnext = [Item("memory-2")]

    result = service.dual_read(
        _request(),
        legacy_reader=lambda request: legacy,
        vnext_reader=lambda request: vnext,
    )

    assert result.legacy_response == legacy
    assert result.report.legacy_result_returned is True
    assert any(item.kind == "RESULT_SET_MISMATCH" for item in result.report.differences)
    assert result.report.legacy_ids_hash != "memory-1"
    assert all("private query" not in str(span) for span in trace_store.records)
    assert trace_store.records[0].classification["mode"] == "dual-read"


def test_dual_read_fails_open_to_legacy_when_vnext_errors() -> None:
    service = ShadowReadService(reflection_service=_reflection_service())
    legacy = [{"memory_id": "memory-1", "tenant_id": "tenant-1"}]

    result = service.dual_read(
        _request(),
        legacy_reader=lambda request: legacy,
        vnext_reader=lambda request: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    assert result.legacy_response == legacy
    assert result.report.vnext_error == "RuntimeError"
    assert result.report.safe is False


def test_dual_read_detects_policy_and_forget_leaks() -> None:
    service = ShadowReadService(reflection_service=_reflection_service())
    result = service.dual_read(
        _request(),
        legacy_reader=lambda request: [],
        vnext_reader=lambda request: [
            {"memory_id": "deleted", "tenant_id": "other", "status": "DELETED"}
        ],
    )

    assert result.report.policy_leak_count == 1
    assert result.report.forget_leak_count == 1
    assert result.report.safe is False
    assert service.report.policy_leak_count == 1
