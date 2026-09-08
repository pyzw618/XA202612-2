from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.schemas import BenchmarkCase


class DatasetLoader:
    """Strict loader for V2 cases; it never silently accepts malformed rows."""

    def load_raw(self, path: str | Path) -> list[dict[str, Any]]:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"dataset does not exist: {source}")
        if source.suffix.lower() == ".jsonl":
            rows = []
            for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {source}:{line_number}: {exc.msg}") from exc
            return rows
        if source.suffix.lower() != ".json":
            raise ValueError(f"unsupported dataset format: {source.suffix}")
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, list):
            return value
        if isinstance(value, dict) and isinstance(value.get("cases"), list):
            return value["cases"]
        raise ValueError("JSON dataset must be an array or an object containing 'cases'")

    def load(self, path: str | Path) -> list[BenchmarkCase]:
        return [BenchmarkCase.from_dict(row) for row in self.load_raw(path)]

    def load_retrieval(self, path: str | Path) -> tuple[list[dict], list[dict]]:
        root = Path(path)
        queries = self.load_raw(root / "queries.jsonl")
        qrels = self.load_raw(root / "qrels.jsonl")
        return queries, qrels
