"""
知识抽取模块

从任务执行轨迹中提取工作流知识、历史案例、可复用模板。
"""

from memoryhub.adapter.schemas import MemoryEvent, KnowledgeMemory, KnowledgeType


class KnowledgeExtractor:
    """
    知识抽取器

    使用方式:
        extractor = KnowledgeExtractor(llm_client=llm)
        knowledge = extractor.extract_from_trajectory(events)
    """

    def __init__(self, llm_client=None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于知识结构化
        """
        self.llm_client = llm_client

    def extract_from_trajectory(self, events: list[MemoryEvent]) -> list[KnowledgeMemory]:
        """
        从任务执行轨迹中抽取知识

        数据流:
            任务事件序列 → extract_from_trajectory
              → 识别任务目标和步骤
              → 提取工具调用链
              → 生成工作流知识 / 历史案例
              → 绑定证据链

        参数:
            events: 同一任务的事件序列（按时间排序）

        返回:
            候选 KnowledgeMemory 列表

        处理逻辑:
            1. 从事件序列中提取任务目标
            2. 识别执行步骤和工具调用链
            3. 判断是否形成可复用的工作流
            4. 生成知识记录并绑定证据
        """
        raise NotImplementedError

    def extract_workflow(self, events: list[MemoryEvent]) -> KnowledgeMemory | None:
        """
        从事件序列中提取工作流知识

        返回:
            WORKFLOW 类型的 KnowledgeMemory，或 None（无法提取时）
        """
        raise NotImplementedError

    def extract_case(self, events: list[MemoryEvent]) -> KnowledgeMemory | None:
        """
        从事件序列中提取历史案例

        返回:
            CASE 类型的 KnowledgeMemory，或 None
        """
        raise NotImplementedError

    def extract_template(self, events: list[MemoryEvent]) -> KnowledgeMemory | None:
        """
        从事件序列中提取可复用模板

        返回:
            TEMPLATE 类型的 KnowledgeMemory，或 None
        """
        raise NotImplementedError

    def _identify_task_goal(self, events: list[MemoryEvent]) -> str:
        """识别任务目标"""
        raise NotImplementedError

    def _extract_tool_chain(self, events: list[MemoryEvent]) -> list[str]:
        """提取工具调用链"""
        raise NotImplementedError

    def _extract_steps(self, events: list[MemoryEvent]) -> list[str]:
        """提取执行步骤"""
        raise NotImplementedError
