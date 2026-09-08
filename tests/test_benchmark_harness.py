from __future__ import annotations

import argparse
import json

import pytest

from evaluation.datasets.loader import DatasetLoader
from evaluation.metrics.bootstrap import bootstrap_ci
from evaluation.reporting.registry import RunRegistry
from evaluation.run_benchmark import run


def test_dataset_loader_supports_json_and_jsonl(tmp_path):
    row = {
        "case_id": "x",
        "benchmark": "preference",
        "version": "2.0",
        "ability": "preference.explicit",
        "difficulty": "easy",
        "input": {"text": "x"},
        "gold": [],
    }
    json_path = tmp_path / "cases.json"
    json_path.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
    jsonl_path = tmp_path / "cases.jsonl"
    jsonl_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert DatasetLoader().load(json_path)[0].case_id == "x"
    assert DatasetLoader().load(jsonl_path)[0].ability == "preference.explicit"


def test_dataset_loader_rejects_incomplete_case(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('[{"case_id":"x"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fields"):
        DatasetLoader().load(path)


def test_bootstrap_ci_is_deterministic_and_bounded():
    first = bootstrap_ci([0, 1, 1, 1], samples=500)
    assert first == bootstrap_ci([0, 1, 1, 1], samples=500)
    assert 0 <= first[0] <= 0.75 <= first[1] <= 1


def test_dev_no_memory_writes_registry_and_three_level_report(tmp_path):
    args = argparse.Namespace(
        suite="dev",
        backend="no_memory",
        base_url=None,
        latency_iterations=1,
        registry=tmp_path / "runs.sqlite",
        report_dir=tmp_path / "reports",
        json=False,
    )
    result = run(args)
    assert result["status"] == "FAIL"  # no-memory and absent real HTTP must not fake a pass
    assert set(result["metrics"]) == {"preference", "retrieval", "latency", "conflict"}
    assert result["metrics"]["latency"]["value"] is None
    assert RunRegistry(args.registry).get(result["run_id"])["git_sha"]
    report = next(args.report_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "Level 1: Acceptance Summary" in report
    assert "Level 2: Ability Breakdown" in report
    assert "Level 3: Failure Detail" in report
