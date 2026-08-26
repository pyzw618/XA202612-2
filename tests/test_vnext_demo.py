"""Acceptance tests for the fixed, redacted vNext demo replay."""

from __future__ import annotations

import json
from pathlib import Path

from examples.vnext_demo.run_demo import SCENARIOS, main


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_all_demo_scenarios_are_replayable_redacted_and_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo-output"
    assert main(["--scenario", "all", "--output-dir", str(output_dir)]) == 0

    expected = {*SCENARIOS, "all"}
    assert {path.stem for path in output_dir.glob("*.json")} == expected
    all_report = _read_json(output_dir / "all.json")
    assert all_report["covered_scenarios"] == list(SCENARIOS)
    assert all_report["redacted"] is True
    assert (output_dir / "demo.db").exists()

    forbidden = (
        "i need to prepare",
        "this time use docx",
        "project a official report uses docx",
        "checkpoint payload",
        '"query"',
    )
    first_reports = {
        name: _read_json(output_dir / f"{name}.json") for name in SCENARIOS
    }
    for report in first_reports.values():
        serialized = json.dumps(report, ensure_ascii=False).lower()
        assert report["redacted"] is True
        assert not any(value in serialized for value in forbidden)

    assert first_reports["formation"]["formation"]["authority_memory_count"] == 0
    assert first_reports["evidence"]["evidence_consolidation"]["candidate_status"] == "CONFIRMED"
    assert first_reports["scope"]["scope_resolution"]["selected_memory_ids"] == [
        "memory-scope-project"
    ]
    retrieval = first_reports["retrieval"]["retrieval_explanation"]
    assert {"intent", "channels", "scope", "budget"} <= set(retrieval)
    assert first_reports["resume"]["resume"]["restart_verified"] is True
    assert first_reports["forget"]["forget"]["residual_retrieval_count"] == 0

    # The report contract is deterministic even though the database contains
    # runtime timestamps and generated audit IDs.
    assert main(["--scenario", "all", "--output-dir", str(output_dir)]) == 0
    for name in (*SCENARIOS, "all"):
        assert _read_json(output_dir / f"{name}.json") == (
            first_reports.get(name) or all_report
        )


def test_each_readme_scenario_command_has_a_runner(tmp_path: Path) -> None:
    output_dir = tmp_path / "individual"
    for name in SCENARIOS:
        assert main(["--scenario", name, "--output-dir", str(output_dir)]) == 0
        report = _read_json(output_dir / f"{name}.json")
        assert report["scenario"] == name
