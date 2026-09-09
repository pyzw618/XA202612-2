from memoryhub.application.reflection_service import DeterministicReflectionModel
from memoryhub.core.knowledge.extractor import KnowledgeExtractor, parse_explicit_fact_statement
from memoryhub.core.reflection.schema import ReflectionInput
from memoryhub.adapter.api import _fact_memory_to_dict
from memoryhub.adapter.schemas import KnowledgeMemory, KnowledgeType


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
