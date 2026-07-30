"""自动遗忘引擎

定时扫描活跃记忆，根据健康度执行降级/归档。
第一版采用硬阈值策略，不物理删除，只改状态/层级。
"""

from memoryhub.adapter.schemas import MemoryLevel, MemoryStatus
from memoryhub.core.forget.health import HealthCalculator


class AutoForgetEngine:
    """
    自动遗忘引擎

    使用方式:
        engine = AutoForgetEngine(db=db, calculator=HealthCalculator())
        stats = engine.run()

    策略：
    - health < 0.2：归档（archived）
    - health < 0.4：降级（long → mid → short）
    - health < 0.6：标记为待审查（pending_review）
    - health >= 0.6：保持活跃
    """

    ARCHIVE_THRESHOLD = 0.2
    DEMOTE_THRESHOLD = 0.4
    REVIEW_THRESHOLD = 0.6

    def __init__(self, db=None, calculator: HealthCalculator | None = None):
        """
        参数:
            db: 数据库存储实例（伪代码阶段，接口待定）
            calculator: 健康度计算器
        """
        self.db = db
        self.calculator = calculator or HealthCalculator()

    def run(self) -> dict:
        """
        执行一次自动遗忘扫描。

        返回:
            {"archived": int, "demoted": int, "reviewed": int, "kept": int}
        """
        stats = {"archived": 0, "demoted": 0, "reviewed": 0, "kept": 0}

        # PSEUDO-DB: 从数据库读取所有 status = active 的记忆（preferences + knowledge）
        # active_memories = db.query(...).filter(status == "active").all()
        active_memories = []

        for memory in active_memories:
            # PSEUDO-DB: 实际计算时应从 row 对象构造 HealthCalculator 输入
            health = self.calculator.calculate_from_row(memory)

            if health < self.ARCHIVE_THRESHOLD:
                # PSEUDO-DB: UPDATE preferences/knowledge SET status='archived', health_score=? WHERE memory_id=?
                stats["archived"] += 1
            elif health < self.DEMOTE_THRESHOLD:
                # PSEUDO-DB: UPDATE preferences/knowledge SET level=?, health_score=? WHERE memory_id=?
                self._demote(memory)
                stats["demoted"] += 1
            elif health < self.REVIEW_THRESHOLD:
                # PSEUDO-DB: UPDATE preferences/knowledge SET status='pending', health_score=? WHERE memory_id=?
                stats["reviewed"] += 1
            else:
                stats["kept"] += 1

        return stats

    def _demote(self, memory) -> None:
        """将记忆层级降级：long → mid → short"""
        level_order = ["long", "mid", "short"]
        current = getattr(memory, "level", "long") or "long"
        idx = level_order.index(current) if current in level_order else 0
        new_level = level_order[min(idx + 1, len(level_order) - 1)]

        # PSEUDO-DB: UPDATE preferences/knowledge SET level=? WHERE memory_id=?
        _ = new_level
