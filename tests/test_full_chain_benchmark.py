# -*- coding: utf-8 -*-
"""完整生产检索链路基准测试回归测试。

覆盖:
  - 基准脚本可运行并返回包含全部验收指标的结果
  - 结果可序列化为 JSON（便于 CI/评测系统解析）
  - 缓存命中率、错误率、待同步积压数可被正确采集
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluation.metrics.full_chain_benchmark import (
    FullChainBenchmarkResult,
    run_full_chain_benchmark,
)


class TestFullChainBenchmark:
    def test_run_full_chain_benchmark_returns_all_metrics(self, tmp_path) -> None:
        """完整链路基准应返回后续阶段所需的全部性能指标。"""
        result = run_full_chain_benchmark(
            engine_provider="milvus_mock",
            embedding_provider="mock",
            memory_count=50,
            query_count=10,
            iterations=2,
            top_k=5,
            dimension=768,
            seed=42,
            runtime_mode="test",
            allow_fallback=False,
            progress_callback=None,
        )

        assert isinstance(result, FullChainBenchmarkResult)
        assert result.total_queries == 20
        assert result.total_indexed == 50
        assert result.pending_backlog_count == 0
        assert result.latency.count == 20
        assert result.latency.p95_ms >= 0
        assert result.latency.p99_ms >= result.latency.p95_ms
        assert 0.0 <= result.recall_at_5 <= 1.0
        assert 0.0 <= result.ndcg_at_10 <= 1.0
        assert 0.0 <= result.result_cache_hit_rate <= 1.0
        assert 0.0 <= result.vector_cache_hit_rate <= 1.0
        assert 0.0 <= result.embedding_error_rate <= 1.0
        assert 0.0 <= result.milvus_error_rate <= 1.0
        assert result.budget_p95_ms == 350.0
        assert result.budget_p99_ms == 500.0

    def test_benchmark_result_is_json_serializable(self, tmp_path) -> None:
        """基准结果应可直接序列化为 JSON 文件，便于交接与自动化解析。"""
        result = run_full_chain_benchmark(
            engine_provider="milvus_mock",
            embedding_provider="mock",
            memory_count=30,
            query_count=5,
            iterations=1,
            top_k=5,
            dimension=768,
            seed=42,
            runtime_mode="test",
            allow_fallback=False,
            progress_callback=None,
        )

        output_path = tmp_path / "bench_result.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

        with open(output_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        required_keys = {
            "total_queries",
            "latency",
            "recall_at_5",
            "ndcg_at_10",
            "result_cache_hit_rate",
            "vector_cache_hit_rate",
            "embedding_error_rate",
            "milvus_error_rate",
            "pending_backlog_count",
            "total_indexed",
            "budget_p95_ms",
            "budget_p99_ms",
            "p95_within_budget",
            "p99_within_budget",
        }
        assert required_keys.issubset(set(loaded.keys()))
        assert loaded["latency"]["operation"] == "search"
        assert loaded["latency"]["count"] > 0

    def test_benchmark_reports_cache_hits(self) -> None:
        """多轮迭代应能统计到结果缓存命中与查询向量缓存命中。"""
        result = run_full_chain_benchmark(
            engine_provider="milvus_mock",
            embedding_provider="mock",
            memory_count=50,
            query_count=10,
            iterations=3,
            top_k=5,
            dimension=768,
            seed=42,
            runtime_mode="test",
            allow_fallback=False,
            progress_callback=None,
        )

        # 3 轮迭代中，后两轮应命中结果缓存；查询向量缓存在非首轮也会命中
        assert result.result_cache_hit_rate > 0.0
        assert result.vector_cache_hit_rate > 0.0

