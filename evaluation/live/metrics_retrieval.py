"""知识检索召回率与延迟（真机 HTTP 路径）。

**相对进程内评估器修正的两处指标缺陷**

``evaluation/runners/run_retrieval_eval.py`` 的 ``recall_at_k``：

1. 空相关集返回 ``1.0`` —— ``no_answer`` 查询因此白送满分，把无答案能力的
   缺陷掩盖成正例；
2. ``retrieved`` 侧不去重 —— 重复 id 会被重复计数，召回率可超过 1.0。

本模块：空相关集返回 ``None``（不计入召回均值，改用独立的
``no_answer_precision`` 衡量），retrieved 侧保序去重。

**为什么召回等价于"目标是否落在 top-K"**

v2 数据集每条查询只有一个等级 ≥2 的记忆（见生成器的相关性分级说明），因此
``hits / len(relevant)`` 恰好等价于 hit@K。这比"多个相关项都要召回"的总量
召回更贴合赛题"召回率"的直观口径，也更容易向评委解释。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from evaluation.live.client import LiveClient, LiveClientError
from evaluation.live.seeding import EvalUser
from evaluation.live.stats import dcg, latency_summary, mean

MIN_RELEVANT_GRADE = 2


def dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def recall_at_k(
    relevance: dict[str, int], retrieved: list[str], k: int,
    min_rel: int = MIN_RELEVANT_GRADE,
) -> float | None:
    """返回 None 表示该查询没有相关项（``no_answer``），不应计入召回均值。"""
    relevant = {memory_id for memory_id, grade in relevance.items() if grade >= min_rel}
    if not relevant:
        return None
    top_k = dedupe_preserving_order(retrieved[:k])
    hits = sum(1 for memory_id in top_k if memory_id in relevant)
    return hits / len(relevant)


def precision_at_k(
    relevance: dict[str, int], retrieved: list[str], k: int,
    min_rel: int = MIN_RELEVANT_GRADE,
) -> float:
    if k <= 0:
        return 0.0
    relevant = {memory_id for memory_id, grade in relevance.items() if grade >= min_rel}
    top_k = dedupe_preserving_order(retrieved[:k])
    return sum(1 for memory_id in top_k if memory_id in relevant) / k


def reciprocal_rank(
    relevance: dict[str, int], retrieved: list[str],
    min_rel: int = MIN_RELEVANT_GRADE,
) -> float:
    relevant = {memory_id for memory_id, grade in relevance.items() if grade >= min_rel}
    for rank, memory_id in enumerate(dedupe_preserving_order(retrieved), start=1):
        if memory_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: dict[str, int], retrieved: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top_k = dedupe_preserving_order(retrieved[:k])
    actual = dcg([relevance.get(memory_id, 0) for memory_id in top_k], k)
    ideal = dcg(sorted(relevance.values(), reverse=True), k)
    return actual / ideal if ideal > 0 else 0.0


@dataclass
class QueryOutcome:
    """单条查询的结果。"""

    query_id: str
    difficulty: str
    relevant_count: int
    retrieved: list[str] = field(default_factory=list)
    recall_5: float | None = None
    recall_10: float | None = None
    precision_5: float = 0.0
    mrr: float = 0.0
    ndcg_5: float = 0.0
    isolation_violations: list[str] = field(default_factory=list)
    no_answer_ok: bool | None = None
    client_e2e_ms: float = 0.0
    server_latency_ms: float = 0.0
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "difficulty": self.difficulty,
            "relevant_count": self.relevant_count,
            "retrieved": self.retrieved[:10],
            "recall_5": self.recall_5,
            "recall_10": self.recall_10,
            "precision_5": round(self.precision_5, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_5": round(self.ndcg_5, 4),
            "isolation_violations": self.isolation_violations,
            "no_answer_ok": self.no_answer_ok,
            "client_e2e_ms": round(self.client_e2e_ms, 2),
            "server_latency_ms": round(self.server_latency_ms, 2),
            "error": self.error,
        }


def evaluate_query(
    client: LiveClient,
    query: dict[str, Any],
    user: EvalUser,
    *,
    top_k: int = 5,
    scoped: bool = True,
) -> QueryOutcome:
    """执行单条查询并打分。

    ``scoped=False`` 时不发送 ``context``/``project_id``，用于观测"纯排序能力"
    与"生产真实（受 scope 门约束）"的差距。
    """
    mapped = user.map_query(query)
    relevance: dict[str, int] = mapped.get("relevance") or {}
    blocked = set(mapped.get("scope_blocked") or [])
    outcome = QueryOutcome(
        query_id=str(mapped.get("query_id", "")),
        difficulty=str(mapped.get("difficulty", "")),
        relevant_count=sum(1 for grade in relevance.values() if grade >= MIN_RELEVANT_GRADE),
    )
    try:
        body, elapsed_ms = client.search_capture_latency(
            user_id=user.user_id,
            query=str(mapped.get("query_text", "")),
            top_k=max(top_k, 10),
            context=mapped.get("context") if scoped else None,
            project_id=str(mapped.get("project_id", "")) if scoped else "",
            memory_types=["knowledge"],
        )
    except LiveClientError as exc:
        outcome.error = str(exc)[:200]
        return outcome

    retrieved = [
        str(item.get("memory_id", ""))
        for item in body.get("results", [])
        if item.get("memory_id")
    ]
    outcome.retrieved = dedupe_preserving_order(retrieved)
    outcome.client_e2e_ms = elapsed_ms
    try:
        outcome.server_latency_ms = float(body.get("latency_ms") or 0.0)
    except (TypeError, ValueError):
        outcome.server_latency_ms = 0.0

    outcome.isolation_violations = [mid for mid in outcome.retrieved if mid in blocked]
    if not relevance:
        # no_answer：正确行为是"什么都不返回"。
        outcome.no_answer_ok = len(outcome.retrieved) == 0
        return outcome

    outcome.recall_5 = recall_at_k(relevance, outcome.retrieved, top_k)
    outcome.recall_10 = recall_at_k(relevance, outcome.retrieved, 10)
    outcome.precision_5 = precision_at_k(relevance, outcome.retrieved, top_k)
    outcome.mrr = reciprocal_rank(relevance, outcome.retrieved)
    outcome.ndcg_5 = ndcg_at_k(relevance, outcome.retrieved, top_k)
    return outcome


def evaluate_retrieval(
    client: LiveClient,
    queries: Iterable[dict[str, Any]],
    user: EvalUser,
    *,
    top_k: int = 5,
    scoped: bool = True,
) -> dict[str, Any]:
    """对整份查询集打分并聚合。"""
    outcomes = [
        evaluate_query(client, query, user, top_k=top_k, scoped=scoped)
        for query in queries
    ]
    answered = [o for o in outcomes if not o.error and o.recall_5 is not None]
    no_answer = [o for o in outcomes if not o.error and o.no_answer_ok is not None]
    failed = [o for o in outcomes if o.error]

    recall_5 = [o.recall_5 for o in answered if o.recall_5 is not None]
    recall_10 = [o.recall_10 for o in answered if o.recall_10 is not None]

    by_difficulty: dict[str, dict[str, Any]] = {}
    for difficulty in sorted({o.difficulty for o in answered}):
        group = [o for o in answered if o.difficulty == difficulty]
        by_difficulty[difficulty] = {
            "count": len(group),
            "recall_5": round(mean([o.recall_5 for o in group if o.recall_5 is not None]), 4),
            "mrr": round(mean([o.mrr for o in group]), 4),
            "ndcg_5": round(mean([o.ndcg_5 for o in group]), 4),
        }

    violations = sum(len(o.isolation_violations) for o in outcomes)
    verdict_items = answered + no_answer

    return {
        "mode": "scoped" if scoped else "unscoped",
        "top_k": top_k,
        "total_queries": len(outcomes),
        "scored_queries": len(answered),
        "no_answer_queries": len(no_answer),
        "failed_queries": len(failed),
        "recall_at_k": round(mean(recall_5), 4) if recall_5 else 0.0,
        "recall_at_10": round(mean(recall_10), 4) if recall_10 else 0.0,
        "precision_at_k": round(mean([o.precision_5 for o in answered]), 4) if answered else 0.0,
        "mrr": round(mean([o.mrr for o in answered]), 4) if answered else 0.0,
        "ndcg_at_k": round(mean([o.ndcg_5 for o in answered]), 4) if answered else 0.0,
        "no_answer_precision": (
            round(mean([1.0 if o.no_answer_ok else 0.0 for o in no_answer]), 4)
            if no_answer else None
        ),
        "isolation_violation_count": violations,
        # 越界项只有在 scoped 模式下才构成"隔离失效"：unscoped 模式是我们主动
        # 不发送 scope，系统无从过滤，返回越界项是预期行为而非缺陷。
        "isolation_violation_rate": (
            round(violations / len(verdict_items), 4)
            if verdict_items and scoped else None
        ),
        "latency": latency_summary([o.client_e2e_ms for o in outcomes if not o.error]),
        "by_difficulty": by_difficulty,
        "failures": [o.as_dict() for o in failed][:10],
        "sample_results": [o.as_dict() for o in outcomes[:50]],
    }
