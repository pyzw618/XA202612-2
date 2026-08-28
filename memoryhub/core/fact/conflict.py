"""
冲突检测模块

两阶段：
1. check() — 代码快速查找冲突（不调 LLM）
   无已有 → NEW
   有已有+同object_id → DUPLICATE
   有已有+不同object_id → CONFLICT（触发阶段 2）
2. resolve() — 兼容入口，仅返回 escalate，交由主 Agent 或用户裁决
"""

import logging

from .models import ConflictResult, Fact, Resolution
from .store import FactStore

logger = logging.getLogger(__name__)

class ConflictDetector:
    """写时确定性冲突检测；语义裁决由宿主 Agent 完成。"""

    def __init__(self, store: FactStore, api_key: str = "", llm_client=None):
        self.store = store

    # ─── 阶段 1: 代码检测（不调 LLM）─────────────────────────────────

    def check(self, fact: Fact) -> ConflictResult:
        """
        代码快速查找冲突。只返回 NEW / DUPLICATE / CONFLICT。

        CONFLICT 的 relation 表示"客体不同，需要 LLM 裁决"。
        """
        predicate = self.store.get_predicate(fact.predicate_id)
        if predicate is None:
            return ConflictResult(
                relation="NEW",
                new_fact=fact,
                reason=f"未知谓词 '{fact.predicate_id}'，按新事实处理",
            )

        existing = self.store.find_facts_by_sp(
            fact.subject_id,
            fact.predicate_id,
            scope=fact.scope,
            project_id=fact.project_id,
            user_id=fact.user_id,
        )

        if not existing:
            return ConflictResult("NEW", fact, reason="新事实，无已有记录")

        # 多值谓词：检查完全重复，否则共存
        if not predicate.single_value:
            for old in existing:
                if old.object_id == fact.object_id and old.object_value == fact.object_value:
                    return ConflictResult(
                        "DUPLICATE", fact, old,
                        reason=f"与已有事实完全相同（谓词 '{predicate.canonical_name}' 允许多值）",
                    )
            return ConflictResult(
                "COEXIST", fact, existing[0],
                reason=f"谓词 '{predicate.canonical_name}' 允许多值，新值可共存",
            )

        # 单值谓词
        for old in existing:
            if old.object_id == fact.object_id:
                return ConflictResult(
                    "DUPLICATE", fact, old,
                    reason=f"相同主体、谓词、客体（已有: {old.object_value}）",
                )

        old_strs = [f"{o.object_value} (id={o.object_id})" for o in existing]
        return ConflictResult(
            "CONFLICT", fact, existing[0],
            reason=f"单值谓词 '{predicate.canonical_name}' 冲突: 已有={', '.join(old_strs)}, 新={fact.object_value}",
        )

    # ─── 阶段 2: 委托宿主 Agent / 用户裁决 ────────────────────────────

    def resolve(self, result: ConflictResult) -> ConflictResult:
        """
        保留旧方法签名以兼容调用方，但不再发起内部 LLM API call。
        """
        if result.relation != "CONFLICT":
            return result

        result.resolution = Resolution.ESCALATE.value
        result.reason = f"[等待主Agent裁决] {result.reason}"
        return result
