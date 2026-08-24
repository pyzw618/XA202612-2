"""Single-command, four-layer reproducible vNext benchmark runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from evaluation.metrics.formation_eval import run_formation_eval
from evaluation.metrics.full_chain_benchmark import run_full_chain_benchmark
from evaluation.metrics.vnext_retrieval_eval import run_vnext_retrieval_eval

RUNNER_VERSION = "vnext-benchmark/v1"
DEFAULT_SEED = 42
ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_infrastructure() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests/test_vnext_reliability.py", "-q"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return {
        "suite": "S4 reliability fault injection",
        "command": " ".join(command),
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "matrix": [
            "vector_timeout", "duplicate_delivery", "worker_crash", "pre_commit_crash",
            "post_commit_crash", "stale_cache", "index_corruption", "duplicate_event",
        ],
    }


def run_vnext_eval(
    *,
    output_path: str | Path = "evaluation/results/vnext_benchmark.json",
    seed: int = DEFAULT_SEED,
    e2e_memory_count: int = 50,
    e2e_query_count: int = 10,
    e2e_iterations: int = 2,
) -> dict[str, Any]:
    """Evaluate Formation, Retrieval, Infrastructure and E2E using fixed inputs."""
    formation = ROOT / "evaluation/datasets/vnext_formation_eval.json"
    pairs = ROOT / "evaluation/datasets/vnext_formation_p1_pairs.json"
    retrieval = ROOT / "evaluation/datasets/vnext_retrieval_eval.json"
    formation_report = run_formation_eval(formation, pairs).model_dump()
    retrieval_report = run_vnext_retrieval_eval(retrieval).model_dump()
    infrastructure_report = _run_infrastructure()
    e2e_report = run_full_chain_benchmark(
        engine_provider="milvus_mock",
        engine_kwargs={"app_id": "vnext-benchmark"},
        embedding_provider="mock",
        memory_count=e2e_memory_count,
        query_count=e2e_query_count,
        iterations=e2e_iterations,
        top_k=5,
        dimension=768,
        seed=seed,
        runtime_mode="test",
        allow_fallback=False,
        progress_callback=None,
    ).to_dict()
    report = {
        "schema_version": "vnext/v1",
        "runner_version": RUNNER_VERSION,
        "reproducibility": {
            "seed": seed,
            "model_version": "mock-embedding/768",
            "prompt_version": "formation-shadow/vnext-v1",
            "weight_version": "retrieval-eval/vnext-v1",
            "annotation_version": "vnext-eval-annotations/v1",
            "dataset_sha256": {
                "formation_samples": _sha256(formation),
                "formation_pairs": _sha256(pairs),
                "retrieval": _sha256(retrieval),
            },
            "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        },
        "layers": {
            "formation": formation_report,
            "retrieval": retrieval_report,
            "infrastructure": infrastructure_report,
            "e2e": e2e_report,
        },
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all four vNext evaluation layers")
    parser.add_argument("--output", default="evaluation/results/vnext_benchmark.json")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--e2e-memory-count", type=int, default=50)
    parser.add_argument("--e2e-query-count", type=int, default=10)
    parser.add_argument("--e2e-iterations", type=int, default=2)
    args = parser.parse_args()
    report = run_vnext_eval(
        output_path=args.output,
        seed=args.seed,
        e2e_memory_count=args.e2e_memory_count,
        e2e_query_count=args.e2e_query_count,
        e2e_iterations=args.e2e_iterations,
    )
    print(json.dumps({"output": args.output, "layers": list(report["layers"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
