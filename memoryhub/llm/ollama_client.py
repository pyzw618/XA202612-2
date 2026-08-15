"""
Ollama 本地推理客户端

通过 Ollama 运行本地模型，完全端侧推理。
"""

import requests

from memoryhub.llm.base import BaseLLMClient, LLMResponse


class OllamaClient(BaseLLMClient):
    """
    Ollama API 客户端。

    使用方式:
        client = OllamaClient(api_base="http://localhost:11434", model="qwen2:1.5b")
        response = client.generate("You are helpful.", "Hello")
    """

    def __init__(self, api_base: str = "http://localhost:11434", model: str = "qwen2:1.5b",
                 temperature: float = 0.1, max_tokens: int = 2048, **kwargs):
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        """调用 Ollama /api/generate 生成文本"""
        url = f"{self.api_base}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }
        try:
            resp = requests.post(url, json=payload, timeout=kwargs.get("timeout", 120))
            resp.raise_for_status()
            data = resp.json()
            response = data.get("response", "")
            return LLMResponse(content=response)
        except requests.RequestException as e:
            return LLMResponse(content="", error=str(e))

    def generate_json(self, prompt: str, schema: dict | None = None,
                      system_prompt: str = "", **kwargs) -> dict:
        """调用 Ollama 并以 JSON 格式返回"""
        json_instruction = "Respond with valid JSON only, no additional text."
        full_prompt = f"{json_instruction}\n\n{prompt}"
        result = self.generate(prompt=full_prompt, system_prompt=system_prompt, **kwargs)
        if result.error:
            return {}
        import json
        try:
            return json.loads(result.content)
        except json.JSONDecodeError:
            return {}

    def is_available(self) -> bool:
        """检查 Ollama 服务是否可用"""
        try:
            resp = requests.get(f"{self.api_base}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        """列出可用模型"""
        try:
            resp = requests.get(f"{self.api_base}/api/tags", timeout=5)
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return [m.get("name", "") for m in models]
        except requests.RequestException:
            return []
