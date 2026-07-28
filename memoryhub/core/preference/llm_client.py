import os
import re
from openai import OpenAI


class OpenAIClientAdapter:
    """OpenAI API 客户端适配器"""

    def __init__(
        self,
        api_key: str = None,
        base_url: str = None,
        model_name: str = "gpt-5.6-sol",
    ):
        # 1. 优先使用传入参数，其次读取环境变量
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model_name = model_name

        if not self.api_key:
            raise ValueError(
                "❌ 未检测到 API Key！请在构造函数中传入 api_key 或设置 OPENAI_API_KEY 环境变量。"
            )

        # 2. 组装客户端初始化参数
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = OpenAI(**client_kwargs)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM 并返回文本响应 (str)"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )

            # 3. 解析并安全返回文本内容
            if hasattr(response, "choices") and response.choices:
                return response.choices[0].message.content or ""
            return str(response)

        except Exception as e:
            print(f"❌ API 请求失败: {e}")
            raise e