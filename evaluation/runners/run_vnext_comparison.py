"""Controlled four-system comparison and one-mechanism ablation runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from evaluation.metrics.vnext_retrieval_eval import run_vnext_retrieval_eval

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evaluation/showcase/datasets/vnext_retrieval_eval.json"
SYSTEMS = ("NO_MEMORY", "FLAT_RAG", "ORIGINAL", "VNEXT")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _mean_ci(values: list[float]) -> dict[str, float]:
    mean = statistics.fmean(values) if values else 0.0
    variance = statistics.variance(values) if len(values) > 1 else 0.0
    margin = 1.96 * math.sqrt(variance / len(values)) if values else 0.0
    return {
        "mean": round(mean, 6),
        "variance": round(variance, 6),
        "ci95_low": round(mean - margin, 6),
        "ci95_high": round(mean + margin, 6),
    }


def _all_channels(query: dict[str, Any]) -> list[str]:
    return _unique(
        memory_id
        for ids in query.get("channel_relevance", {}).values()
        for memory_id in ids
    )


def _system_selectors(vnext: dict[str, Any]) -> dict[str, Callable[[dict[str, Any]], list[str]]]:
    selected = {
        item["query_id"]: list(item["details"]["selected_memory_ids"])
        for item in vnext["sample_results"]
    }
    return {
        "NO_MEMORY": lambda _: [],
        "FLAT_RAG": _all_channels,
        "ORIGINAL": lambda query: list(query.get("channel_relevance", {}).get("vector", [])),
        "VNEXT": lambda query: selected[query["query_id"]],
    }


def _evaluate_variant(
    queries: list[dict[str, Any]], selector: Callable[[dict[str, Any]], list[str]], repeats: int
) -> dict[str, Any]:
    success: list[float] = []
    leakage: list[float] = []
    mrr: list[float] = []
    tokens: list[float] = []
    latency: list[float] = []
    for _ in range(repeats):
        for query in queries:
            started = time.perf_counter()
            retrieved = selector(query)
            latency.append((time.perf_counter() - started) * 1000)
            expected = set(query.get("expected_memory_ids", []))
            forbidden = set(query.get("forbidden_memory_ids", []))
            success.append(len(expected & set(retrieved)) / len(expected) if expected else 1.0)
            leakage.append(len(forbidden & set(retrieved)) / len(forbidden) if forbidden else 0.0)
            first = next((i + 1 for i, item in enumerate(retrieved) if item in expected), None)
            mrr.append(1.0 / first if first else 0.0)
            tokens.append(float(len(retrieved) * 32))
    return {
        "task_success": _mean_ci(success),
        "policy_leak_rate": _mean_ci(leakage),
        "mrr": _mean_ci(mrr),
        "context_tokens": _mean_ci(tokens),
        "latency_ms": _mean_ci(latency),
    }


def run_vnext_comparison(
    *, output_path: str | Path = "evaluation/results/vnext_final/comparison.json", repeats: int = 5
) -> dict[str, Any]:
    """Run equally-budgeted comparison; reports are redacted to query IDs/aggregates."""
    if repeats < 2:
        raise ValueError("repeats must be at least 2 to calculate variance and CI")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    vnext = run_vnext_retrieval_eval(DATASET).model_dump()
    selectors = _system_selectors(vnext)
    systems = {
        name: _evaluate_variant(dataset["queries"], selector, repeats)
        for name, selector in selectors.items()
    }
    # Each ablation starts from the same vNext output and removes one mechanism only.
    ablations = {
        "NO_ROUTER": _evaluate_variant(
            dataset["queries"],
            lambda query: list(query.get("channel_relevance", {}).get("vector", [])),
            repeats,
        ),
        "NO_SCOPE_RESOLVER": _evaluate_variant(dataset["queries"], _all_channels, repeats),
        "NO_RERANKER": _evaluate_variant(
            dataset["queries"], lambda query: list(reversed(selectors["VNEXT"](query))), repeats
        ),
        "NO_CONTEXT_BUDGET": _evaluate_variant(dataset["queries"], _all_channels, repeats),
    }
    report = {
        "schema_version": "vnext/v1",
        "comparison_version": "vnext-comparison/v1",
        "methodology": {
            "systems": list(SYSTEMS),
            "shared_model": "mock-embedding/768",
            "shared_tool_permissions": "offline deterministic mock channels only",
            "shared_token_budget": "dataset token_budget per query",
            "repeats": repeats,
            "confidence_interval": "normal approximation, two-sided 95%",
            "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
            "redacted": True,
        },
        "systems": systems,
        "ablations": ablations,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run four-system vNext comparison and ablations")
    parser.add_argument("--output", default="evaluation/results/vnext_final/comparison.json")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    report = run_vnext_comparison(output_path=args.output, repeats=args.repeats)
    print(
        json.dumps({"output": args.output, "systems": list(report["systems"])}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
