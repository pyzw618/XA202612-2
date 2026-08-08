"""LangGraph-backed Qwen Agent connected to Kylin-MemoryHub."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from integrations.agents.config import QwenAgentSettings
from integrations.agents.tools import build_demo_tools
from integrations.agents.trace_adapter import (
    build_agent_event,
    build_user_event,
    extract_final_answer,
)
from integrations.memoryhub_client import MemoryHubClient


class QwenMemoryAgent:
    def __init__(
        self,
        settings: QwenAgentSettings,
        workspace: Path,
        memory_client: MemoryHubClient | None = None,
    ):
        settings.require_api_key()
        self.settings = settings
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.memory_client = memory_client or MemoryHubClient(settings.memoryhub_url)
        self._owns_client = memory_client is None

    def run(
        self,
        user_input: str,
        *,
        user_id: str = "demo-user",
        session_id: str = "",
        scene: str = "office",
        task_type: str = "office.weekly_report",
    ) -> dict[str, Any]:
        session_id = session_id or f"session_{uuid.uuid4().hex[:12]}"
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        memory = self.memory_client.get_context(
            user_id=user_id,
            query=user_input,
            scene=scene,
            task_type=task_type,
        )
        graph = self._build_graph(memory["context"])
        result = graph.invoke(
            {"messages": [{"role": "user", "content": user_input}]},
            config={"configurable": {"thread_id": session_id}},
        )
        messages = result["messages"]

        events = [
            build_user_event(
                user_input,
                user_id=user_id,
                session_id=session_id,
                turn_id=turn_id,
                scene=scene,
                task_type=task_type,
            )
        ]
        agent_event = build_agent_event(
            messages,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            scene=scene,
            task_type=task_type,
            model=self.settings.model,
        )
        if agent_event is not None:
            events.append(agent_event)
        write_result = self.memory_client.write_events(events)

        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "answer": extract_final_answer(messages),
            "memory_context": memory["context"],
            "events_written": write_result,
        }

    def close(self) -> None:
        if self._owns_client:
            self.memory_client.close()

    def _build_graph(self, memory_context: str):
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.api_base,
            model=self.settings.model,
            temperature=self.settings.temperature,
        )
        system_prompt = f"""你是一个项目周报 Agent。
你必须先调用 file_search 和 calendar_read 获取事实，再调用 report_writer 写入 Markdown 周报。
不得编造工具没有返回的进展或日程。报告写入成功后，向用户简要说明输出路径。

MemoryHub 返回的历史记忆：
{memory_context}
"""
        return create_agent(
            model=model,
            tools=build_demo_tools(self.workspace),
            system_prompt=system_prompt,
        )
