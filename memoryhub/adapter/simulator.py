"""
OS Agent 模拟器 — 用于独立演示和测试

模拟真实 OS Agent 的行为：接收用户任务、调用记忆模块、执行工具调用。
"""

import uuid
from datetime import datetime, timezone

from memoryhub.adapter.schemas import MemoryEvent, SearchResponse, SourceType, ToolCallResult


class OSAgentSimulator:
    """
    OS Agent 模拟器，用于无后端集成测试。

    使用方式:
        sim = OSAgentSimulator()
        events = sim.simulate_task("整理上周周报", scene="document", task_type="report")
    """

    def simulate_task(self, task: str, scene: str = "general", task_type: str = "general",
                      user_id: str = "test_user") -> list[MemoryEvent]:
        """模拟一次完整的任务交互，返回生成的事件列表"""
        events = []
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 用户输入事件
        events.append(MemoryEvent(
            event_id=f"sim_input_{uuid.uuid4().hex[:8]}",
            source_type=SourceType.USER_BEHAVIOR,
            event_type="user_input",
            user_id=user_id,
            scene=scene,
            task_type=task_type,
            text=task,
            occurred_at=ts,
        ))

        # 模拟工具调用
        tool_call = ToolCallResult(
            call_id=f"sim_tool_{uuid.uuid4().hex[:8]}",
            tool_name="file_search",
            arguments={"query": task},
            result={"files_found": ["report_week_27.md", "report_week_28.md"]},
            status="success",
            sequence=1,
        )
        events.append(MemoryEvent(
            event_id=f"sim_tool_{uuid.uuid4().hex[:8]}",
            source_type=SourceType.TOOL_RESULT,
            event_type="file_search",
            user_id=user_id,
            scene=scene,
            task_type=task_type,
            text=f"Found files for task: {task}",
            tool_calls=[tool_call],
            occurred_at=ts,
        ))

        return events

    def simulate_conversation(self, turns: list[str], scene: str = "chat",
                              task_type: str = "conversation") -> list[MemoryEvent]:
        """模拟多轮对话"""
        events = []
        for turn_text in turns:
            events.extend(self.simulate_task(turn_text, scene=scene, task_type=task_type))
        return events

    def simulate_search(self, query: str, scene: str = "general") -> SearchResponse:
        """模拟检索请求（返回空结果）"""
        return SearchResponse(
            preferences=[],
            knowledge=[],
            latency_ms=0.0,
        )

    def simulate_error(self, error_message: str = "Simulated error") -> MemoryEvent:
        """模拟错误事件"""
        return MemoryEvent(
            event_id=f"sim_error_{uuid.uuid4().hex[:8]}",
            source_type=SourceType.TOOL_RESULT,
            event_type="error",
            text=error_message,
            occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    def simulate_feedback(self, memory_id: str, feedback_text: str, action: str = "update") -> dict:
        """模拟用户反馈"""
        return {
            "user_id": "test_user",
            "memory_id": memory_id,
            "feedback_text": feedback_text,
            "action": action,
        }
