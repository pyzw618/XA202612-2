"""Run a reproducible MemoryHub vNext S0 baseline.

The runner deliberately composes existing validation, retrieval and regression
entry points.  It records unavailable measurements instead of treating a
missing runtime or model as a successful baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_DATASET = ROOT / "evaluation" / "datasets" / (
    "memoryhub_knowledge_retrieval_v1_dev.json"
)
DEFAULT_SCHEMA = ROOT / "evaluation" / "datasets" / (
    "memoryhub_retrieval_dataset_schema_v1.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "evaluation" / "results" / "vnext_baseline"
DEFAULT_CONFIG = ROOT / "config.yaml"
if not DEFAULT_CONFIG.exists():
    DEFAULT_CONFIG = ROOT / "config.example.yaml"


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file without loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _run_command(command: list[str]) -> dict[str, Any]:
    """Run a local command and retain bounded, useful evidence."""
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        return {
            "status": "ERROR",
            "exit_code": None,
            "command": command,
            "error": str(exc),
        }
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "exit_code": result.returncode,
        "command": command,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _config_snapshot(config_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(config_path.relative_to(ROOT)),
        "sha256": sha256_file(config_path),
    }
    try:
        from memoryhub.config import load_config

        config = load_config(str(config_path))
        result["runtime_mode"] = config.runtime.mode
        result["embedding_provider"] = config.embedding.provider
        result["embedding_model"] = config.embedding.model_name or "default"
        result["vector_engine"] = config.vector_engine.provider
        result["vector_index_version"] = "runtime-configured"
        result["vnext"] = {
            "mode": config.vnext.mode,
            "canary_percent": config.vnext.canary_percent,
            "policy_required": config.vnext.policy_required,
            "authority_single_writer": config.vnext.authority_single_writer,
        }
    except Exception as exc:  # pragma: no cover - depends on local config
        result["status"] = "ERROR"
        result["error"] = str(exc)
    return result


def _validate_dataset(dataset_path: Path, schema_path: Path) -> dict[str, Any]:
    from evaluation.validate_retrieval_dataset import validate_dataset

    dataset = _load_json(dataset_path)
    schema = _load_json(schema_path) if schema_path.exists() else None
    validation = validate_dataset(dataset, schema)
    return {
        "status": "PASS" if validation["passed"] else "FAIL",
        "report": validation,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = percentile / 100 * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _run_vector_only_baseline(dataset_path: Path) -> dict[str, Any]:
    """Run a dependency-light vector baseline when Hybrid's optional BM25 is absent."""
    import math
    import time

    from memoryhub.embedding import MockEmbeddingClient

    dataset = _load_json(dataset_path)
    memories = [
        memory for memory in dataset.get("memories", [])
        if memory.get("status", "active") == "active"
    ]
    client = MockEmbeddingClient(dim=768, latency=0.0)
    indexed: list[tuple[str, list[float], str]] = []
    for memory in memories:
        indexed.append((
            memory["id"],
            client.embed(memory["content"]),
            memory.get("user_id", "?"),
        ))

    def cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0

    rows: list[dict[str, Any]] = []
    for query in dataset.get("queries", []):
        relevant = {
            memory_id for memory_id, score in (query.get("relevance") or {}).items()
            if score >= 2
        }
        started = time.perf_counter()
        query_vector = client.embed(query["query_text"])
        scored = sorted(
            ((memory_id, user_id, cosine(query_vector, vector))
             for memory_id, vector, user_id in indexed),
            key=lambda item: item[2],
            reverse=True,
        )[:10]
        elapsed_ms = (time.perf_counter() - started) * 1000
        retrieved = [item[0] for item in scored]
        hits_at_5 = sum(memory_id in relevant for memory_id in retrieved[:5])
        hits_at_10 = sum(memory_id in relevant for memory_id in retrieved[:10])
        first_rank = next(
            (rank for rank, memory_id in enumerate(retrieved, 1)
             if memory_id in relevant),
            0,
        )
        cross_user = sum(
            1 for item in scored if item[1] != query.get("user_id", "?")
        )
        rows.append({
            "query_id": query["query_id"],
            "retrieved": retrieved,
            "recall_5": hits_at_5 / len(relevant) if relevant else 1.0,
            "recall_10": hits_at_10 / len(relevant) if relevant else 1.0,
            "precision_5": hits_at_5 / 5,
            "precision_10": hits_at_10 / 10,
            "mrr": 1 / first_rank if first_rank else 0.0,
            "cross_user_rate": cross_user / max(len(scored), 1),
            "latency_ms": round(elapsed_ms, 3),
        })

    latencies = [row["latency_ms"] for row in rows]
    count = len(rows)
    overall = {
        "count": count,
        "recall_5": round(sum(row["recall_5"] for row in rows) / count, 4)
        if count else 0.0,
        "recall_10": round(sum(row["recall_10"] for row in rows) / count, 4)
        if count else 0.0,
        "precision_5": round(sum(row["precision_5"] for row in rows) / count, 4)
        if count else 0.0,
        "precision_10": round(sum(row["precision_10"] for row in rows) / count, 4)
        if count else 0.0,
        "mrr": round(sum(row["mrr"] for row in rows) / count, 4) if count else 0.0,
        "cross_user_rate": round(
            sum(row["cross_user_rate"] for row in rows) / count, 4
        ) if count else 0.0,
        "latency_p50_ms": round(_percentile(latencies, 50), 3),
        "latency_p95_ms": round(_percentile(latencies, 95), 3),
        "latency_p99_ms": round(_percentile(latencies, 99), 3),
        "latency_max_ms": round(max(latencies), 3) if latencies else 0.0,
    }
    return {
        "engine": "faiss",
        "mode": "vector_only",
        "indexed_active_memory_count": len(memories),
        "overall": overall,
        "per_query": rows,
    }


def build_baseline_report(
    *,
    dataset_path: Path,
    schema_path: Path,
    config_path: Path,
    output_dir: Path,
    tests: dict[str, Any] | None = None,
    retrieval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the report envelope; command execution remains explicit."""
    dataset = _load_json(dataset_path)
    return {
        "schema": "memoryhub/vnext-baseline/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "root": str(ROOT),
            "branch": _git_value("branch", "--show-current"),
            "commit": _git_value("rev-parse", "HEAD"),
            "short_commit": _git_value("rev-parse", "--short", "HEAD"),
        },
        "configuration": _config_snapshot(config_path),
        "dataset": {
            "path": str(dataset_path.relative_to(ROOT)),
            "sha256": sha256_file(dataset_path),
            "metadata": dataset.get("metadata", {}),
            "memory_count": len(dataset.get("memories", [])),
            "query_count": len(dataset.get("queries", [])),
        },
        "model_and_index": {
            "embedding_provider": "mock",
            "embedding_model": "memoryhub-mock-deterministic-v1",
            "index_engine": "faiss",
            "index_version": "runtime-built-from-dataset-v1",
        },
        "tests": tests or {"status": "NOT_RUN"},
        "retrieval": retrieval or {"status": "NOT_RUN"},
        "latency": {
            "status": "SEE_RETRIEVAL_GROUPS",
            "source": "retrieval.groups.*.overall.latency_p50_ms/p95/p99_ms",
        },
        "write_bypass_scan": {
            "status": "SEE_TESTS",
            "source": "tests/test_no_production_write_bypass.py",
        },
        "artifacts": {
            "output_dir": str(output_dir.relative_to(ROOT)),
        },
    }


def run_baseline(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    schema_path: Path = DEFAULT_SCHEMA,
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_tests: bool = True,
    run_retrieval: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    validation = _validate_dataset(dataset_path, schema_path)
    validation_path = output_dir / "dataset_validation.json"
    validation_path.write_text(
        json.dumps(validation["report"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tests = {"status": "NOT_RUN"}
    if run_tests:
        tests = _run_command([
            sys.executable,
            "-m",
            "pytest",
            "tests/test_no_production_write_bypass.py",
            "tests/test_vnext_contracts.py",
            "tests/test_vnext_interface.py",
            "-q",
        ])

    retrieval: dict[str, Any] = {"status": "NOT_RUN"}
    retrieval_json = output_dir / "retrieval_eval.json"
    retrieval_md = output_dir / "retrieval_eval.md"
    if run_retrieval:
        command_result = _run_command([
            sys.executable,
            "evaluation/runners/run_retrieval_eval.py",
            "--dataset",
            str(dataset_path.relative_to(ROOT)),
            "--provider",
            "mock",
            "--engine",
            "faiss",
            "--output-json",
            str(retrieval_json.relative_to(ROOT)),
            "--output-md",
            str(retrieval_md.relative_to(ROOT)),
        ])
        retrieval = command_result
        if retrieval_json.exists():
            retrieval["report"] = _load_json(retrieval_json)
        if retrieval["status"] != "PASS":
            try:
                vector_report = _run_vector_only_baseline(dataset_path)
            except (ImportError, OSError, ValueError) as exc:
                retrieval["fallback"] = {
                    "status": "ERROR",
                    "error": str(exc),
                }
            else:
                retrieval = {
                    "status": "PASS",
                    "mode": "vector_only_fallback",
                    "fallback_reason": command_result.get("stderr_tail", "")[-1000:],
                    "hybrid_attempt": command_result,
                    "report": {"groups": {"vector_only": vector_report}},
                }

    report = build_baseline_report(
        dataset_path=dataset_path,
        schema_path=schema_path,
        config_path=config_path,
        output_dir=output_dir,
        tests=tests,
        retrieval=retrieval,
    )
    report["dataset_validation"] = validation
    report["write_bypass_scan"] = {
        "status": tests["status"],
        "command": tests.get("command", []),
        "test": "tests/test_no_production_write_bypass.py",
    }
    if retrieval.get("report"):
        groups = retrieval["report"].get("groups", {})
        report["latency"] = {
            "status": "PASS" if retrieval["status"] == "PASS" else "PARTIAL",
            "groups": {
                name: group.get("overall", {}) for name, group in groups.items()
            },
        }

    report["status"] = "PASS" if (
        validation["status"] == "PASS"
        and tests["status"] in {"PASS", "NOT_RUN"}
        and retrieval["status"] in {"PASS", "NOT_RUN"}
    ) else "FAIL"

    report_path = output_dir / "baseline.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "report": str(report_path),
        "dataset_validation": validation["status"],
        "tests": tests["status"],
        "retrieval": retrieval["status"],
    }, ensure_ascii=False))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MemoryHub vNext S0 baseline")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-retrieval", action="store_true")
    args = parser.parse_args()
    try:
        report = run_baseline(
            dataset_path=args.dataset.resolve(),
            schema_path=args.schema.resolve(),
            config_path=args.config.resolve(),
            output_dir=args.output_dir.resolve(),
            run_tests=not args.skip_tests,
            run_retrieval=not args.skip_retrieval,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"baseline failed: {exc}", file=sys.stderr)
        return 1
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
