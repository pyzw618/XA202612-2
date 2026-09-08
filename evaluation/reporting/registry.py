from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class RunRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(self, run: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS benchmark_runs "
                "(run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO benchmark_runs VALUES (?, ?, ?)",
                (run["run_id"], run["created_at"], json.dumps(run, ensure_ascii=False)),
            )

    def get(self, run_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT payload FROM benchmark_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None
