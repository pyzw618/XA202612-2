from __future__ import annotations

import pytest

from memoryhub.adapter.vnext_schemas import (
    APIError,
    APIErrorCode,
    ConsistencyMode,
    ForgetRequest,
    ForgetStatus,
    LegacySearchCompatibilityResponse,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
    RetrievedMemory,
)
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType, RetrievalIntent


def test_retrieval_request_supports_state_queries_and_authority_checked_mode() -> None:
    request = MemoryRetrievalRequest(
        request_id="req-001",
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-001",
        current_goal="complete report",
        current_step="draft",
        active_constraints=["use DOCX"],
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        intent_hint=RetrievalIntent.CURRENT_STATE,
        consistency=ConsistencyMode.AUTHORITY_CHECKED,
        page_size=10,
    )

    assert request.query == ""
    assert request.consistency is ConsistencyMode.AUTHORITY_CHECKED
    assert request.intent_hint is RetrievalIntent.CURRENT_STATE


def test_forget_requires_explicit_selector_and_confirmation_for_execution() -> None:
    with pytest.raises(ValueError, match="explicit selector"):
        ForgetRequest(request_id="req-001", idempotency_key="idem-001", tenant_id="t", user_id="u")

    with pytest.raises(ValueError, match="confirm=true"):
        ForgetRequest(
            request_id="req-001",
            idempotency_key="idem-001",
            tenant_id="t",
            user_id="u",
            target_memory_ids=["memory-001"],
            dry_run=False,
        )

    request = ForgetRequest(
        request_id="req-001",
        idempotency_key="idem-001",
        tenant_id="t",
        user_id="u",
        target_memory_ids=["memory-001"],
        dry_run=False,
        confirm=True,
    )
    assert request.confirm is True


def test_compatibility_response_is_a_shape_adapter_only() -> None:
    memory = RetrievedMemory(
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id="memory-001",
        memory_type=MemoryType.PREFERENCE,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        content_version=2,
        evolution_status="ACTIVE",
        content={"value": "DOCX"},
        score=0.9,
    )
    response = MemoryRetrievalResponse(
        request_id="req-001",
        trace_id="trace-001",
        intent=RetrievalIntent.PREFERENCE,
        selected_memories=[memory],
        total_count=1,
    )

    legacy = LegacySearchCompatibilityResponse.from_vnext(response)

    assert legacy.results[0]["memory_id"] == "memory-001"
    assert legacy.results[0]["memory_level"] == "long_term"
    assert legacy.results[0]["metadata"]["content_version"] == 2
    assert legacy.trace_id == "trace-001"


def test_error_contract_has_stable_code_and_safe_retry_signal() -> None:
    error = APIError(
        code=APIErrorCode.PARTIAL_RESULT,
        message="some retrieval channels are unavailable",
        retryable=True,
        trace_id="trace-001",
    )

    assert error.api_version == "vnext/v1"
    assert error.code is APIErrorCode.PARTIAL_RESULT
    assert error.retryable is True
    assert ForgetStatus.VERIFIED.value == "VERIFIED"
