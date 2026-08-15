"""Structured adapter over the application-level BaseLLMClient."""

from __future__ import annotations

import json
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class StructuredLLMAdapter:
    def __init__(self, llm_client: Any = None) -> None:
        self.llm_client = llm_client

    def generate_json(
        self,
        *,
        task_name: str,
        system_prompt: str,
        prompt: str,
        parser: Callable[[Any], T],
        temperature: float = 0.0,
    ) -> T:
        if self.llm_client is None or not callable(
            getattr(self.llm_client, "generate", None)
        ):
            raise RuntimeError(f"{task_name} LLM client is not configured")
        response = self.llm_client.generate(
            prompt, system_prompt=system_prompt, temperature=temperature
        )
        content = str(getattr(response, "content", response) or "").strip()
        if content.startswith("```"):
            content = content.strip("`").removeprefix("json").strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{task_name} returned invalid JSON") from exc
        return parser(data)

    def generate_text(
        self,
        *,
        task_name: str,
        system_prompt: str,
        prompt: str,
        temperature: float = 0.0,
        timeout: float | None = None,
    ) -> str:
        if self.llm_client is None or not callable(
            getattr(self.llm_client, "generate", None)
        ):
            raise RuntimeError(f"{task_name} LLM client is not configured")
        kwargs: dict[str, Any] = {"temperature": temperature}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = self.llm_client.generate(
            prompt, system_prompt=system_prompt, **kwargs
        )
        error = str(getattr(response, "error", "") or "").strip()
        if error:
            # Providers such as Ollama return transport failures in LLMResponse
            # instead of raising.  Do not treat that as an empty model answer.
            raise RuntimeError(f"{task_name} LLM request failed")
        return str(getattr(response, "content", response) or "")
