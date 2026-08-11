"""Environment-backed settings for the Qwen Agent integration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class QwenAgentSettings:
    api_key: str
    api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: str = "qwen-plus"
    temperature: float = 0.1
    memoryhub_url: str = "http://127.0.0.1:8000"

    @classmethod
    def from_env(cls) -> "QwenAgentSettings":
        load_dotenv()
        return cls(
            api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            api_base=os.getenv(
                "QWEN_API_BASE",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).rstrip("/"),
            model=os.getenv("QWEN_MODEL", "qwen-plus").strip() or "qwen-plus",
            temperature=float(os.getenv("QWEN_TEMPERATURE", "0.1")),
            memoryhub_url=os.getenv(
                "MEMORYHUB_URL",
                "http://127.0.0.1:8000",
            ).rstrip("/"),
        )

    def require_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY。请在环境变量或 .env 中配置阿里云百炼 API Key。"
            )
