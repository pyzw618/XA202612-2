"""播种后的就绪判定。

**为什么需要三段信号而不是一段**

生产模式下写入只落在 projection outbox，向量投影由每 30 秒一次的 worker
完成（``project_immediately=False``）。因此"接口返回 200"完全不等于
"记忆可被检索"。单独任何一个信号都不足以判断就绪：

1. **outbox 排空** —— 还有待投影项就说明向量还没写完；
2. **reconcile 无漂移** —— 覆盖 ``pending_index=1`` 的补写路径；
3. **canary 可检索** —— 这是唯一能区分"排序确实差"与"索引根本没建"的信号。

没有 canary，一个因索引故障导致的低召回会被误读成"模型效果不好"。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from evaluation.live.client import LiveClient, LiveClientError
from evaluation.live.seeding import EvalUser

#: canary 通过所需的最低命中率。
CANARY_THRESHOLD = 0.95


class ReadinessError(RuntimeError):
    """就绪判定失败，对应 runner 退出码 4。"""


@dataclass
class ReadinessReport:
    """就绪判定结果，写进报告。"""

    outbox_pending: int = -1
    outbox_failed: int = -1
    reconcile: dict[str, Any] = field(default_factory=dict)
    canary_sampled: int = 0
    canary_hits: int = 0
    canary_recall: float = 0.0
    canary_zero_results: int = 0
    canary_misses: list[str] = field(default_factory=list)
    verdict: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "outbox_pending": self.outbox_pending,
            "outbox_failed": self.outbox_failed,
            "reconcile": self.reconcile,
            "canary_sampled": self.canary_sampled,
            "canary_hits": self.canary_hits,
            "canary_recall": round(self.canary_recall, 4),
            "canary_zero_results": self.canary_zero_results,
            "canary_misses": self.canary_misses[:10],
            "verdict": self.verdict,
        }


def count_outbox(client: LiveClient, user_id: str) -> tuple[int, int]:
    """返回 ``(pending, failed)`` 条数。"""
    pending = failed = 0
    for status, setter in (("pending", "pending"), ("failed", "failed")):
        try:
            body = client.request(
                "GET", "/api/memory/v2/projections",
                params={"user_id": user_id, "status": status, "limit": 500},
            )[1]
        except LiveClientError:
            continue
        items = body.get("items", []) if isinstance(body, dict) else []
        if setter == "pending":
            pending = len(items)
        else:
            failed = len(items)
    return pending, failed


def await_projection(
    client: LiveClient,
    user: EvalUser,
    *,
    timeout_s: float = 900.0,
    poll_interval_s: float = 5.0,
    expected_min: int = 0,
) -> tuple[int, int]:
    """轮询等待 outbox 排空，返回最终 ``(pending, failed)``。

    超时不抛错，交由调用方结合 canary 判断——outbox 为空并不代表向量已可见，
    反之亦然。
    """
    deadline = time.monotonic() + timeout_s
    pending, failed = count_outbox(client, user.user_id)
    while time.monotonic() < deadline:
        if pending == 0 and failed == 0:
            return pending, failed
        time.sleep(poll_interval_s)
        pending, failed = count_outbox(client, user.user_id)
    return pending, failed


def canary_check(
    client: LiveClient,
    memories: Iterable[dict[str, Any]],
    user: EvalUser,
    *,
    sample_size: int = 20,
    candidate_k: int = 20,
) -> tuple[int, list[str], int]:
    """抽样用记忆名称检索，返回 ``(命中数, 未命中记忆名, 零结果次数)``。

    两个刻意的设计：

    1. **无 scope 查询**：canary 只验证"向量是否已建立并可见"，不掺入 scope
       门的因素，否则无法与后续的分级检索结果区分开。
    2. **候选窗口取 20 而非 5**：语料刻意包含大量同主题近似名称（每个任务词
       有 10 条记忆），用 top-5 会把"排序把兄弟记忆排在前面"误判成"索引没建"。
       canary 要回答的是"这条向量在不在索引里"，不是"排序好不好"。

    ``zero_result_count`` 才是真正的索引故障信号：服务重启导致
    ``_metadata_store`` 丢失时，所有查询都会返回 0 条。
    """
    ordered = sorted(memories, key=lambda memory: str(memory.get("id", "")))
    if not ordered:
        return 0, [], 0
    step = max(1, len(ordered) // max(1, sample_size))
    sample = ordered[::step][:sample_size]

    hits = 0
    misses: list[str] = []
    zero_results = 0
    for memory in sample:
        name = str(memory.get("name", ""))
        expected_id = user.memory_id(str(memory.get("id", "")))
        try:
            body = client.search(user_id=user.user_id, query=name, top_k=candidate_k)
        except LiveClientError:
            misses.append(name)
            continue
        results = body.get("results", [])
        if not results:
            zero_results += 1
            misses.append(name)
            continue
        returned = {str(item.get("memory_id")) for item in results}
        if expected_id in returned:
            hits += 1
        else:
            misses.append(name)
    return hits, misses, zero_results


def assess_readiness(
    client: LiveClient,
    user: EvalUser,
    memories: Iterable[dict[str, Any]],
    *,
    projection_timeout_s: float = 900.0,
    canary_sample: int = 20,
) -> ReadinessReport:
    """执行三段就绪判定，返回报告。

    抛出:
        :class:`ReadinessError` —— canary 未达标（索引故障），此时后续的分级
        检索分数没有意义，必须中止而不是记录一个低分。
    """
    report = ReadinessReport()
    report.outbox_pending, report.outbox_failed = await_projection(
        client, user, timeout_s=projection_timeout_s
    )
    try:
        report.reconcile = client.reconcile()
    except LiveClientError as exc:
        report.reconcile = {"error": str(exc)[:200]}

    hits, misses, zero_results = canary_check(
        client, memories, user, sample_size=canary_sample
    )
    report.canary_sampled = hits + len(misses)
    report.canary_hits = hits
    report.canary_zero_results = zero_results
    report.canary_recall = hits / report.canary_sampled if report.canary_sampled else 0.0
    report.canary_misses = misses

    if report.canary_sampled == 0:
        report.verdict = "no_sample"
        raise ReadinessError("canary 无样本，无法判断索引是否就绪")
    # 零结果是索引故障的确定信号（典型成因：服务重启后 Milvus 的内存标量
    # 映射为空，导致 user_id/status 过滤把所有候选滤掉）。
    if zero_results > 0:
        report.verdict = "index_unavailable"
        raise ReadinessError(
            f"canary 有 {zero_results}/{report.canary_sampled} 次查询返回 0 条结果："
            "语料向量不可见，这属于索引故障而非排序质量问题。"
            "常见原因是服务在播种后重启，Milvus 的内存标量映射未重建。"
        )
    if report.canary_recall < CANARY_THRESHOLD:
        report.verdict = "canary_failed"
        raise ReadinessError(
            f"canary 召回 {report.canary_recall:.2%} < {CANARY_THRESHOLD:.0%}："
            f"部分语料未正确索引。未命中示例：{misses[:5]}"
        )
    report.verdict = "ready"
    return report
