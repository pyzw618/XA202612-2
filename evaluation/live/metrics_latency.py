"""知识检索响应时间（真机 HTTP 路径）。

**口径必须先说清楚，否则数字没有意义**

- ``client_e2e_ms``：从发出请求到收到响应，**包含**网络、JSON 序列化与客户端
  开销。这是桌面端用户实际感受到的耗时，赛题 ≤500ms 的结论以此为准。
- ``server_latency_ms``：响应体里的 ``latency_ms``，是服务端自计的检索耗时，
  作为支撑数字并列报告。

两者都必须报，不能只挑好看的那个。

**阶段划分**

- ``cold``：每条查询文本只出现一次，同时绕过查询向量缓存与结果缓存。这是
  唯一诚实的"冷"数字。
- ``vector_hot``：复用已出现过的查询（命中缓存），**单独报告，绝不并入 headline**。
  v1 的 ``latency_report.json`` 把三个阶段混在一起引用，属于口径错误。
- ``cold_start_first_request_ms``：服务冷启动后的第一个请求单独记录。实测约
  700ms+，明显高于稳态；把它混进 p95 会污染样本，隐藏它则是掩盖事实，所以
  单独列出。

embedding 与网络**计入**测量，报告需显式声明这一点。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Iterable

from evaluation.live.client import LiveClient
from evaluation.live.seeding import EvalUser
from evaluation.live.stats import latency_summary


@dataclass
class LatencySample:
    query_id: str
    client_e2e_ms: float = 0.0
    server_latency_ms: float = 0.0
    result_count: int = 0
    status: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error


def _measure_one(
    client: LiveClient,
    query: dict[str, Any],
    user: EvalUser,
    *,
    top_k: int,
    scoped: bool,
) -> LatencySample:
    mapped = user.map_query(query)
    sample = LatencySample(query_id=str(mapped.get("query_id", "")))
    try:
        body, elapsed_ms = client.search_capture_latency(
            user_id=user.user_id,
            query=str(mapped.get("query_text", "")),
            top_k=top_k,
            context=mapped.get("context") if scoped else None,
            project_id=str(mapped.get("project_id", "")) if scoped else "",
            memory_types=["knowledge"],
        )
    except Exception as exc:  # noqa: BLE001 - 逐条记录失败，不中断整批
        sample.error = f"{type(exc).__name__}: {exc}"[:200]
        return sample
    sample.status = 200
    sample.client_e2e_ms = elapsed_ms
    try:
        sample.server_latency_ms = float(body.get("latency_ms") or 0.0)
    except (TypeError, ValueError):
        sample.server_latency_ms = 0.0
    sample.result_count = int(body.get("total_count") or 0)
    return sample


def run_batch(
    client: LiveClient,
    queries: Iterable[dict[str, Any]],
    user: EvalUser,
    *,
    concurrency: int = 1,
    top_k: int = 5,
    scoped: bool = True,
) -> list[LatencySample]:
    """按指定并发执行一批查询。"""
    items = list(queries)
    if not items:
        return []
    if concurrency <= 1:
        return [_measure_one(client, q, user, top_k=top_k, scoped=scoped) for q in items]

    samples: list[LatencySample] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_measure_one, client, q, user, top_k=top_k, scoped=scoped)
            for q in items
        ]
        for future in as_completed(futures):
            samples.append(future.result())
    return samples


def summarize_phase(samples: list[LatencySample], *, wall_clock_s: float) -> dict[str, Any]:
    ok = [s for s in samples if s.ok]
    errors = [s for s in samples if not s.ok]
    summary = latency_summary([s.client_e2e_ms for s in ok])
    summary["server"] = latency_summary([s.server_latency_ms for s in ok])
    summary["requested"] = len(samples)
    summary["errors"] = len(errors)
    summary["error_rate"] = round(len(errors) / len(samples), 4) if samples else 0.0
    summary["wall_clock_s"] = round(wall_clock_s, 2)
    summary["qps"] = round(len(ok) / wall_clock_s, 2) if wall_clock_s > 0 else 0.0
    summary["error_samples"] = [s.error for s in errors[:5]]
    return summary


def evaluate_latency(
    client: LiveClient,
    dataset: dict[str, Any],
    user: EvalUser,
    *,
    concurrency_levels: tuple[int, ...] = (1, 4, 8, 16),
    warmup_count: int = 100,
    max_requests: int | None = None,
    top_k: int = 5,
    scoped: bool = True,
) -> dict[str, Any]:
    """执行冷/热分相与多并发档位的延迟评测。"""
    formal: list[dict[str, Any]] = list(dataset.get("formal_queries", []))
    warmup: list[dict[str, Any]] = list(dataset.get("warmup_queries", []))[:warmup_count]

    # 预热：不计入任何统计。
    if warmup:
        run_batch(client, warmup, user, concurrency=1, top_k=top_k, scoped=scoped)

    report: dict[str, Any] = {
        "scoped": scoped,
        "top_k": top_k,
        "unique_queries": len({q.get("query_text", "") for q in formal}),
        "concurrency_levels": list(concurrency_levels),
        "includes_embedding_and_network": True,
        "headline_metric": "client_e2e_ms",
        "phases": {},
        "notes": (
            "cold 阶段每条查询文本只使用一次以绕过向量与结果缓存；"
            "vector_hot 复用已出现的查询，单独报告；"
            "cold_start_first_request_ms 为冷启动后首个请求，单独列出不并入 p95。"
        ),
    }

    # 为各并发档位切出不重叠的查询，保证每个请求都是冷查询。
    per_level = len(formal) // max(1, len(concurrency_levels))
    if max_requests:
        per_level = min(per_level, max_requests)
    cursor = 0
    first_request_ms: float | None = None

    for level in concurrency_levels:
        slice_ = formal[cursor : cursor + per_level]
        cursor += per_level
        if not slice_:
            continue
        started = time.perf_counter()
        samples = run_batch(client, slice_, user, concurrency=level, top_k=top_k, scoped=scoped)
        wall = time.perf_counter() - started
        if level == 1:
            ok = [s for s in samples if s.ok]
            if ok:
                first_request_ms = ok[0].client_e2e_ms
        report["phases"][f"cold_c{level}"] = summarize_phase(samples, wall_clock_s=wall)

    # 热态：复用 cold 已经用过的查询，应命中缓存。
    hot_slice = formal[: min(50, len(formal))]
    if hot_slice:
        started = time.perf_counter()
        hot = run_batch(client, hot_slice, user, concurrency=1, top_k=top_k, scoped=scoped)
        report["phases"]["vector_hot_c1"] = summarize_phase(
            hot, wall_clock_s=time.perf_counter() - started
        )

    report["cold_start_first_request_ms"] = (
        round(first_request_ms, 2) if first_request_ms is not None else None
    )
    return report
