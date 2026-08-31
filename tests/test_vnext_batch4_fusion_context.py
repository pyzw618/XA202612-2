from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest, RetrievedMemory
from memoryhub.application.context_service import ContextService
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    ActivationStatus,
    EvolutionStatus,
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.fusion import ReciprocalRankFusion
from memoryhub.retrieval.planner import RetrievalPlan


def _request(**overrides):
    values = {
        "request_id": "batch4-request",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "query": "remember my project preference",
        "task_id": "task-1",
        "scope_level": MemoryScope.PROJECT,
        "scope": "project-1",
        "token_budget": 128,
        "page_size": 5,
    }
    values.update(overrides)
    return MemoryRetrievalRequest(**values)


def _memory(memory_id: str, *, score: float = 1.0, text: str = "memory"):
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.PROJECT,
        scope="project-1",
        content_version=1,
        projection_version=1,
        evolution_status=EvolutionStatus.ACTIVE.value,
        content={"text": text},
        score=score,
        score_breakdown={},
        source_ids=[f"authority:{memory_id}"],
    )


def test_rrf_records_and_applies_intent_channel_weights():
    fusion = ReciprocalRankFusion().fuse(
        {"authority": [_memory("authority")], "vector": [_memory("vector")]},
        channel_weights={"authority": 1.35, "vector": 1.0},
    )

    assert fusion.memories[0].memory_id == "authority"
    assert fusion.memories[0].score_breakdown["channel_weights"]["authority"] == 1.35


def test_context_uses_plan_intent_and_request_budget():
    request = _request(intent_hint=None)
    plan = RetrievalPlan(
        intent=RetrievalIntent.PREFERENCE,
        enabled_channels=["authority", "vector"],
        top_k=5,
    )
    assembly = ContextService().build_context(
        request,
        plan,
        {
            "authority": [_memory("authority", text="preferred build tool")],
            "vector": [_memory("vector", text="x" * 800)],
        },
    )

    assert assembly.trace["intent"] == RetrievalIntent.PREFERENCE.value
    assert assembly.context.selected_tokens <= request.token_budget
    assert assembly.fusion.memories[0].memory_id == "authority"


def test_retrieval_records_recalled_selected_and_in_context():
    request = _request(intent_hint=RetrievalIntent.PREFERENCE)
    plan = RetrievalPlan(
        intent=RetrievalIntent.PREFERENCE,
        enabled_channels=["authority"],
        top_k=5,
    )
    service = RetrievalService(
        planner=type("Planner", (), {"plan": lambda self, req, routed: plan})(),
        channel_executors={"authority": lambda req, current_plan, channel: [_memory("m1")]},
    )

    result = service.retrieve(request)
    statuses = {activation.status for activation in result.activations}

    assert ActivationStatus.RECALLED in statuses
    assert ActivationStatus.IN_CONTEXT in statuses
