from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from memoryhub.adapter.vnext_api import vnext_dashboard
from memoryhub.adapter.vnext_schemas import DashboardRequest
from memoryhub.application.dashboard_service import DashboardService
from memoryhub.observability.trace_store import TraceStore


def test_dashboard_views_are_tenant_scoped_redacted_and_audited(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "vnext_benchmark.json").write_text(
        '{"runner_version":"v1","layers":{"retrieval":{"scope_leak_rate":0.0,'
        '"sample_results":[{"query":"must not leak"}]}}}',
        encoding="utf-8",
    )
    traces = TraceStore()
    traces.record_event(
        trace_id="trace-a", tenant_id="tenant-a", user_id="user-a", event_id="event-a",
        event_type="instruction", source_type="user", policy_action="ALLOW", source_hash="hash",
    )
    traces.record_infrastructure(
        trace_id="trace-a", tenant_id="tenant-a", user_id="user-a", operation="projection",
        outcome="succeeded", ids={"memory_id": "memory-a"},
    )
    service = DashboardService(trace_store=traces, results_root=results)

    explorer = service.view("explorer", tenant_id="tenant-a", user_id="user-a", actor_id="admin")
    evolution = service.view("evolution", tenant_id="tenant-a", user_id="user-a", actor_id="admin")
    debugger = service.view(
        "retrieval_debugger", tenant_id="tenant-a", user_id="user-a", actor_id="admin"
    )
    benchmark = service.view("benchmark", tenant_id="tenant-a", user_id="user-a", actor_id="admin")

    assert explorer["redacted"] is evolution["redacted"] is debugger["redacted"] is True
    assert explorer["items"][0]["ids"] == {"event_id": "event-a"}
    assert benchmark["layers"]["retrieval"] == {"scope_leak_rate": 0.0}
    assert "must not leak" not in str(benchmark)
    assert len(service.audit_log) == 4
    assert all(entry["redacted"] == "true" for entry in service.audit_log)


def test_dashboard_api_requires_admin_and_returns_redacted_projection() -> None:
    service = DashboardService()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(dashboard_service=service)))
    payload = DashboardRequest(request_id="req-1", tenant_id="tenant-a", user_id="user-a")

    with pytest.raises(HTTPException) as denied:
        asyncio.run(vnext_dashboard("explorer", payload, request, None))
    assert denied.value.status_code == 403

    response = asyncio.run(vnext_dashboard("explorer", payload, request, "admin"))
    assert response.redacted is True
    assert response.data["redacted"] is True
    assert service.audit_log[-1]["actor_id"] == "user-a"
