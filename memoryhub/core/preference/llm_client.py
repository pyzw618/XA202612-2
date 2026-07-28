import os
import re
from openai import OpenAI


class OpenAIClientAdapter:
    """Windows 兼容的 API 客户端适配器"""

    def __init__(self, model_name: str = "gpt-5.6-sol"):
        """
        :param model_name: 调用的模型名称 (例如: gpt-4o-mini, deepseek-chat, Qwen/Qwen2.5-7B-Instruct)
        """
        api_key = os.getenv("OPENAI_API_KEY") or "sk-xen2GeBn0BleDqJOYTqiGWdbfGtTJClr024pV3Lbs3da1jnx"
        base_url = os.getenv("OPENAI_BASE_URL", "https://cortexlane.cloud/")

        if not api_key:
            raise ValueError("❌ 环境变量 OPENAI_API_KEY 未设置！请检查环境变量配置。")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """提供给 PreferenceExtractor 调用的生成函数"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},  # 强约束 JSON 输出
            )

            content = response.choices[0].message.content or ""

            # 容错：去除 Markdown 代码块包裹
            if "```" in content:
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
                if match:
                    content = match.group(1)

            return content.strip()

        except Exception as e:
            print(f"❌ API 请求失败: {e}")
            raise e