"""
Ollama 本地推理客户端

通过 Ollama 运行本地模型，完全端侧推理。
"""

from memoryhub.llm.base import BaseLLMClient, LLMResponse


class OllamaClient(BaseLLMClient):
    """
    Ollama 本地推理客户端

    使用方式:
        client = OllamaClient(model="qwen2:1.5b")
        response = client.generate("分析以下偏好...")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2:1.5b",
        temperature: float = 0.1,
    ):
        """
        参数:
            base_url: Ollama 服务地址
            model: 模型名称（需已通过 ollama pull 下载）
            temperature: 生成温度
        """
        self.base_url = base_url
        self.model = model
        self.temperature = temperature

    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        """
        调用 Ollama 生成文本

        数据流:
            prompt → POST /api/generate → 解析响应

        参数:
            prompt: 用户 prompt
            system_prompt: 系统 prompt

        返回:
            LLMResponse
        """
        raise NotImplementedError

    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        """
        生成结构化 JSON

        Ollama 支持 format="json" 参数，可在 prompt 中指定 JSON schema。
        """
        raise NotImplementedError

    def is_available(self) -> bool:
        """通过调用 /api/tags 检查 Ollama 服务是否运行"""
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """列出本地已下载的模型"""
        raise NotImplementedError
