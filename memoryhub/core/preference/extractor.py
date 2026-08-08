"""
偏好抽取模块

从 MemoryEvent 中提取用户偏好，支持规则抽取和 LLM 辅助抽取。
"""

import re

from memoryhub.adapter.schemas import (
    Evidence,
    MemoryEvent,
    PreferenceMemory,
    PreferenceType,
    SceneScope,
    SourceType,
)


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
        candidates = self._rule_extract(event)
        if self.llm_client is not None and self.llm_client.is_available():
            candidates.extend(self._llm_extract(event))

        unique: dict[tuple[str, str], PreferenceMemory] = {}
        for preference in candidates:
            key = (preference.preference_type.value, preference.content.strip().lower())
            unique[key] = preference
        return list(unique.values())

    def _rule_extract(self, event: MemoryEvent) -> list[PreferenceMemory]:
        """
        规则模板抽取（显式偏好）

        匹配模式示例:
            "以后都用 X" → output_style
            "默认使用 X" → tool_preference / format_preference
            "不要记住 X" → safety_preference
            "每次都先 Y 再 Z" → workflow_preference
        """
        if event.source_type not in {SourceType.USER_BEHAVIOR, SourceType.MANUAL_CONFIG}:
            return []

        if event.source_type is SourceType.MANUAL_CONFIG:
            key = str(event.payload.get("key", "")).strip()
            value = event.payload.get("value", "")
            if not key:
                return []
            text = f"默认配置 {key}={value}"
        else:
            text = self._event_text(event)

        text = re.sub(r"\s+", " ", text).strip()
        if not text or any(marker in text for marker in ("忘掉", "忘记", "删除记忆")):
            return []

        explicit_markers = (
            "以后",
            "今后",
            "默认",
            "每次",
            "一直",
            "都用",
            "都使用",
            "我喜欢",
            "我偏好",
            "优先",
            "不要",
            "必须",
        )
        if event.source_type is SourceType.USER_BEHAVIOR and not any(
            marker in text for marker in explicit_markers
        ):
            return []

        return [
            PreferenceMemory(
                user_id=event.user_id,
                preference_type=self._classify_type(text),
                content=text,
                scope=SceneScope(
                    scene=event.scene,
                    task_type=event.task_type,
                    app=str(event.payload.get("app", "os_agent")),
                ),
                confidence=max(0.8, event.quality.score),
                evidences=[self._build_evidence(event)],
            )
        ]

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
        # The minimal service deliberately learns only explicit preferences.
        # An LLM extractor can be added later without changing the API contract.
        return []

    def _classify_type(self, text: str) -> PreferenceType:
        """对偏好文本进行类型分类"""
        lowered = text.lower()
        if any(word in lowered for word in ("语言", "中文", "英文", "english")):
            return PreferenceType.LANGUAGE_PREF
        if any(word in lowered for word in ("安全", "隐私", "敏感", "不要记住")):
            return PreferenceType.SAFETY_PREF
        if any(word in lowered for word in ("先", "再", "步骤", "流程")):
            return PreferenceType.WORKFLOW_PREF
        if any(word in lowered for word in ("工具", "搜索", "日历", "本地")):
            return PreferenceType.TOOL_PREFERENCE
        if any(
            word in lowered
            for word in ("格式", "markdown", "word", "pdf", "三段", "模板")
        ):
            return PreferenceType.FORMAT_PREF
        return PreferenceType.OUTPUT_STYLE

    def _build_evidence(self, event: MemoryEvent):
        """从事件构建证据链"""
        return Evidence(
            event_id=event.event_id,
            content=self._event_text(event)[:500],
            source_type=event.source_type,
            weight=event.quality.score,
        )

    @staticmethod
    def _event_text(event: MemoryEvent) -> str:
        if event.text:
            return event.text
        for key in ("text", "value", "content", "message"):
            value = event.payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
