"""
OS Agent 模拟器 — 用于独立演示和测试

模拟真实 OS Agent 的行为：接收用户任务、调用记忆模块、执行工具调用。
"""

from memoryhub.adapter.schemas import MemoryEvent, SearchResponse


class AgentSimulator:
    """
    OS Agent 模拟器

    使用方式:
        simulator = AgentSimulator(memory_adapter)
        result = simulator.run_task("帮我按上次的方式生成项目周报")
    """

    def __init__(self, memory_adapter=None):
        """
        初始化模拟器

        参数:
            memory_adapter: MemoryAdapter 实例，用于调用记忆接口
        """
        self.memory_adapter = memory_adapter
        self.session_id = ""
        self.task_history: list[dict] = []

    def run_task(self, user_input: str) -> dict:
        """
        执行一次完整的模拟任务

        数据流:
            用户输入 → 识别任务类型 → 检索记忆 → 模拟工具调用
            → 写入事件 → 返回结果

        参数:
            user_input: 用户自然语言输入

        返回:
            {
                "task_type": str,
                "memory_context": SearchResponse,
                "tool_calls": list[dict],
                "output": str,
                "events_generated": list[MemoryEvent]
            }
        """
        raise NotImplementedError

    def _identify_task_type(self, user_input: str) -> str:
        """识别任务类型，返回 scene.task_type 标识"""
        raise NotImplementedError

    def _simulate_tool_calls(self, task_type: str, memory_context: SearchResponse) -> list[dict]:
        """根据任务类型和记忆上下文，模拟工具调用序列"""
        raise NotImplementedError

    def _generate_events(
        self, task_type: str, tool_calls: list[dict], user_input: str
    ) -> list[MemoryEvent]:
        """将本次任务执行转化为 MemoryEvent 列表"""
        raise NotImplementedError

    def simulate_user_feedback(self, feedback_text: str) -> MemoryEvent:
        """
        模拟用户反馈

        参数:
            feedback_text: 如 "以后都用 Markdown"

        返回:
            生成的 user_feedback 类型 MemoryEvent
        """
        raise NotImplementedError
