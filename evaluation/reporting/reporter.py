from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_report(run: dict[str, Any], directory: str | Path) -> tuple[Path, Path]:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{run['suite']}_{run['run_id']}"
    json_path, md_path = root / f"{stem}.json", root / f"{stem}.md"
    json_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# MemoryHub Acceptance Benchmark V2",
        "",
        "## Level 1: Acceptance Summary",
        "",
        "| Metric | Value | 95% CI | Result |",
        "|---|---:|---:|:---:|",
    ]
    for metric in run.get("metrics", {}).values():
        ci = metric.get("ci95")
        ci_text = f"[{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "—"
        display = metric.get("display", metric.get("value"))
        lines.append(f"| {metric['name']} | {display} | {ci_text} | {metric['status']} |")
    lines += ["", f"**FINAL: {run['status']}**", "", "## Level 2: Ability Breakdown", ""]
    breakdown = run.get("ability_breakdown") or {}
    lines.append("```json\n" + json.dumps(breakdown, ensure_ascii=False, indent=2) + "\n```")
    lines += ["", "## Level 3: Failure Detail", ""]
    failures = run.get("failures") or []
    lines.append(
        "No failed cases."
        if not failures
        else "```json\n" + json.dumps(failures, ensure_ascii=False, indent=2) + "\n```"
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path
