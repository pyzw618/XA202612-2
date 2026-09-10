"""live 指标计算的离线单元测试。

重点覆盖两处相对旧实现的修正，以及"越界"与"漏排"必须分开统计这一点。
"""

from __future__ import annotations

from typing import Any

from evaluation.live.metrics_retrieval import (
    evaluate_query,
    evaluate_retrieval,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.live.seeding import EvalUser

USER = EvalUser(user_id="run1", run_tag="run1")


class FakeClient:
    """按 *query_text* 返回预置检索结果。

    返回的 id 会加上评测身份前缀，模拟真机服务返回的是已命名空间的 memory_id
    ——这正是"查询侧与播种侧改写必须一致"的现实约束。
    """

    def __init__(self, responses: dict[str, list[str]], latency_ms: float = 1.0,
                 prefix: str = "run1__") -> None:
        self.responses = responses
        self.latency_ms = latency_ms
        self.prefix = prefix
        self.calls: list[dict[str, Any]] = []

    def search_capture_latency(self, **kwargs: Any) -> tuple[dict[str, Any], float]:
        self.calls.append(kwargs)
        query = kwargs["query"]
        ids = self.responses.get(query, [])
        return (
            {
                "served": "vnext",
                "results": [
                    {"memory_id": f"{self.prefix}{memory_id}", "score": 1.0}
                    for memory_id in ids
                ],
                "total_count": len(ids),
                "latency_ms": self.latency_ms,
            },
            self.latency_ms,
        )


def _query(**overrides: Any) -> dict[str, Any]:
    query = {
        "query_id": "q1",
        "query_text": "如何生成周报",
        "difficulty": "exact",
        "context": {"scene": "office", "task_type": "office.report", "app": "agent"},
        "project_id": "proj",
        "relevance": {"m1": 3},
        "scope_blocked": [],
    }
    query.update(overrides)
    return query


# ------------------------------------------------------ 指标函数本身


def test_recall_returns_none_for_empty_relevance() -> None:
    """旧实现对空相关集返回 1.0，等于给 no_answer 白送满分。"""
    assert recall_at_k({}, ["a", "b"], 5) is None


def test_recall_dedupes_retrieved_side() -> None:
    """旧实现不去重，重复 id 会重复计分，召回可超过 1.0。"""
    assert recall_at_k({"m1": 3}, ["m1", "m1", "m1"], 5) == 1.0
    assert recall_at_k({"m1": 3, "m2": 3}, ["m1", "m1", "m1"], 5) == 0.5


def test_recall_respects_k_window() -> None:
    assert recall_at_k({"m2": 3}, ["m1", "m2"], 1) == 0.0
    assert recall_at_k({"m2": 3}, ["m1", "m2"], 2) == 1.0


def test_precision_and_mrr_basic() -> None:
    relevance = {"m2": 3}
    assert precision_at_k(relevance, ["m1", "m2"], 2) == 0.5
    assert reciprocal_rank(relevance, ["m1", "m2"]) == 0.5


def test_ndcg_is_one_for_ideal_ordering() -> None:
    assert ndcg_at_k({"m1": 3}, ["m1"], 1) == 1.0
    assert ndcg_at_k({"m1": 3}, ["other", "m1"], 2) < 1.0


# ------------------------------------------------------ 单查询评估


def test_target_hit_is_scored_correctly() -> None:
    client = FakeClient({"如何生成周报": ["m1"]})
    outcome = evaluate_query(client, _query(), USER, top_k=5)
    assert outcome.recall_5 == 1.0
    assert outcome.isolation_violations == []


def test_scope_blocked_hit_is_reported_as_isolation_violation() -> None:
    """越界项被返回时不能算作"排序成功"，要单独计为隔离违规。

    违规 id 保留服务返回的命名空间前缀，以便直接与真机结果对账。
    """
    client = FakeClient({"如何生成周报": ["x1", "m1"]})
    outcome = evaluate_query(client, _query(scope_blocked=["x1"]), USER, top_k=5)
    assert outcome.recall_5 == 1.0
    assert outcome.isolation_violations == ["run1__x1"]


def test_no_answer_query_is_ok_only_when_nothing_returned() -> None:
    empty = evaluate_query(FakeClient({"如何生成周报": []}), _query(relevance={}), USER)
    assert empty.no_answer_ok is True
    assert empty.recall_5 is None

    noisy = evaluate_query(FakeClient({"如何生成周报": ["m9"]}), _query(relevance={}), USER)
    assert noisy.no_answer_ok is False


def test_scoped_mode_sends_scope_and_unscoped_does_not() -> None:
    client = FakeClient({"如何生成周报": ["m1"]})
    evaluate_query(client, _query(), USER, scoped=True)
    evaluate_query(client, _query(), USER, scoped=False)
    assert client.calls[0]["context"] == {"scene": "office", "task_type": "office.report", "app": "agent"}
    assert client.calls[0]["project_id"] == "run1__proj"
    assert client.calls[1]["context"] is None
    assert client.calls[1]["project_id"] == ""


def test_query_and_memory_namespacing_agree() -> None:
    """查询侧与播种侧的 id/项目改写必须一致，否则相关记忆永远不可达。"""
    mapped = USER.map_query(_query())
    assert mapped["relevance"] == {"run1__m1": 3}
    assert mapped["project_id"] == "run1__proj"
    assert USER.map_memory({"id": "m1", "project_id": "proj"})["memory_id"] == "run1__m1"


# ------------------------------------------------------ 聚合


def test_aggregate_separates_isolation_from_ranking() -> None:
    queries = [
        _query(query_id="q1"),
        _query(query_id="q2", query_text="另一个问题", relevance={"m2": 3}, scope_blocked=["x"]),
        _query(query_id="q3", query_text="无答案", difficulty="no_answer", relevance={}),
    ]
    client = FakeClient({
        "如何生成周报": ["m1"],
        "另一个问题": ["x"],       # 越界项被返回且目标漏排
        "无答案": [],
    })
    report = evaluate_retrieval(client, queries, USER, top_k=5, scoped=True)

    assert report["total_queries"] == 3
    assert report["scored_queries"] == 2
    assert report["no_answer_queries"] == 1
    assert report["recall_at_k"] == 0.5           # q1 命中，q2 漏排
    assert report["isolation_violation_count"] == 1
    assert report["no_answer_precision"] == 1.0


def test_aggregate_counts_failures_without_polluting_recall() -> None:
    class BrokenClient(FakeClient):
        def search_capture_latency(self, **kwargs: Any):
            from evaluation.live.client import ServiceUnavailable

            raise ServiceUnavailable("boom")

    report = evaluate_retrieval(BrokenClient({}), [_query()], USER)
    assert report["failed_queries"] == 1
    assert report["scored_queries"] == 0
    assert report["recall_at_k"] == 0.0


# ------------------------------------------------------ 冲突结果读取


class _ConflictClient:
    """只实现 run_case 所需接口的桩客户端。"""

    def __init__(self, conflicts: list[dict], processing: bool = True) -> None:
        self._conflicts = conflicts
        self._processing = processing

    def agent_step(self, payload):
        return {"processing": {"preferences_written": ["p1"]}} if self._processing else {}

    def list_conflicts(self, *, user_id, status=None, memory_type=None, size=200):
        return self._conflicts

    def list_preferences(self, *, user_id, status="active"):
        return [{"memory_id": "p1"}, {"memory_id": "p2"}]


def test_conflict_is_found_by_user_not_by_memory_id() -> None:
    """回归：曾按 memory_id 匹配却传了空串，导致永远匹配失败。

    结果是把"冲突已正确创建"误报成"驱动失败"，静默吞掉真实结果。
    """
    from evaluation.live.metrics_conflict import evaluate_conflict

    dataset = {
        "samples": [
            {
                "case_id": "c1", "block": "preference_native",
                "old_text": "以后办公场景都用 markdown 格式",
                "new_text": "以后办公场景都用 html 格式",
                "old_scene": "office", "new_scene": "office",
                "expected_decision": "override", "expects_conflict_record": True,
            }
        ]
    }
    client = _ConflictClient([{"conflict_id": "x", "decision": "override"}])
    report = evaluate_conflict(client, dataset, USER)
    assert report["drive_failure_count"] == 0
    assert report["scored_cases"] == 1
    assert report["accuracy"] == 1.0
    assert report["sample_results"][0]["observed_decision"] == "override"


def test_missing_conflict_record_counts_against_end_to_end_accuracy() -> None:
    """未关联的偏好对在端到端口径下计为未正确处理。

    报告以端到端为 headline：系统没能把两条偏好关联起来时，用户看到的就是
    "处理失败"，不能因为"关联之后没算错"就从分母里消失。条件正确率另给。
    """
    from evaluation.live.metrics_conflict import evaluate_conflict

    dataset = {
        "samples": [
            {
                "case_id": "c1", "block": "preference_native",
                "old_text": "a markdown 格式", "new_text": "b html 格式",
                "old_scene": "office", "new_scene": "office",
                "expected_decision": "override", "expects_conflict_record": True,
            }
        ]
    }
    report = evaluate_conflict(_ConflictClient([]), dataset, USER)
    assert report["drive_failure_count"] == 1
    assert report["scored_cases"] == 0
    # 端到端：1 例全错 → 0.0；条件值无样本 → None
    assert report["accuracy"] == 0.0
    assert report["accuracy_conditional"] is None
