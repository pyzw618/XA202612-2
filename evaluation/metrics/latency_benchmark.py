"""
性能基准测试模块

测试检索延迟、写入延迟等性能指标（方案 §4.9.1）。

设计要点：
- 驱动脚本通过 search_fn / insert_fn 注入被测操作，
  benchmark 类本身不关心引擎类型（FAISS / Milvus / mock 均可复用）；
- 计时用 time.perf_counter()；
- 百分位数复用 retrieval_eval.percentile（纯 Python 线性插值，无新依赖）。
"""

import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from evaluation.metrics.retrieval_eval import percentile

DEFAULT_WARMUP = 5


@dataclass
class LatencyResult:
    """延迟测试结果"""

    operation: str = ""
    count: int = 0
    mean_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    qps: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        header = f"{'操作':<12}{'次数':>8}{'mean':>10}{'P50':>10}{'P95':>10}{'P99':>10}{'min':>10}{'max':>10}{'QPS':>10}"
        row = (
            f"{self.operation:<12}{self.count:>8}"
            f"{self.mean_ms:>10.2f}{self.p50_ms:>10.2f}{self.p95_ms:>10.2f}"
            f"{self.p99_ms:>10.2f}{self.min_ms:>10.2f}{self.max_ms:>10.2f}"
            f"{self.qps:>10.1f}"
        )
        return f"{header}\n{'-' * len(header)}\n{row}\n（单位：毫秒）"


class LatencyBenchmark:
    """
    性能基准测试器

    使用方式:
        benchmark = LatencyBenchmark(search_fn=lambda q: engine.hybrid_search(...))
        result = benchmark.benchmark_search(queries, iterations=100)
    """

    def __init__(
        self,
        search_fn: Optional[Callable[[str], None]] = None,
        insert_fn: Optional[Callable[[object], None]] = None,
        warmup: int = DEFAULT_WARMUP,
    ):
        """
        参数:
            search_fn: 被测检索操作，入参为 query 文本
            insert_fn: 被测写入操作，入参为 benchmark_insert 传入的单个元素
            warmup: 预热迭代轮数（不计时）
        """
        self.search_fn = search_fn
        self.insert_fn = insert_fn
        self.warmup = warmup

    def benchmark_search(self, queries: list[str], iterations: int = 100) -> LatencyResult:
        """
        测试检索延迟

        数据流:
            预热（不计时） → 循环 iterations 轮，逐条 query 计时 → 计算百分位/QPS

        参数:
            queries: 测试查询列表
            iterations: 整体循环轮数，总计时次数 = iterations * len(queries)

        返回:
            LatencyResult

        性能目标:
            p95 latency ≤ 500ms
        """
        if self.search_fn is None:
            raise ValueError("LatencyBenchmark 需要 search_fn")
        if not queries:
            raise ValueError("queries 不能为空")

        # warm-up：让缓存/连接/JIT 类开销先行发生，不计入统计
        for _ in range(self.warmup):
            for q in queries:
                self.search_fn(q)

        latencies_ms: list[float] = []
        total_start = time.perf_counter()
        for _ in range(iterations):
            for q in queries:
                start = time.perf_counter()
                self.search_fn(q)
                latencies_ms.append((time.perf_counter() - start) * 1000.0)
        total_seconds = time.perf_counter() - total_start

        return self._build_result("search", latencies_ms, total_seconds)

    def benchmark_insert(self, items: list, iterations: int = 1) -> LatencyResult:
        """
        测试写入延迟

        参数:
            items: 待写入元素列表（逐个传给 insert_fn，元素类型由 insert_fn 决定）
            iterations: 重复次数（写入有副作用，默认 1；
                重复写入同一批数据是否安全取决于注入的 insert_fn）

        返回:
            LatencyResult
        """
        if self.insert_fn is None:
            raise ValueError("LatencyBenchmark 需要 insert_fn")
        if not items:
            raise ValueError("items 不能为空")

        latencies_ms: list[float] = []
        total_start = time.perf_counter()
        for _ in range(iterations):
            for item in items:
                start = time.perf_counter()
                self.insert_fn(item)
                latencies_ms.append((time.perf_counter() - start) * 1000.0)
        total_seconds = time.perf_counter() - total_start

        return self._build_result("insert", latencies_ms, total_seconds)

    @staticmethod
    def _build_result(operation: str, latencies_ms: list[float], total_seconds: float) -> LatencyResult:
        count = len(latencies_ms)
        return LatencyResult(
            operation=operation,
            count=count,
            mean_ms=sum(latencies_ms) / count,
            p50_ms=percentile(latencies_ms, 50),
            p95_ms=percentile(latencies_ms, 95),
            p99_ms=percentile(latencies_ms, 99),
            min_ms=min(latencies_ms),
            max_ms=max(latencies_ms),
            qps=count / total_seconds if total_seconds > 0 else 0.0,
        )
