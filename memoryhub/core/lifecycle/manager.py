"""
记忆生命周期管理模块

管理短期、中期、长期记忆之间的流转。
"""

from memoryhub.adapter.schemas import MemoryEvent, MemoryLevel


class LifecycleManager:
    """
    记忆生命周期管理器

    使用方式:
        manager = LifecycleManager()
        level = manager.classify(event)
        manager.promote(memory_id, from_level, to_level)
    """

    # 流转阈值配置
    PROMOTE_THRESHOLDS = {
        "short_to_mid": {
            "min_occurrences": 2,        # 至少出现 2 次
            "min_quality_score": 0.4,    # event.quality.score >= 0.4
        },
        "mid_to_long": {
            "min_occurrences": 5,        # 至少出现 5 次
            "min_confidence": 0.7,       # 置信度 >= 0.7
            "min_days": 3,               # 至少存在 3 天
            "user_confirmed": False,     # 是否需要用户确认
        },
    }

    # 淘汰配置
    DEMOTE_THRESHOLDS = {
        "mid_expire_days": 30,           # 中期记忆 30 天无更新则过期
        "long_expire_days": 365,         # 长期记忆 365 天无更新则审查
    }

    def classify(self, event: MemoryEvent) -> MemoryLevel:
        """
        对新事件进行记忆层级分类

        数据流: MemoryEvent → classify → MemoryLevel

        参数:
            event: 标准化事件

        返回:
            建议的 MemoryLevel

        分类规则:
            - 低质量/单次事件 → SHORT
            - 中等质量/有重复 → MID
            - 高质量/用户确认 → LONG
        """
        raise NotImplementedError

    def should_promote(self, memory_id: str, current_level: MemoryLevel) -> bool:
        """
        判断记忆是否应升级

        数据流: 定期检查 → should_promote → True/False

        参数:
            memory_id: 记忆 ID
            current_level: 当前层级

        返回:
            是否应升级

        升级条件:
            SHORT → MID: 出现次数 >= 2 且质量评分 >= 0.4
            MID → LONG: 出现次数 >= 5 且置信度 >= 0.7 且存在 >= 3 天
        """
        raise NotImplementedError

    def promote(self, memory_id: str, from_level: MemoryLevel, to_level: MemoryLevel) -> bool:
        """
        执行记忆升级

        数据流: should_promote=True → promote → 更新 level 字段

        参数:
            memory_id: 记忆 ID
            from_level: 原层级
            to_level: 目标层级

        返回:
            是否成功
        """
        raise NotImplementedError

    def should_expire(self, memory_id: str, current_level: MemoryLevel) -> bool:
        """
        判断记忆是否应过期/降级

        参数:
            memory_id: 记忆 ID
            current_level: 当前层级

        返回:
            是否应过期

        过期规则:
            MID: 30 天无更新 → 标记过期
            LONG: 365 天无更新 → 审查
        """
        raise NotImplementedError

    def expire(self, memory_id: str) -> bool:
        """
        将记忆标记为过期（archived）

        返回:
            是否成功
        """
        raise NotImplementedError

    def run_lifecycle_check(self) -> dict:
        """
        执行一次完整的生命周期检查（定时任务调用）

        数据流:
            定时触发 → run_lifecycle_check
              → 遍历所有记忆
              → 检查升级条件
              → 检查过期条件
              → 执行流转

        返回:
            {
                "promoted": int,     # 升级数量
                "expired": int,      # 过期数量
                "checked": int,      # 检查总数
            }
        """
        raise NotImplementedError
