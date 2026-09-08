#!/usr/bin/env python3
"""Unified MemoryHub V2 benchmark entry point.

Quality suites invoke the existing production extractors/retriever/conflict resolver.
The acceptance latency metric is only emitted from real HTTP calls; no mock latency can
produce a PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.metrics.bootstrap import bootstrap_ci  # noqa: E402
from evaluation.metrics.conflict_eval import ConflictEvaluator  # noqa: E402
from evaluation.metrics.preference_eval import PreferenceEvaluator  # noqa: E402
from evaluation.reporting import RunRegistry, write_report  # noqa: E402

DATASETS = ROOT / "evaluation" / "datasets"
RESULTS = ROOT / "evaluation" / "results"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    targets = sorted(path.rglob("*")) if path.is_dir() else [path]
    for target in targets:
        if target.is_file():
            digest.update(
                target.relative_to(path).as_posix().encode()
                if path.is_dir()
                else target.name.encode()
            )
            digest.update(target.read_bytes())
    return digest.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _metric(
    name: str,
    value: float | None,
    threshold: float,
    higher_is_better: bool,
    values: list[float] | None = None,
    unavailable: str = "",
) -> dict[str, Any]:
    passed = value is not None and (value >= threshold if higher_is_better else value <= threshold)
    result: dict[str, Any] = {
        "name": name,
        "value": value,
        "threshold": threshold,
        "status": "PASS" if passed else "FAIL",
    }
    if value is None:
        result["reason"] = unavailable
        result["display"] = "UNAVAILABLE"
    elif "P95" in name:
        result["display"] = f"{value:.3f} ms"
    else:
        result["display"] = f"{value:.2%}"
    if values:
        result["ci95"] = list(bootstrap_ci(values))
    return result


def _preference() -> tuple[dict, dict, list]:
    report = PreferenceEvaluator().run(str(DATASETS / "preference_golden_v1.json"))
    values = [1.0 if row.correct else 0.0 for row in report.details]
    failures = [
        {
            "case_id": r.sample_id,
            "benchmark": "preference",
            "gold": r.expected,
            "prediction": r.predicted,
            "failure_tag": "exact_mismatch",
        }
        for r in report.details
        if not r.correct
    ]
    return _metric("Preference Exact Accuracy", report.accuracy, 0.85, True, values), {}, failures


def _conflict() -> tuple[dict, dict, list]:
    report = ConflictEvaluator().run(str(DATASETS / "conflict_golden_v1.json"))
    values = [1.0 if row.correct else 0.0 for row in report.details]
    failures = [
        {
            "case_id": r.sample_id,
            "benchmark": "conflict",
            "gold": r.expected,
            "prediction": r.predicted,
            "failure_tag": "final_state_mismatch",
        }
        for r in report.details
        if not r.correct
    ]
    return _metric("Conflict State Accuracy", report.accuracy, 0.88, True, values), {}, failures


def _retrieval(backend: str) -> tuple[dict, dict, list]:
    dataset_path = DATASETS / "memoryhub_golden_retrieval_v1.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    queries = dataset["queries"]
    if backend == "no_memory":
        answerable = [
            q for q in queries if any(v >= 2 for v in (q.get("relevance") or {}).values())
        ]
        values = [0.0] * len(answerable)
        failures = [
            {
                "case_id": q["query_id"],
                "benchmark": "retrieval",
                "failure_tag": "no_relevant_in_final",
            }
            for q in answerable
        ]
        return _metric("Retrieval Recall@5", 0.0, 0.85, True, values), {}, failures

    # This is the repository's production HybridRetriever and its real sparse/dense paths.
    from evaluation.run_retrieval_eval import build_retriever, evaluate_group
    from memoryhub.config import RetrievalConfig
    from memoryhub.embedding import MockEmbeddingClient

    embedder = MockEmbeddingClient(dimension=768)
    weights = {
        "bm25": (0.0, 1.0, 0.0),
        "dense": (1.0, 0.0, 0.0),
        "original": (0.6, 0.3, 0.1),
        "vnext": (0.6, 0.3, 0.1),
    }
    vector, keyword, metadata = weights[backend]
    config = RetrievalConfig(
        vector_weight=vector,
        keyword_weight=keyword,
        metadata_weight=metadata,
    )
    retriever = build_retriever(dataset["memories"], embedder.embed, 768, config)
    by_kt = {m["id"]: m.get("knowledge_type", "") for m in dataset["memories"]}
    by_user = {m["id"]: m.get("user_id", "") for m in dataset["memories"]}
    evaluated = evaluate_group(retriever, queries, by_kt, by_user, top_k=5)
    answerable_rows = [
        r
        for r in evaluated["per_query"]
        if any(
            v >= 2
            for v in next(q for q in queries if q["query_id"] == r["query_id"])[
                "relevance"
            ].values()
        )
    ]
    values = [r["recall_5"] for r in answerable_rows]
    value = sum(values) / len(values) if values else 0.0
    failures = [
        {
            "case_id": r["query_id"],
            "benchmark": "retrieval",
            "prediction": r["retrieved"],
            "failure_tag": "no_relevant_in_final",
        }
        for r in answerable_rows
        if r["recall_5"] < 1.0
    ]
    breakdown = {"difficulty": evaluated["by_difficulty"], "language": evaluated["by_language"]}
    return _metric("Retrieval Recall@5", value, 0.85, True, values), breakdown, failures


def _latency(base_url: str | None, iterations: int) -> tuple[dict, dict, list]:
    if not base_url:
        return (
            _metric(
                "Production HTTP Retrieval P95",
                None,
                500.0,
                False,
                unavailable="--base-url is required; mock latency is not acceptance evidence",
            ),
            {},
            [],
        )
    import httpx

    endpoint = base_url.rstrip("/") + "/api/memory/search"
    timings = []
    with httpx.Client(timeout=30.0) as client:
        for _ in range(iterations):
            started = time.perf_counter()
            response = client.post(
                endpoint, json={"user_id": "benchmark_user", "query": "项目周报流程", "top_k": 5}
            )
            response.raise_for_status()
            timings.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(timings)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    return _metric("Production HTTP Retrieval P95", p95, 500.0, False), {}, []


def run(args: argparse.Namespace) -> dict[str, Any]:
    selected = (
        [args.suite]
        if args.suite not in {"acceptance", "dev"}
        else ["preference", "retrieval", "latency", "conflict"]
    )
    metrics, breakdown, failures = {}, {}, []
    handlers = {
        "preference": _preference,
        "retrieval": lambda: _retrieval(args.backend),
        "latency": lambda: _latency(args.base_url, args.latency_iterations),
        "conflict": _conflict,
    }
    for name in selected:
        metric, slices, failed = handlers[name]()
        metrics[name] = metric
        if slices:
            breakdown[name] = slices
        failures.extend(failed)
    now = datetime.now(timezone.utc)
    config_path = Path(os.environ.get("MEMORYHUB_CONFIG_PATH", ROOT / "config.yaml"))
    run_id = now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    result = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "suite": args.suite,
        "benchmark_version": "2.0",
        "backend": args.backend,
        "git_sha": _git_sha(),
        "dataset_sha256": _sha256(DATASETS),
        "config_sha256": _sha256(config_path) if config_path.is_file() else "missing",
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "embedding": "production-http" if args.base_url else "not-used-for-latency",
        },
        "metrics": metrics,
        "ability_breakdown": breakdown,
        "failures": failures,
        "status": "PASS"
        if metrics and all(m["status"] == "PASS" for m in metrics.values())
        else "FAIL",
    }
    RunRegistry(args.registry).record(result)
    json_path, md_path = write_report(result, args.report_dir)
    result["artifacts"] = {
        "json": str(json_path),
        "markdown": str(md_path),
        "registry": str(args.registry),
    }
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run the unified MemoryHub V2 benchmark")
    value.add_argument(
        "--suite",
        choices=["acceptance", "dev", "preference", "retrieval", "latency", "conflict"],
        default="dev",
    )
    value.add_argument(
        "--backend",
        choices=["no_memory", "bm25", "dense", "original", "vnext"],
        default="no_memory",
    )
    value.add_argument(
        "--base-url", help="running production MemoryHub URL; required for latency acceptance"
    )
    value.add_argument("--latency-iterations", type=int, default=30)
    value.add_argument("--registry", type=Path, default=RESULTS / "runs.sqlite")
    value.add_argument("--report-dir", type=Path, default=RESULTS / "reports")
    value.add_argument("--json", action="store_true", help="print complete machine-readable result")
    return value


def main() -> int:
    args = parser().parse_args()
    result = run(args)
    print(
        json.dumps(result, ensure_ascii=False, indent=2)
        if args.json
        else (
            f"{result['status']} run_id={result['run_id']} report={result['artifacts']['markdown']}"
        )
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
