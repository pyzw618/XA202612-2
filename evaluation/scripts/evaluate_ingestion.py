from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.ingestion import IngestionPipeline


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def evaluate(path: Path, repeat: int = 1) -> dict:
    rows = load_rows(path)
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    pipeline = IngestionPipeline(reference_time="2026-07-20T00:00:00Z")
    field_total = field_correct = 0
    status_total = status_correct = 0
    sensitive_total = sensitive_found = 0
    latencies_ms: list[float] = []
    mistakes: list[dict] = []

    for row in rows * repeat:
        start = time.perf_counter_ns()
        result = pipeline.process(row["input"])
        latencies_ms.append((time.perf_counter_ns() - start) / 1_000_000)
        output = result.to_dict()
        gold = row.get("gold", {})
        row_mistakes = []
        for field in row.get("check_fields", ("source_type", "event_type", "user_id", "occurred_at")):
            field_total += 1
            if output.get(field) == gold.get(field):
                field_correct += 1
            else:
                row_mistakes.append({"field": field, "expected": gold.get(field), "actual": output.get(field)})

        expected_status = gold.get("quality_status")
        if expected_status:
            status_total += 1
            if output["quality"]["status"] == expected_status:
                status_correct += 1
            else:
                row_mistakes.append(
                    {
                        "field": "quality.status",
                        "expected": expected_status,
                        "actual": output["quality"]["status"],
                    }
                )

        expected_sensitive = set(gold.get("sensitive_labels", ()))
        sensitive_total += len(expected_sensitive)
        sensitive_found += len(expected_sensitive & set(output["redactions"]))
        if row_mistakes:
            mistakes.append({"id": row.get("id", ""), "mistakes": row_mistakes})

    return {
        "dataset": str(path),
        "total": len(rows) * repeat,
        "unique_cases": len(rows),
        "repeat": repeat,
        "field_accuracy": field_correct / field_total if field_total else 0.0,
        "field_correct": field_correct,
        "field_total": field_total,
        "quality_status_accuracy": status_correct / status_total if status_total else 0.0,
        "quality_status_correct": status_correct,
        "quality_status_total": status_total,
        "sensitive_recall": sensitive_found / sensitive_total if sensitive_total else 1.0,
        "sensitive_found": sensitive_found,
        "sensitive_total": sensitive_total,
        "latency_ms": {
            "mean": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
            "p50": percentile(latencies_ms, 0.50),
            "p95": percentile(latencies_ms, 0.95),
            "p99": percentile(latencies_ms, 0.99),
        },
        "mistakes": mistakes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate multi-source ingestion quality.")
    parser.add_argument("--data", default="evaluation/datasets/ingestion_dataset.jsonl")
    parser.add_argument("--show-mistakes", action="store_true")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the development set for a larger latency sample.")
    args = parser.parse_args()
    report = evaluate(Path(args.data), repeat=args.repeat)
    print(f"dataset: {report['dataset']}")
    print(f"total: {report['total']}")
    print(f"field_accuracy: {report['field_accuracy']:.2%} ({report['field_correct']}/{report['field_total']})")
    print(
        "quality_status_accuracy: "
        f"{report['quality_status_accuracy']:.2%} "
        f"({report['quality_status_correct']}/{report['quality_status_total']})"
    )
    print(f"sensitive_recall: {report['sensitive_recall']:.2%} ({report['sensitive_found']}/{report['sensitive_total']})")
    print("latency_ms: " + json.dumps(report["latency_ms"], ensure_ascii=False))
    if args.show_mistakes and report["mistakes"]:
        print("mistakes:")
        print(json.dumps(report["mistakes"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
