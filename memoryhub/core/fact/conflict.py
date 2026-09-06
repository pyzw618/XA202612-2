"""
冲突检测模块

两阶段：
1. check() — 代码执行关系本体归一化和结构性冲突检测（不调 LLM）
   覆盖直接/逆向/对称等价、双向基数、互斥、类型、自反与成环约束
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
        代码快速查找冲突。返回 NEW / DUPLICATE / CONFLICT / COEXIST。

        CONFLICT 表示需要主 Agent展示依据并请求用户裁决。
        """
        predicate = self.store.get_predicate(fact.predicate_id)
        if predicate is None:
            return ConflictResult(
                relation="NEW",
                new_fact=fact,
                reason=f"未知谓词 '{fact.predicate_id}'，按新事实处理",
            )

        validation = self._validate_shape(fact, predicate)
        if validation is not None:
            return validation

        existing = self.store.list_facts(
            status="active",
            limit=10000,
            scope=fact.scope,
            project_id=fact.project_id,
            user_id=fact.user_id,
        )
        new_key = self._canonical_key(fact, predicate)
        related = []
        for old in existing:
            old_predicate = self.store.get_predicate(old.predicate_id)
            if old_predicate is None:
                continue
            old_key = self._canonical_key(old, old_predicate)
            if old_key[0] == new_key[0]:
                related.append((old, old_key))
                if old_key == new_key:
                    relation_kind = (
                        "inverse_equivalent"
                        if old.predicate_id != fact.predicate_id
                        else "symmetric_equivalent"
                        if predicate.symmetric and old.subject_id == fact.object_id
                        else "direct_duplicate"
                    )
                    return ConflictResult(
                        "DUPLICATE", fact, old,
                        reason="新旧陈述在关系本体归一化后等价",
                        conflict_type=relation_kind,
                    )

            if (
                old.subject_id == fact.subject_id
                and old.predicate_id in predicate.exclusive_with
            ):
                return ConflictResult(
                    "CONFLICT", fact, old,
                    reason="同一主体出现互斥关系",
                    conflict_type="mutually_exclusive_predicate",
                )

        canonical_predicate = self.store.get_predicate(new_key[0]) or predicate
        for old, old_key in related:
            if old_key[1] == new_key[1] and old_key[2] != new_key[2]:
                if canonical_predicate.single_value:
                    return ConflictResult(
                        "CONFLICT", fact, old,
                        reason="同一主体的单值关系出现不同客体",
                        conflict_type="subject_cardinality",
                    )
            if old_key[2] == new_key[2] and old_key[1] != new_key[1]:
                if canonical_predicate.object_single_value:
                    return ConflictResult(
                        "CONFLICT", fact, old,
                        reason="同一客体的逆向单值关系出现不同主体",
                        conflict_type="object_cardinality",
                    )

        if canonical_predicate.acyclic and self._creates_cycle(new_key, related):
            return ConflictResult(
                "CONFLICT", fact,
                reason="该关系要求无环，新事实会形成关系环",
                conflict_type="relation_cycle",
            )

        same_subject = [old for old, key in related if key[1] == new_key[1]]
        if same_subject:
            return ConflictResult(
                "COEXIST", fact, same_subject[0],
                reason=f"谓词 '{canonical_predicate.canonical_name}' 允许多值，新值可共存",
            )
        return ConflictResult("NEW", fact, reason="新事实，无已有等价或冲突记录")

    def _canonical_key(self, fact: Fact, predicate) -> tuple[str, str, str]:
        """把直接、逆向和对称写法映射到同一个关系坐标系。"""
        predicate_id = predicate.predicate_id
        subject_id, object_id = fact.subject_id, fact.object_id
        if predicate.symmetric:
            subject_id, object_id = sorted((subject_id, object_id))
        elif predicate.inverse_of and predicate_id > predicate.inverse_of:
            predicate_id = predicate.inverse_of
            subject_id, object_id = object_id, subject_id
        return predicate_id, subject_id, object_id

    def _validate_shape(self, fact: Fact, predicate) -> ConflictResult | None:
        subject = self.store.get_entity(fact.subject_id, user_id=fact.user_id)
        obj = self.store.get_entity(fact.object_id, user_id=fact.user_id)
        if predicate.irreflexive and fact.subject_id == fact.object_id:
            return ConflictResult(
                "CONFLICT", fact,
                reason="该关系不允许主体与客体相同",
                conflict_type="irreflexive_violation",
            )
        if (
            subject
            and subject.entity_type != "Other"
            and predicate.domain
            and subject.entity_type not in predicate.domain
        ):
            return ConflictResult(
                "CONFLICT", fact,
                reason=f"主体类型 {subject.entity_type} 不符合谓词 domain",
                conflict_type="domain_type_violation",
            )
        if (
            obj
            and obj.entity_type != "Other"
            and predicate.range
            and obj.entity_type not in predicate.range
        ):
            return ConflictResult(
                "CONFLICT", fact,
                reason=f"客体类型 {obj.entity_type} 不符合谓词 range",
                conflict_type="range_type_violation",
            )
        return None

    @staticmethod
    def _creates_cycle(
        new_key: tuple[str, str, str],
        related: list[tuple[Fact, tuple[str, str, str]]],
    ) -> bool:
        _, start, end = new_key
        graph: dict[str, set[str]] = {}
        for _, (_, left, right) in related:
            graph.setdefault(left, set()).add(right)
        pending = [end]
        seen = set()
        while pending:
            node = pending.pop()
            if node == start:
                return True
            if node in seen:
                continue
            seen.add(node)
            pending.extend(graph.get(node, ()))
        return False

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
