"""
敏感信息检测模块

在记忆写入前识别和处理敏感信息。
"""

import re

from memoryhub.adapter.schemas import MemoryEvent, SensitiveLevel


class SensitiveDetector:
    """
    敏感信息检测器

    使用方式:
        detector = SensitiveDetector()
        level = detector.detect(event)
        cleaned = detector.mask(event)
    """

    # 默认检测规则
    DEFAULT_PATTERNS = {
        "api_key": r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*\S+",
        "id_card": r"\b\d{17}[\dXx]\b",
        "phone": r"\b1[3-9]\d{9}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    }

    def __init__(self, custom_patterns: dict[str, str] | None = None):
        """
        参数:
            custom_patterns: 自定义检测规则，格式同 DEFAULT_PATTERNS
        """
        self.patterns = {**self.DEFAULT_PATTERNS}
        if custom_patterns:
            self.patterns.update(custom_patterns)

    def detect(self, event: MemoryEvent) -> SensitiveLevel:
        """
        检测事件中的敏感信息等级

        数据流: MemoryEvent → detect → SensitiveLevel

        参数:
            event: 标准化事件

        返回:
            SensitiveLevel: NONE / LOW / MEDIUM / HIGH

        判定规则:
            - HIGH: 包含 API Key、密码、身份证号
            - MEDIUM: 包含手机号、邮箱
            - LOW: 包含 IP 地址等
            - NONE: 无敏感信息
        """
        raise NotImplementedError

    def detect_text(self, text: str) -> tuple[SensitiveLevel, list[str]]:
        """
        检测文本中的敏感信息

        参数:
            text: 待检测文本

        返回:
            (sensitive_level, matched_patterns): 敏感等级和匹配到的模式名列表
        """
        raise NotImplementedError

    def mask(self, event: MemoryEvent) -> MemoryEvent:
        """
        对事件中的敏感信息进行脱敏处理

        数据流: MemoryEvent → mask → 脱敏后的 MemoryEvent

        参数:
            event: 原始事件

        返回:
            脱敏后的新 MemoryEvent（不修改原对象）

        脱敏策略:
            - API Key → [REDACTED_API_KEY]
            - 手机号 → 138****1234
            - 邮箱 → u***@example.com
            - 身份证 → 110***********1234
        """
        raise NotImplementedError

    def mask_text(self, text: str) -> str:
        """对文本进行脱敏"""
        raise NotImplementedError

    def should_reject(self, event: MemoryEvent) -> tuple[bool, str]:
        """
        判断事件是否应被拒绝入库

        参数:
            event: 待检测事件

        返回:
            (should_reject, reason): 是否拒绝及原因

        规则:
            - HIGH 级别且 reject_on_detect=True → 拒绝
            - 其他 → 不拒绝（交给 mask 处理）
        """
        raise NotImplementedError
