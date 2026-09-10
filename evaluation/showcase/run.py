"""Run the four MemoryHub showcase metrics in one command.

This runner is deliberately honest about its evidence level.  Its bundled
retrieval fixture uses deterministic channel executors, so it validates the
vNext retrieval pipeline (routing, fusion, scope and context), not a deployed
Milvus service.  A report generated this way is therefore labelled
``DEMONSTRATION_ONLY`` and must not be used as a production performance claim.

For a real Milvus acceptance run, first run
``scripts/run_milvus_real_smoke_test.py`` and the HTTP retrieval evaluator on
the target Kylin host.  Keeping those results separate prevents mock scores
from being presented as production measurements.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.metrics.conflict_eval import ConflictEvaluator
from evaluation.metrics.preference_eval import PreferenceEvaluator
from evaluation.metrics.vnext_retrieval_eval import (
    VNextRetrievalEvaluator,
    build_vnext_retrieval_service_for_eval,
)
from memoryhub.config import load_config

PREFERENCE_TARGET = 0.85
RECALL_TARGET = 0.85
LATENCY_TARGET_MS = 500.0
CONFLICT_TARGET = 0.88

DEFAULT_DATASETS = {
    "preference": ROOT / "evaluation/showcase/datasets/preference_golden_v1.json",
    "conflict": ROOT / "evaluation/showcase/datasets/conflict_golden_v1.json",
    "retrieval": ROOT / "evaluation/showcase/datasets/vnext_retrieval_eval.json",
}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = percentile / 100 * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _config_fingerprint(config_path: Path) -> dict[str, Any]:
    config = load_config(str(config_path))
    return {
        "config_path": str(config_path),
        "runtime_mode": config.runtime.mode,
        "allow_fallback": config.runtime.allow_fallback,
        "embedding_provider": config.embedding.provider,
        "embedding_dimension": config.embedding.dimension,
        "vector_engine_provider": config.vector_engine.provider,
        "vector_engine_dimension": config.vector_engine.dimension,
        "vnext_mode": config.vnext.mode,
    }


def _run_pipeline_retrieval(dataset_path: Path, repeats: int) -> tuple[dict[str, Any], dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    service = build_vnext_retrieval_service_for_eval(dataset)
    evaluator = VNextRetrievalEvaluator(service, top_k=dataset.get("metadata", {}).get("top_k", 10))
    report = evaluator.evaluate(dataset_path)

    # Measure the same complete RetrievalService pipeline repeatedly.  This is
    # useful for demo regression detection, but remains mock-backed by design.
    latencies: list[float] = []
    memory_map = {item["memory_id"]: item for item in dataset["memories"]}
    for _ in range(repeats):
        for query in dataset["queries"]:
            started = time.perf_counter()
            evaluator._evaluate_query(query, memory_map)
            latencies.append((time.perf_counter() - started) * 1000)
    latency = {
        "sample_count": len(latencies),
        "repeats": repeats,
        "p50_ms": round(_percentile(latencies, 50), 3),
        "p95_ms": round(_percentile(latencies, 95), 3),
        "p99_ms": round(_percentile(latencies, 99), 3),
        "max_ms": round(max(latencies), 3) if latencies else 0.0,
    }
    return report.model_dump(), latency


def build_report(*, config_path: Path, repeats: int) -> dict[str, Any]:
    preference = PreferenceEvaluator().run(str(DEFAULT_DATASETS["preference"]))
    conflict_evaluator = ConflictEvaluator()
    conflict = conflict_evaluator.run(str(DEFAULT_DATASETS["conflict"]))
    detection = conflict_evaluator.evaluate_detection(str(DEFAULT_DATASETS["conflict"]))
    retrieval, latency = _run_pipeline_retrieval(DEFAULT_DATASETS["retrieval"], repeats)

    metrics = [
        {
            "name": "偏好提取准确率",
            "value": preference.accuracy,
            "threshold": PREFERENCE_TARGET,
            "unit": "ratio",
            "passed": preference.accuracy >= PREFERENCE_TARGET,
            "sample_count": preference.total_samples,
        },
        {
            "name": "知识检索召回率 Recall@K",
            "value": retrieval["recall_at_k"],
            "threshold": RECALL_TARGET,
            "unit": "ratio",
            "passed": retrieval["recall_at_k"] >= RECALL_TARGET,
            "sample_count": retrieval["total_queries"],
        },
        {
            "name": "知识检索响应时间 P95",
            "value": latency["p95_ms"],
            "threshold": LATENCY_TARGET_MS,
            "unit": "ms",
            "passed": latency["p95_ms"] <= LATENCY_TARGET_MS,
            "sample_count": latency["sample_count"],
        },
        {
            "name": "知识冲突处理正确率",
            "value": conflict.accuracy,
            "threshold": CONFLICT_TARGET,
            "unit": "ratio",
            "passed": conflict.accuracy >= CONFLICT_TARGET,
            "sample_count": conflict.total_samples,
        },
    ]
    return {
        "schema_version": "memoryhub/showcase-evaluation/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_level": "DEMONSTRATION_ONLY",
        "evidence_notice": (
            "检索与延迟使用内置确定性 mock 通道，仅验证评测数据、检索编排和回归；"
            "不得作为真实 Kylin Embedding + Milvus 的生产验收结论。"
        ),
        "environment": {
            **_config_fingerprint(config_path),
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "datasets": {name: str(path.relative_to(ROOT)) for name, path in DEFAULT_DATASETS.items()},
        "metrics": metrics,
        "all_thresholds_passed": all(metric["passed"] for metric in metrics),
        "details": {
            "preference": preference.model_dump(),
            "conflict": {"resolution": conflict.model_dump(), "detection": detection},
            "retrieval": retrieval,
            "latency": latency,
        },
        "production_follow_up": [
            "在目标麒麟机器执行 scripts/check_kylin_embedding_runtime.py。",
            "执行 scripts/run_milvus_real_smoke_test.py --app_id <真实 app_id>。",
            "使用真实服务的 HTTP 评测替换本报告中的 mock 检索与延迟结果。",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# MemoryHub 四项指标评测报告",
        "",
        f"> 证据等级：**{report['evidence_level']}**",
        "> " + report["evidence_notice"],
        "",
        "| 指标 | 结果 | 阈值 | 样本数 | 判定 |",
        "|---|---:|---:|---:|---|",
    ]
    for metric in report["metrics"]:
        suffix = "ms" if metric["unit"] == "ms" else "%"
        value = f"{metric['value']:.3f}" if suffix == "ms" else f"{metric['value'] * 100:.2f}%"
        threshold = f"≤ {metric['threshold']:.0f}ms" if suffix == "ms" else f"≥ {metric['threshold'] * 100:.0f}%"
        verdict = "通过" if metric["passed"] else "未通过"
        lines.append(f"| {metric['name']} | {value} | {threshold} | {metric['sample_count']} | {verdict} |")
    environment = report["environment"]
    lines.extend([
        "",
        "## 环境指纹",
        "",
        f"- 运行模式：`{environment['runtime_mode']}`；向量引擎：`{environment['vector_engine_provider']}`；Embedding：`{environment['embedding_provider']}`",
        f"- vNext 模式：`{environment['vnext_mode']}`；Embedding 维度：`{environment['embedding_dimension']}`",
        "",
        "## 生产验收前置条件",
        "",
        *[f"- {item}" for item in report["production_follow_up"]],
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the four showcase metrics in one command")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation/results/showcase")
    parser.add_argument("--repeats", type=int, default=20, help="retrieval fixture repetitions for latency")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    report = build_report(config_path=args.config.resolve(), repeats=args.repeats)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "four_metrics_report.json"
    markdown_path = output_dir / "four_metrics_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({
        "report_json": str(json_path),
        "report_markdown": str(markdown_path),
        "evidence_level": report["evidence_level"],
        "all_thresholds_passed": report["all_thresholds_passed"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
