"""OpenAI-compatible chat completion client."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from memoryhub.llm.base import BaseLLMClient, LLMResponse


class OpenAIClient(BaseLLMClient):
    def __init__(self, api_base: str = "http://localhost:11434/v1", api_key: str = "", model: str = "qwen2:1.5b", temperature: float = 0.1, max_tokens: int = 2048):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _request(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        payload = {"model": kwargs.pop("model", self.model), "messages": messages, "temperature": kwargs.pop("temperature", self.temperature), "max_tokens": kwargs.pop("max_tokens", self.max_tokens), "stream": False, **kwargs}
        req = urllib.request.Request(self.api_base + "/chat/completions", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})}, method="POST")
        with urllib.request.urlopen(req, timeout=kwargs.pop("timeout", 60)) as response:
            return json.loads(response.read().decode("utf-8"))

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        messages = ([{"role": "system", "content": system_prompt}] if system_prompt else []) + [{"role": "user", "content": prompt}]
        started = time.perf_counter()
        data = self._request(messages, **kwargs)
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        return LLMResponse(content=str(content or ""), model=str(data.get("model", self.model)), tokens_used=int(usage.get("total_tokens", 0) or 0), latency_ms=(time.perf_counter() - started) * 1000)

    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        instruction = (system_prompt + "\n" if system_prompt else "") + "Return JSON only. JSON schema:\n" + json.dumps(schema, ensure_ascii=False)
        result = self.generate(prompt, system_prompt=instruction, response_format={"type": "json_object"})
        text = result.content.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError("LLM JSON response must be an object")
        return value

    def is_available(self) -> bool:
        return bool(self.api_base and (self.api_key or "localhost" in self.api_base or "127.0.0.1" in self.api_base))
