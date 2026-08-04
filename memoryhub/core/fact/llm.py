"""LLM compatibility helpers for the facts subsystem."""

from __future__ import annotations

from types import SimpleNamespace


class _UnavailableCompletions:
    def create(self, **kwargs):
        raise RuntimeError("facts LLM client is not configured")


class _GenerateCompletions:
    def __init__(self, client):
        self.client = client

    def create(self, *, messages, **kwargs):
        system = "\n".join(
            str(item.get("content", "")) for item in messages
            if item.get("role") == "system"
        )
        prompt = "\n".join(
            str(item.get("content", "")) for item in messages
            if item.get("role") != "system"
        )
        allowed = {key: value for key, value in kwargs.items() if key in {"temperature", "max_tokens"}}
        response = self.client.generate(prompt, system_prompt=system, **allowed)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=response.content)
        )])


class _ChatWrapper:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


def build_chat_client(*, api_key: str = "", llm_client=None, base_url: str):
    """Return an OpenAI-style chat client without requiring a remote API key at startup."""
    if llm_client is not None:
        if getattr(getattr(llm_client, "chat", None), "completions", None) is not None:
            return llm_client
        if callable(getattr(llm_client, "generate", None)):
            return _ChatWrapper(_GenerateCompletions(llm_client))
        raise TypeError("llm_client must expose generate() or chat.completions")

    import os
    key = api_key or os.environ.get("DEEPSEEK_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return _ChatWrapper(_UnavailableCompletions())
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base_url)
