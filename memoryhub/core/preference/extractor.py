"""
偏好抽取模块

从 MemoryEvent 中提取用户偏好，支持规则抽取和 LLM 辅助抽取。
"""

from memoryhub.adapter.schemas import MemoryEvent, PreferenceMemory, PreferenceType


class PreferenceExtractor:
    """
    偏好抽取器

    使用方式:
        extractor = PreferenceExtractor(llm_client=llm)
        prefs = extractor.extract(event)
    """

    def __init__(self, llm_client=None):
        """
        参数:
            llm_client: LLM 抽象客户端，用于辅助抽取隐式偏好
        """
        self.llm_client = llm_client

    def extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        从单条事件中抽取候选偏好

        数据流:
            MemoryEvent → extract
              → 规则抽取（显式偏好）
              → LLM 抽取（隐式偏好）
              → 合并去重
              → 返回候选偏好列表

        参数:
            event: 标准化事件

        返回:
            候选 PreferenceMemory 列表（尚未写入存储）

        处理逻辑:
            1. 调用 _rule_extract 尝试规则匹配
            2. 调用 _llm_extract 尝试 LLM 辅助抽取
            3. 合并结果，去重
            4. 为每条偏好绑定证据链
        """
        raise NotImplementedError

    def _rule_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        规则模板抽取（显式偏好）

        匹配模式示例:
            "以后都用 X" → output_style
            "默认使用 X" → tool_preference / format_preference
            "不要记住 X" → safety_preference
            "每次都先 Y 再 Z" → workflow_preference
        """
        raise NotImplementedError

    def _llm_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        LLM 辅助抽取（隐式偏好）

        将事件内容传给 LLM，让其识别潜在偏好。

        Prompt 模板:
            给定以下用户操作记录，请判断是否存在隐式偏好：
            事件类型: {event_type}
            内容: {content}
            ...
        """
        raise NotImplementedError

    def _classify_type(self, text: str) -> PreferenceType:
        """对偏好文本进行类型分类"""
        raise NotImplementedError

    def _build_evidence(self, event: MemoryEvent):
        """从事件构建证据链"""
        raise NotImplementedError
