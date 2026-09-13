from memoryhub.adapter.api import _fact_memory_to_dict, _render_legacy_context
from memoryhub.adapter.retrieval_executor import _legacy_memory_metadata, _retrieved_content
from memoryhub.adapter.schemas import KnowledgeMemory, KnowledgeType
from memoryhub.adapter.vnext_schemas import RetrievedMemory, _retrieved_memory_to_legacy_typed
from memoryhub.adapter.schemas import SearchRequest, SearchResponse, SearchResult
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType
import pytest
from memoryhub.application.reflection_service import DeterministicReflectionModel
from memoryhub.core.knowledge.extractor import KnowledgeExtractor, parse_explicit_fact_statement
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.reflection.schema import ReflectionInput


def test_english_possessive_statement_is_extracted_as_triple() -> None:
    assert parse_explicit_fact_statement("The user's name is Joe.") == (
        "user",
        "name",
        "Joe",
    )
    assert KnowledgeExtractor()._facts_from_dialogue_text("The user's name is Joe.") == [
        ("user", "name", "Joe")
    ]


def test_deterministic_reflection_keeps_statement_and_structured_triple() -> None:
    input_data = ReflectionInput(
        tenant_id="default",
        user_id="alice",
        task_id="task-1",
        episode_id="episode-1",
        event_id="event-1",
        payload_summary={"text": "The user's name is Joe."},
    )
    result = DeterministicReflectionModel().generate(
        "prompt", input_hash="hash", input_data=input_data
    )
    assert result["claim"] == {
        "statement": "the user's name is joe.",
        "subject": "user",
        "predicate": "name",
        "object_value": "joe",
    }


def test_fact_api_recovers_old_statement_only_row_for_display() -> None:
    row = KnowledgeMemory(
        memory_id="fact-old",
        user_id="alice",
        knowledge_type=KnowledgeType.FACT,
        name="old fact",
        content="The user's name is Joe.",
    )
    result = _fact_memory_to_dict(row)
    assert (result["subject"], result["predicate"], result["object_value"]) == (
        "user",
        "name",
        "Joe",
    )


def _retrieved_fact(content: dict) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="default", user_id="alice", memory_id="fact-qa",
        memory_type=MemoryType.SEMANTIC, layer=LifecycleLayer.LONG_TERM,
        scope_level=MemoryScope.GLOBAL, scope="GLOBAL", content_version=2,
        evolution_status="ACTIVE", content=content, score=0.9,
    )


def test_fact_triple_survives_legacy_retrieval_round_trip() -> None:
    row = KnowledgeMemory(
        memory_id="fact-qa", user_id="alice", knowledge_type=KnowledgeType.FACT,
        name="owner", content="report owner Bob", subject="report",
        predicate="owner", object_value="Bob",
    )
    content = _retrieved_content(row.content, _legacy_memory_metadata(row))
    indexed = _retrieved_content(row.content, MemoryWriteService.index_metadata(row))
    assert indexed["object_value"] == "Bob"
    fact = _retrieved_memory_to_legacy_typed(_retrieved_fact(content))
    assert (fact.subject_id, fact.predicate_id, fact.object_value) == ("report", "owner", "Bob")
    assert "- report owner Bob" in _render_legacy_context(SearchResponse(facts=[fact]))


@pytest.mark.parametrize("content", [
    {"subject_id": "report", "predicate_id": "owner", "object_value": "Bob"},
    {"claim": {"subject": "report", "predicate": "owner", "object_value": "Bob"}},
])
def test_fact_compatibility_accepts_legacy_ids_and_canonical_claim(content: dict) -> None:
    fact = _retrieved_memory_to_legacy_typed(_retrieved_fact(content))
    assert (fact.subject_id, fact.predicate_id, fact.object_value) == ("report", "owner", "Bob")
    assert fact.version == 2


def test_statement_only_fact_context_is_not_an_empty_bullet() -> None:
    fact = _retrieved_memory_to_legacy_typed(_retrieved_fact({"text": "legacy statement"}))
    assert _render_legacy_context(SearchResponse(facts=[fact])) == "## 事实记忆\n- legacy statement"


@pytest.mark.parametrize("retriever_type", [HybridRetriever, MilvusHybridRetriever])
def test_fact_only_filter_accepts_canonical_fact_but_not_other_knowledge(retriever_type) -> None:
    retriever = retriever_type.__new__(retriever_type)
    retriever.memory_lookup = {}
    results = [SearchResult(
        memory_id=subtype, memory_type="knowledge", score=0.9,
        metadata={"user_id": "alice", "status": "active", "knowledge_type": subtype},
    ) for subtype in ("fact", "workflow", "case")]
    selected = retriever._filter_by_context(results, SearchRequest(user_id="alice", memory_types=["fact"]))
    assert [item.memory_id for item in selected] == ["fact"]
    assert retriever._filter_by_context(results, SearchRequest(user_id="bob", memory_types=["fact"])) == []
