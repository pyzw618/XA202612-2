"""Reflection service: schema, prompt versioning, retries, Candidate-only output."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from memoryhub.core.reflection.prompts import PROMPT_VERSION, render_reflection_prompt
from memoryhub.core.reflection.schema import (
    ReflectionInput,
    ReflectionOutput,
    ReflectionRunError,
)
from memoryhub.domain.contracts import Candidate, CandidateStatus, MemoryScope, MemoryType


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
        confidence = 0.7

        if "docx" in text:
            normalized_key = "format:docx"
            claim = {"format": "DOCX", "context": text}
            scope_level = "PROJECT"
            scope = "PROJECT:reporting"
        elif "markdown" in text or "md" in text:
            normalized_key = "format:markdown"
            claim = {"format": "Markdown", "context": text}
        elif "fix" in text or "repair" in text:
            memory_type = "PROCEDURAL"
            normalized_key = "procedure:repair"
            claim = {"action": "repair", "context": text}
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
            "utility": 0.6,
            "stability": 0.5,
            "model_id": self.model_id,
            "prompt_version": PROMPT_VERSION,
            "input_hash": input_hash,
            "reason": f"deterministic extraction from payload: {normalized_key}",
            "evidence_refs": [event_id],
            "supporting_episode_ids": [episode_id],
            "status": "REVIEW" if confidence < 0.5 else "ACCUMULATING",
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
        self.model = model or DeterministicReflectionModel()
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
]
