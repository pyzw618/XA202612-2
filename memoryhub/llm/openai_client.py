"""
OpenAI 兼容 API 客户端

支持任何 OpenAI 兼容的 API 端点（如 vLLM、LiteLLM、DeepSeek 等）。
"""

from memoryhub.llm.base import BaseLLMClient, LLMResponse


class OpenAIClient(BaseLLMClient):
    """
    OpenAI 兼容 API 客户端

    使用方式:
        client = OpenAIClient(
            api_base="http://localhost:8000/v1",
            api_key="sk-xxx",
            model="qwen2:7b"
        )
        response = client.generate("分析以下偏好...")
    """

    def __init__(
        self,
        api_base: str = "http://localhost:11434/v1",
        api_key: str = "",
        model: str = "qwen2:1.5b",
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ):
        """
        参数:
            api_base: API 端点地址
            api_key: API 密钥
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大生成 token 数
        """
        self.api_base = api_base
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        """
        调用 OpenAI 兼容 API 生成文本

        数据流:
            prompt → 构造 messages → POST /v1/chat/completions → 解析响应

        参数:
            prompt: 用户 prompt
            system_prompt: 系统 prompt
            **kwargs: 覆盖默认参数（temperature, max_tokens, model）

        返回:
            LLMResponse
        """
        raise NotImplementedError

    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        """
        生成结构化 JSON

        实现方式:
            在 system_prompt 中加入 JSON schema 要求，
            设置 response_format={"type": "json_object"}（如 API 支持），
            解析返回的 JSON 字符串。
        """
        raise NotImplementedError

    def is_available(self) -> bool:
        """通过调用 models 端点检查服务可用性"""
        raise NotImplementedError
