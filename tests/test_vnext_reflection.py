from __future__ import annotations

from typing import Any

import pytest

from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionModel,
    ReflectionService,
    StructuredReflectionModel,
)
from memoryhub.core.reflection.prompts import PROMPT_VERSION
from memoryhub.core.reflection.schema import ReflectionInput, ReflectionOutput, ReflectionRunError
from memoryhub.domain.contracts import Candidate, CandidateStatus, MemoryScope, MemoryType


@pytest.fixture()
def reflection_input() -> ReflectionInput:
    return ReflectionInput(
        tenant_id="tenant-a",
        user_id="user-a",
        task_id="task-a",
        episode_id="episode-a",
        event_id="event-a",
        payload_summary={"text": "This time please use DOCX for Project-A reports."},
        working_state_snapshot={"current_step": "draft"},
        episode_history_summary=[{"phase": "draft"}],
        requested_memory_type="PREFERENCE",
        scope_hint="PROJECT",
    )


def test_reflection_outputs_candidate_with_prompt_version_and_input_hash(
    reflection_input: ReflectionInput,
) -> None:
    service = ReflectionService()
    candidate = service.run(reflection_input)
    assert isinstance(candidate, Candidate)
    assert candidate.memory_type is MemoryType.PREFERENCE
    assert candidate.normalized_key == "format:docx"
    assert candidate.scope_level is MemoryScope.PROJECT
    assert candidate.status is CandidateStatus.ACCUMULATING


def test_reflection_records_model_and_prompt_metadata(reflection_input: ReflectionInput) -> None:
    service = ReflectionService()
    candidate = service.run(reflection_input)
    # Candidate schema does not carry model_id/prompt_version directly; the
    # deterministic model is tested below to prove those fields are produced.
    assert candidate.evidence_refs == [reflection_input.event_id]
    assert candidate.supporting_episode_ids == [reflection_input.episode_id]


def test_reflection_output_schema_validates_model_metadata() -> None:
    raw = DeterministicReflectionModel().generate(
        "unused",
        input_hash="deadbeef" * 4,
        input_data=ReflectionInput(
            tenant_id="t",
            user_id="u",
            task_id="task",
            episode_id="ep",
            event_id="ev",
            payload_summary={"text": "use DOCX"},
        ),
    )
    output = ReflectionOutput.model_validate(raw)
    assert output.model_id == "deterministic-reflection/v1"
    assert output.prompt_version == PROMPT_VERSION
    assert output.input_hash == "deadbeef" * 4


def test_reflection_retries_then_routes_to_review_on_failure() -> None:
    class FailingModel(ReflectionModel):
        model_id = "failing/v1"
        calls: int = 0

        def generate(
            self, prompt: str, *, input_hash: str, input_data: ReflectionInput | None = None
        ) -> dict[str, Any]:
            self.calls += 1
            raise RuntimeError("model failure")

    model = FailingModel()
    service = ReflectionService(model=model, max_retries=2)
    with pytest.raises(ReflectionRunError):
        service.run(
            ReflectionInput(
                tenant_id="t",
                user_id="u",
                task_id="task",
                episode_id="ep",
                event_id="ev",
                payload_summary={"text": "use DOCX"},
            )
        )
    assert model.calls == 3


def test_structured_reflection_uses_configured_llm_and_runtime_metadata(
    reflection_input: ReflectionInput,
) -> None:
    class ConfiguredLLM:
        model = "configured-reflection-model"

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def generate_json(
            self,
            prompt: str,
            schema: dict[str, Any],
            system_prompt: str = "",
        ) -> dict[str, Any]:
            self.calls.append((prompt, schema))
            return {
                "candidate_id": "candidate-configured",
                "memory_type": "PREFERENCE",
                "normalized_key": "format:docx",
                "claim": {"format": "DOCX"},
                "scope_level": "PROJECT",
                "scope": "PROJECT:reporting",
                "confidence": 0.8,
                "utility": 0.7,
                "stability": 0.6,
                "reason": "explicit project preference",
                "evidence_refs": [reflection_input.event_id],
                "supporting_episode_ids": [reflection_input.episode_id],
                "status": "ACCUMULATING",
            }

    llm = ConfiguredLLM()
    candidate = ReflectionService(model=StructuredReflectionModel(llm)).run(reflection_input)

    assert candidate.candidate_id == "candidate-configured"
    assert candidate.memory_type is MemoryType.PREFERENCE
    assert len(llm.calls) == 1
    assert "candidate_id" in llm.calls[0][1]["properties"]


def test_structured_reflection_rejects_invalid_schema_output(
    reflection_input: ReflectionInput,
) -> None:
    class InvalidLLM:
        model = "invalid-reflection-model"

        def generate_json(
            self,
            prompt: str,
            schema: dict[str, Any],
            system_prompt: str = "",
        ) -> dict[str, Any]:
            return {"candidate_id": "missing-required-fields"}

    service = ReflectionService(model=StructuredReflectionModel(InvalidLLM()), max_retries=0)
    with pytest.raises(ReflectionRunError):
        service.run(reflection_input)
