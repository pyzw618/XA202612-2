import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# 将项目根目录加入搜索路径
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


API_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen3.7-flash"
DEFAULT_API_KEY = "sk-ws-H.EIPEEMI.WNAR.MEYCIQDGUZ2778Niidp7woaLMej95Uv2ODI1s5-nXbBTkv4WJAIhAKDOYNwTWgIAXiZfajqDIZ7127f80JhL8pCu3ohTEdKQ"  # 已经跑通了测试，复试请自己填


def _call_dashscope_api(prompt: str, api_key: str | None = None) -> dict:
    """调用阿里云 DashScope 的 OpenAI 兼容接口。"""
    key = api_key or os.getenv("DASHSCOPE_API_KEY") or DEFAULT_API_KEY
    if not key:
        raise RuntimeError(
            "DASHSCOPE_API_KEY is not set. To run this test provide a real key via environment variable and set RUN_LLM_API_TESTS=1."
        )
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是知识抽取助手。请从给定的任务轨迹中提取可复用的工作流知识、案例和模板。"
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        f"{API_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.mark.skipif(
    os.getenv("RUN_LLM_API_TESTS", "0") != "1" or os.getenv("DASHSCOPE_API_KEY") is None,
    reason="仅在同时设置 RUN_LLM_API_TESTS=1 且提供 DASHSCOPE_API_KEY 环境变量时才执行，避免在 CI/本地泄露密钥",
)
def test_knowledge_api_extracts_workflow_from_task_trajectory() -> None:
    """
    说明：知识抽取通常需要 LLM 的语义理解，因此这类测试会走模型 API。
    这份测试用于验证 DashScope 的 OpenAI 兼容接口是否可用。
    """
    prompt = (
        "请从以下任务轨迹中提取工作流知识："
        "任务：生成周报；步骤：收集数据、整理结论、生成周报；工具：file_search, note_tool。"
        "请输出简短的工作流描述。"
    )

    response = _call_dashscope_api(prompt)
    choices = response.get("choices", [])
    assert choices, f"API 响应中未返回 choices: {response}"

    content = choices[0].get("message", {}).get("content", "")
    assert isinstance(content, str) and len(content.strip()) > 0

