"""Restricted demo tools used by the Qwen weekly-report Agent."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def build_demo_tools(workspace: Path):
    from langchain_core.tools import StructuredTool

    workspace = workspace.resolve()
    output_dir = workspace / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    def file_search(query: str) -> dict[str, Any]:
        """Search text, Markdown, and JSON files in the demo project workspace."""
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", query)]
        matches = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file() or output_dir in path.parents:
                continue
            if path.suffix.lower() not in {".txt", ".md", ".json"}:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            haystack = f"{path.name}\n{content}".lower()
            if not terms or any(term in haystack for term in terms):
                matches.append(
                    {
                        "path": str(path.relative_to(workspace)),
                        "excerpt": content[:500],
                    }
                )
        return {"query": query, "matches": matches[:10]}

    def calendar_read() -> dict[str, Any]:
        """Read this week's calendar events from the demo workspace."""
        path = workspace / "calendar.json"
        if not path.exists():
            return {"events": [], "warning": "calendar.json not found"}
        return json.loads(path.read_text(encoding="utf-8"))

    def report_writer(
        content: str, filename: str = "weekly_report.md"
    ) -> dict[str, Any]:
        """Write a Markdown weekly report into the restricted output directory."""
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".md"):
            safe_name = f"{safe_name}.md"
        target = output_dir / safe_name
        target.write_text(content, encoding="utf-8")
        return {
            "path": str(target.relative_to(workspace)),
            "characters": len(content),
        }

    return [
        StructuredTool.from_function(file_search),
        StructuredTool.from_function(calendar_read),
        StructuredTool.from_function(report_writer),
    ]
