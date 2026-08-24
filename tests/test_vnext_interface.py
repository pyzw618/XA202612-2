from __future__ import annotations

import pytest

from memoryhub.adapter.schemas import SearchRequest, SearchResponse
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


# ---------------------------------------------------------------------------
# S3-01: Retrieval vNext request/response compatibility
# ---------------------------------------------------------------------------


def test_vnext_request_from_legacy_search_request_maps_scope_and_intent() -> None:
    legacy = SearchRequest(
        user_id="user-a",
        query="weekly report format",
        project_id="proj-1",
        top_k=10,
        level="long",
        session_id="session-1",
    )
    vnext = MemoryRetrievalRequest.from_legacy_search_request(legacy, tenant_id="tenant-a")

    assert vnext.tenant_id == "tenant-a"
    assert vnext.user_id == "user-a"
    assert vnext.query == "weekly report format"
    assert vnext.scope_level is MemoryScope.PROJECT
    assert vnext.scope == "PROJECT:proj-1"
    assert vnext.intent_hint is RetrievalIntent.MIXED
    assert vnext.page_size == 10
    assert vnext.session_id == "session-1"


def test_legacy_level_short_maps_to_current_state_intent() -> None:
    legacy = SearchRequest(user_id="u", query="what is my current task", level="short")
    vnext = MemoryRetrievalRequest.from_legacy_search_request(legacy)
    assert vnext.intent_hint is RetrievalIntent.CURRENT_STATE


def test_legacy_memory_type_preference_maps_to_preference_intent() -> None:
    legacy = SearchRequest(user_id="u", query="preferred format", memory_types=["preference"])
    vnext = MemoryRetrievalRequest.from_legacy_search_request(legacy)
    assert vnext.intent_hint is RetrievalIntent.PREFERENCE


def test_vnext_response_to_legacy_search_response_preserves_results() -> None:
    response = MemoryRetrievalResponse(
        request_id="req-1",
        trace_id="trace-1",
        intent=RetrievalIntent.PREFERENCE,
        selected_memories=[
            RetrievedMemory(
                tenant_id="t",
                user_id="u",
                memory_id="pref-1",
                memory_type=MemoryType.PREFERENCE,
                layer=LifecycleLayer.LONG_TERM,
                scope_level=MemoryScope.GLOBAL,
                scope="GLOBAL",
                content_version=1,
                evolution_status="ACTIVE",
                content={"text": "use DOCX for formal reports"},
                score=0.95,
                source_ids=["vector"],
            ),
            RetrievedMemory(
                tenant_id="t",
                user_id="u",
                memory_id="fact-1",
                memory_type=MemoryType.SEMANTIC,
                layer=LifecycleLayer.LONG_TERM,
                scope_level=MemoryScope.PROJECT,
                scope="PROJECT:reporting",
                content_version=2,
                evolution_status="ACTIVE",
                content={"content": "weekly report deadline is Friday"},
                score=0.88,
                source_ids=["keyword", "metadata"],
            ),
        ],
        total_count=2,
    )

    legacy: SearchResponse = response.to_legacy_search_response(latency_ms=12.5)

    assert legacy.total_count == 2
    assert len(legacy.results) == 2
    assert legacy.latency_ms == 12.5
    assert legacy.results[0].memory_id == "pref-1"
    assert legacy.results[0].memory_type == "preference"
    assert legacy.results[0].memory_level == "long"
    assert legacy.results[0].source == "vector"
    assert legacy.results[1].memory_id == "fact-1"
    assert legacy.results[1].memory_type == "fact"
    assert legacy.results[1].source == "keyword+metadata"
    assert len(legacy.preferences) == 1
    assert len(legacy.facts) == 1


def test_legacy_compatibility_response_populates_typed_lists() -> None:
    response = MemoryRetrievalResponse(
        request_id="req-1",
        trace_id="trace-1",
        intent=RetrievalIntent.SEMANTIC_FACT,
        selected_memories=[
            RetrievedMemory(
                tenant_id="t",
                user_id="u",
                memory_id="proc-1",
                memory_type=MemoryType.PROCEDURAL,
                layer=LifecycleLayer.LONG_TERM,
                scope_level=MemoryScope.PROJECT,
                scope="PROJECT:onboarding",
                content_version=1,
                evolution_status="ACTIVE",
                content={"name": "new hire onboarding", "steps": ["step1", "step2"]},
                score=0.82,
            ),
        ],
        total_count=1,
    )

    legacy = LegacySearchCompatibilityResponse.from_vnext(response, latency_ms=7.0)

    assert len(legacy.results) == 1
    assert legacy.results[0]["memory_type"] == "knowledge"
    assert len(legacy.knowledge) == 1
    assert legacy.knowledge[0]["name"] == "new hire onboarding"
    assert legacy.latency_ms == 7.0
