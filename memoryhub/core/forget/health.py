"""记忆健康度计算模块

基于时间衰减与使用频率，为每条记忆计算一个 [0, 1] 区间的健康度分数。
分数越低，记忆越容易被遗忘/降级。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory


def _as_datetime(value):
    """Normalize datetime/ISO values to naive UTC for safe subtraction."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@dataclass
class HealthFactors:
    """健康度计算所需因子（第一版只保留两个核心因子）"""

    time_decay: float
    usage_frequency: float


class HealthCalculator:
    """
    记忆健康度计算器

    使用方式:
        calc = HealthCalculator()
        score = calc.calculate(memory)

    第一版仅使用两个核心因子：
    1. 时间衰减：基于 Ebbinghaus 遗忘曲线 R = e^(-t/S)
    2. 使用频率：基于近 30 天访问次数
    """

    DEFAULT_HALF_LIFE_DAYS = 30.0

    def calculate(self, memory: PreferenceMemory | KnowledgeMemory) -> float:
        """
        计算单条记忆的健康度

        参数:
            memory: 偏好记忆或知识记忆

        返回:
            [0, 1] 区间的健康度分数
        """
        factors = HealthFactors(
            time_decay=self._time_decay_factor(memory),
            usage_frequency=self._usage_frequency_factor(memory),
        )

        # 第一版：时间衰减 60%，使用频率 40%
        score = 0.6 * factors.time_decay + 0.4 * factors.usage_frequency

        # 置信度兜底：置信度越低，健康度上限越低
        score = min(score, getattr(memory, "confidence", 1.0) or 1.0)

        return max(0.0, min(1.0, score))

    def _time_decay_factor(self, memory) -> float:
        """
        基于 Ebbinghaus 遗忘曲线计算时间衰减因子。

        公式：R = e^(-t / S)
        t 为距上次更新/访问的天数，S 为记忆稳定性。
        稳定性越高，衰减越慢。
        """
        now = datetime.now()
        anchor = _as_datetime(
            getattr(memory, "last_accessed_at", None)
            or getattr(memory, "updated_at", None)
            or getattr(memory, "created_at", None)
            or getattr(memory, "observed_at", None)
        )
        if anchor is None:
            days = 0.0
        else:
            days = max(0.0, (now - anchor).total_seconds() / 86400.0)

        # 使用频率越高，稳定性越强
        stability = max(
            1.0,
            (getattr(memory, "stability", 1.0) or 1.0)
            * (1 + (getattr(memory, "access_count_30d", 0) or 0) / 10.0),
        )

        return math.exp(-days / stability)

    def _usage_frequency_factor(self, memory) -> float:
        """
        使用频率因子：近 30 天访问次数越多，记忆越健康。
        """
        hits = getattr(memory, "access_count_30d", 0) or 0
        return min(1.0, hits / 5.0)

    def calculate_from_row(self, row) -> float:
        """
        从 SQLAlchemy Row 对象计算健康度。
        数据库相关字段：health_score, stability, last_accessed_at, updated_at,
                       created_at, access_count_30d, confidence
        """
        # 从数据库行对象计算健康度，支持 ORM Row 和 Pydantic 模型两种输入。
        now = datetime.now()
        last_accessed = _as_datetime(
            getattr(row, "last_accessed_at", None)
            or getattr(row, "updated_at", None)
            or getattr(row, "created_at", None)
            or getattr(row, "observed_at", None)
        )
        days = 0.0
        if last_accessed is not None:
            days = max(0.0, (now - last_accessed).total_seconds() / 86400.0)

        stability = max(1.0, (getattr(row, "stability", 1.0) or 1.0) * (1 + (getattr(row, "access_count_30d", 0) or 0) / 10.0))
        time_decay = math.exp(-days / stability)

        hits = getattr(row, "access_count_30d", 0) or 0
        usage = min(1.0, hits / 5.0)

        score = 0.6 * time_decay + 0.4 * usage
        confidence = getattr(row, "confidence", 1.0) or 1.0
        return max(0.0, min(1.0, min(score, confidence)))
