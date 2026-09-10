from __future__ import annotations

import json
from pathlib import Path

from evaluation.runners.run_vnext_comparison import SYSTEMS, run_vnext_comparison


def test_comparison_uses_four_systems_same_methodology_and_one_at_a_time_ablations(
    tmp_path: Path,
) -> None:
    output = tmp_path / "comparison.json"
    report = run_vnext_comparison(output_path=output, repeats=2)
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted == report
    assert tuple(report["systems"]) == SYSTEMS
    assert report["methodology"]["shared_model"] == "mock-embedding/768"
    assert report["methodology"]["shared_tool_permissions"].startswith("offline")
    assert report["methodology"]["redacted"] is True
    assert set(report["ablations"]) == {
        "NO_ROUTER", "NO_SCOPE_RESOLVER", "NO_RERANKER", "NO_CONTEXT_BUDGET"
    }
    for result in list(report["systems"].values()) + list(report["ablations"].values()):
        for metric in ("task_success", "policy_leak_rate", "mrr", "context_tokens", "latency_ms"):
            assert {"mean", "variance", "ci95_low", "ci95_high"} == set(result[metric])
    assert report["systems"]["NO_MEMORY"]["task_success"]["mean"] == 0.0
    assert report["systems"]["VNEXT"]["policy_leak_rate"]["mean"] == 0.0
