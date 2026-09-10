from __future__ import annotations

import json
from pathlib import Path

from evaluation.runners.run_vnext_eval import run_vnext_eval


def test_four_layer_runner_writes_versioned_reproducible_report(tmp_path: Path) -> None:
    output = tmp_path / "benchmark.json"
    report = run_vnext_eval(
        output_path=output, e2e_memory_count=20, e2e_query_count=5, e2e_iterations=1
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted == report
    assert set(report["layers"]) == {"formation", "retrieval", "infrastructure", "e2e"}
    assert report["layers"]["infrastructure"]["passed"] is True
    assert report["layers"]["retrieval"]["scope_leak_rate"] == 0.0
    reproducibility = report["reproducibility"]
    assert reproducibility["seed"] == 42
    assert reproducibility["model_version"]
    assert reproducibility["prompt_version"]
    assert reproducibility["weight_version"]
    assert all(len(value) == 64 for value in reproducibility["dataset_sha256"].values())
