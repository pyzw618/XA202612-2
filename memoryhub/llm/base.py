"""
LLM 抽象基类

定义统一的 LLM 调用接口，支持不同后端实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str = ""                  # 生成的文本
    model: str = ""                    # 使用的模型名
    tokens_used: int = 0              # 消耗的 token 数
    latency_ms: float = 0.0           # 调用延迟


class BaseLLMClient(ABC):
    """
    LLM 客户端抽象基类

    所有 LLM 后端（云端 OpenAI 兼容 API）都实现此接口。
    上层模块（偏好抽取、知识抽取、冲突检测、遗忘意图解析）只依赖此接口。

    使用方式:
        client = OpenAIClient(api_base="...", api_key="...")
        response = client.generate("请分析以下用户偏好...")
    """

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> LLMResponse:
        """
        生成文本

        参数:
            prompt: 用户 prompt
            system_prompt: 系统 prompt
            **kwargs: 额外参数（temperature, max_tokens 等）

        返回:
            LLMResponse
        """
        raise NotImplementedError

    @abstractmethod
    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        """
        生成结构化 JSON 输出

        参数:
            prompt: 用户 prompt
            schema: 期望的 JSON schema
            system_prompt: 系统 prompt

        返回:
            解析后的 JSON 字典

        说明:
            实现时应在 prompt 中加入 JSON 格式要求，
            并对输出进行 JSON 解析和校验。
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """
        检查 LLM 服务是否可用

        返回:
            True 表示服务正常
        """
        raise NotImplementedError
