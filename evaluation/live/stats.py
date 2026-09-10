"""live 评测包自用的统计小工具。

刻意不 import ``evaluation/runners/run_retrieval_eval.py``：那个模块在导入时
会拉起 ``memoryhub.retrieval.*`` 的进程内检索栈，而 live 包的整个意义就是
"不依赖进程内实现"。这几个函数很短，重复定义比引入耦合更划算。
"""

from __future__ import annotations

import math


def percentile(data: list[float], p: float) -> float:
    """线性插值分位数；空列表返回 0.0。"""
    if not data:
        return 0.0
    ordered = sorted(data)
    index = (p / 100.0) * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def latency_summary(samples: list[float]) -> dict[str, float]:
    """延迟分布摘要（毫秒）。"""
    if not samples:
        return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0,
                "max_ms": 0.0, "mean_ms": 0.0}
    return {
        "count": len(samples),
        "p50_ms": round(percentile(samples, 50), 2),
        "p95_ms": round(percentile(samples, 95), 2),
        "p99_ms": round(percentile(samples, 99), 2),
        "max_ms": round(max(samples), 2),
        "mean_ms": round(mean(samples), 2),
    }


def gain(score: int) -> int:
    """0-3 级相关性到 NDCG 增益的线性映射。"""
    return score


def dcg(values: list[int], k: int) -> float:
    return sum(gain(value) / math.log2(index + 2) for index, value in enumerate(values[:k]))
