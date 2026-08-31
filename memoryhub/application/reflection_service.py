"""Reflection service: schema, prompt versioning, retries, Candidate-only output."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Protocol

from memoryhub.core.reflection.prompts import PROMPT_VERSION, render_reflection_prompt
from memoryhub.core.reflection.schema import (
    ReflectionInput,
    ReflectionOutput,
    ReflectionRunError,
)
from memoryhub.domain.contracts import Candidate, CandidateStatus, MemoryScope, MemoryType

logger = logging.getLogger(__name__)


class ReflectionModel(Protocol):
    """A model that turns a rendered prompt into structured reflection output."""

    model_id: str

    def generate(
        self,
        prompt: str,
        *,
        input_hash: str,
        input_data: ReflectionInput | None = None,
    ) -> dict[str, Any]:
        ...


class DeterministicReflectionModel:
    """A local, deterministic reflection model for B07 testing.

    It does not call a remote LLM.  It extracts simple preferences/facts from
    the payload so the reflection pipeline can be validated end-to-end.
    """

    model_id: str = "deterministic-reflection/v1"

    def generate(
        self,
        prompt: str,
        *,
        input_hash: str,
        input_data: ReflectionInput | None = None,
    ) -> dict[str, Any]:
        # Use the structured input directly; the prompt is rendered only for
        # pipeline validation and audit.
        payload = input_data.payload_summary if input_data is not None else {}
        text = str(payload.get("text", "")).lower()
        memory_type = "PREFERENCE"
        normalized_key = "preference:unknown"
        claim: dict[str, Any] = {"value": text}
        scope_level = "TASK"
        scope = "TASK:default"
        confidence = 0.85
        utility = 0.7
        stability = 0.7

        if "docx" in text:
            normalized_key = "format:docx"
            claim = {"value": "DOCX", "format": "DOCX", "context": text}
            scope_level = "PROJECT"
            scope = "PROJECT:reporting"
        elif "markdown" in text or "md" in text:
            normalized_key = "format:markdown"
            claim = {"value": "Markdown", "format": "Markdown", "context": text}
        elif "fix" in text or "repair" in text:
            memory_type = "PROCEDURAL"
            normalized_key = "procedure:repair"
            confidence = 0.9
            utility = 0.7
            stability = 0.7
            # Procedure claims have a stable shape.  Episode-specific prose is
            # kept out of the identity key so independent runs can accumulate
            # evidence for the same repair recipe.
            raw = input_data.payload_summary if input_data is not None else {}
            claim = {
                "trigger": raw.get("trigger") or "repair failure",
                "preconditions": self._as_list(
                    raw.get("preconditions")
                    or raw.get("conditions")
                    or ["the task is reproducible"]
                ),
                "steps": self._as_list(
                    raw.get("steps")
                    or raw.get("procedure_steps")
                    or ["inspect the failure", "apply the repair"]
                ),
                "verification": self._as_list(
                    raw.get("verification") or ["repeat the task and confirm the result"]
                ),
                "failure_recovery": self._as_recovery(
                    raw.get("failure_recovery") or raw.get("recovery") or [
                        {"condition": "repair fails", "action": "restore the last known good state"}
                    ]
                ),
                "outcome": str(raw.get("outcome") or raw.get("result") or "success").lower(),
            }
        elif "fact" in text or "is" in text:
            memory_type = "SEMANTIC"
            normalized_key = "fact:extracted"
            claim = {"statement": text}

        if not text:
            confidence = 0.3

        event_id = input_data.event_id if input_data is not None else ""
        episode_id = input_data.episode_id if input_data is not None else ""

        return {
            "candidate_id": f"candidate-{input_hash[:16]}",
            "memory_type": memory_type,
            "normalized_key": normalized_key,
            "claim": claim,
            "scope_level": scope_level,
            "scope": scope,
            "confidence": confidence,
            "utility": utility,
            "stability": stability,
            "model_id": self.model_id,
            "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash,
            "reason": f"deterministic extraction from payload: {normalized_key}",
            "evidence_refs": [event_id],
            "supporting_episode_ids": [episode_id],
            "status": "REVIEW" if confidence < 0.5 else "ACCUMULATING",
        }

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)] if str(value).strip() else []

    @staticmethod
    def _as_recovery(value: Any) -> list[Any]:
        if isinstance(value, (list, tuple)):
            return list(value)
        return [value]


class StructuredReflectionModel:
    """Adapt the configured application LLM to the ReflectionModel contract.

    The LLM owns only semantic Candidate fields.  Runtime-generated metadata is
    supplied locally so the provider never has to reproduce the input hash or
    identify itself correctly for schema validation.
    """

    def __init__(self, llm_client: Any) -> None:
        if not callable(getattr(llm_client, "generate_json", None)):
            raise TypeError("structured reflection requires an LLM generate_json client")
        self.llm_client = llm_client
        self.model_id = str(
            getattr(llm_client, "model", "") or llm_client.__class__.__name__
        )

    def generate(
        self,
        prompt: str,
        *,
        input_hash: str,
        input_data: ReflectionInput | None = None,
    ) -> dict[str, Any]:
        raw = self.llm_client.generate_json(
            prompt,
            schema=ReflectionOutput.model_json_schema(),
        )
        if not isinstance(raw, dict):
            raise ValueError("structured reflection response must be an object")
        # These values are controlled by the runtime rather than the model.
        return {
            **raw,
            "model_id": self.model_id,
            "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash,
        }


class ReflectionService:
    """Run reflection with prompt versioning, retries and Candidate-only output.

    The service never writes to long-term Authority.  It returns a Candidate
    object that downstream staging services may merge or promote.
    """

    def __init__(
        self,
        *,
        model: ReflectionModel | None = None,
        max_retries: int = 2,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if model is None:
            raise TypeError(
                "ReflectionService requires an explicit model; "
                "use StructuredReflectionModel(<configured llm>) in production "
                "or DeterministicReflectionModel()/FakeReflectionModel() in tests"
            )
        self.model = model
        self.max_retries = max_retries
        self.prompt_version = prompt_version

    def run(self, reflection_input: ReflectionInput) -> Candidate:
        if not isinstance(reflection_input, ReflectionInput):
            raise TypeError("reflection requires ReflectionInput")

        input_hash = self._hash_input(reflection_input)
        prompt = render_reflection_prompt(reflection_input.model_dump(mode="json"))

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self.model.generate(
                    prompt, input_hash=input_hash, input_data=reflection_input
                )
                output = ReflectionOutput.model_validate(raw)
                if output.prompt_version != self.prompt_version:
                    output.prompt_version = self.prompt_version
                if output.input_hash != input_hash:
                    output.input_hash = input_hash
                if output.model_id != self.model.model_id:
                    output.model_id = self.model.model_id
                return self._to_candidate(output, reflection_input)
            except Exception as exc:  # noqa: BLE001 - reflection failures are routed to REVIEW
                last_error = exc
                if attempt == self.max_retries:
                    break

        logger.warning(
            "structured_reflection_failed input_hash=%s attempts=%s error_type=%s",
            input_hash,
            self.max_retries + 1,
            type(last_error).__name__ if last_error is not None else "UnknownError",
        )
        return self._failed_candidate(reflection_input, input_hash, last_error)

    @staticmethod
    def _hash_input(reflection_input: ReflectionInput) -> str:
        payload = reflection_input.model_dump(mode="json")
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _to_candidate(output: ReflectionOutput, input_data: ReflectionInput) -> Candidate:
        return Candidate(
            tenant_id=input_data.tenant_id,
            user_id=input_data.user_id,
            candidate_id=output.candidate_id,
            memory_type=MemoryType(output.memory_type),
            normalized_key=output.normalized_key,
            claim=output.claim,
            scope_level=MemoryScope(output.scope_level),
            scope=output.scope,
            confidence=output.confidence,
            utility=output.utility,
            stability=output.stability,
            evidence_refs=output.evidence_refs,
            supporting_episode_ids=output.supporting_episode_ids,
            status=CandidateStatus(output.status),
        )

    def _failed_candidate(
        self,
        input_data: ReflectionInput,
        input_hash: str,
        error: Exception | None,
    ) -> Candidate:
        raise ReflectionRunError(
            f"reflection failed after {self.max_retries + 1} attempts: {error}",
            input_hash=input_hash,
        )


__all__ = [
    "DeterministicReflectionModel",
    "ReflectionModel",
    "ReflectionService",
    "StructuredReflectionModel",
]
