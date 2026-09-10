from __future__ import annotations

import json
from pathlib import Path

from evaluation.runners.run_vnext_baseline import (
    DEFAULT_CONFIG,
    DEFAULT_DATASET,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SCHEMA,
    build_baseline_report,
    sha256_file,
)

ROOT = Path(__file__).parents[1]


def test_baseline_inputs_are_present_and_hashed() -> None:
    assert DEFAULT_DATASET.exists()
    assert DEFAULT_SCHEMA.exists()
    assert DEFAULT_CONFIG.exists()
    digest = sha256_file(DEFAULT_DATASET)
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)


def test_baseline_report_has_required_evidence_sections() -> None:
    report = build_baseline_report(
        dataset_path=DEFAULT_DATASET,
        schema_path=DEFAULT_SCHEMA,
        config_path=DEFAULT_CONFIG,
        output_dir=DEFAULT_OUTPUT_DIR,
        tests={"status": "PASS", "command": ["pytest"]},
        retrieval={"status": "PASS", "report": {"groups": {}}},
    )
    assert report["repository"]["commit"]
    assert report["configuration"]["sha256"]
    assert report["dataset"]["sha256"]
    assert report["model_and_index"]["embedding_model"]
    assert report["model_and_index"]["index_version"]
    assert report["tests"]["status"] == "PASS"
    assert report["retrieval"]["status"] == "PASS"
    assert "latency" in report
    assert "write_bypass_scan" in report
    json.dumps(report, ensure_ascii=False)
