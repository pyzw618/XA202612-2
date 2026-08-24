"""Run the deterministic S4 reliability matrix and emit a JSON report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

FAULT_MATRIX = (
    "vector_timeout", "duplicate_delivery", "worker_crash", "pre_commit_crash",
    "post_commit_crash", "stale_cache", "index_corruption", "duplicate_event",
)


def run(output: str | None = None) -> dict:
    command = [sys.executable, "-m", "pytest", "tests/test_vnext_reliability.py", "-q"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    report = {
        "suite": "S4 reliability fault injection",
        "matrix": list(FAULT_MATRIX),
        "command": " ".join(command),
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-json")
    args = parser.parse_args()
    result = run(args.output_json)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
