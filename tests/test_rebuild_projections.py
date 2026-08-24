from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from memoryhub.storage.database import Database
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import KnowledgeRow, PreferenceRow

ROOT = Path(__file__).parents[1]
DB_BASE = ROOT / "evaluation" / "results" / "rebuild_projections_test"
_db_counter = 0


def _db() -> Database:
    global _db_counter
    _db_counter += 1
    db_path = DB_BASE.parent / f"{DB_BASE.name}_{int(time.time() * 1000)}_{_db_counter}.db"
    db = Database(str(db_path))
    db.init_schema()
    return db


def _run_script(*args: str) -> tuple[int, str, str]:
    script = ROOT / "scripts" / "rebuild_projections.py"
    cmd = [sys.executable, str(script), *args]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    return result.returncode, result.stdout, result.stderr


def test_rebuild_projections_enqueues_active_authority_memories() -> None:
    db = _db()

    with db.session() as session:
        session.add(
            PreferenceRow(
                memory_id="pref-rebuild-1",
                user_id="user-rebuild",
                tenant_id="tenant-rebuild",
                preference_type="output_style",
                content="Use Markdown",
                status="active",
                version=3,
            )
        )
        session.add(
            KnowledgeRow(
                memory_id="know-rebuild-1",
                user_id="user-rebuild",
                tenant_id="tenant-rebuild",
                knowledge_type="fact",
                name="Reboot fixes it",
                content="Reboot fixes it",
                status="active",
                version=2,
            )
        )
        session.add(
            PreferenceRow(
                memory_id="pref-deleted",
                user_id="user-rebuild",
                tenant_id="tenant-rebuild",
                preference_type="output_style",
                content="Old rule",
                status="deleted",
                version=1,
            )
        )
        session.flush()

    returncode, stdout, stderr = _run_script(
        "--db-path", db.db_path, "--report", str(DB_BASE.parent / "rebuild_report.json")
    )
    assert returncode == 0, stderr

    outbox = MemoryProjectionOutboxRepository(db)
    pending = outbox.list_by_status(("pending",), limit=100)
    memory_ids = {item.memory_id for item in pending}
    assert memory_ids == {"pref-rebuild-1", "know-rebuild-1"}

    # Verify content_version by reading the underlying outbox rows directly.
    with db.session() as session:
        from memoryhub.storage.models import MemoryProjectionOutboxRow

        rows = session.query(MemoryProjectionOutboxRow).all()
        version_map = {row.memory_id: row.content_version for row in rows}
        assert version_map["pref-rebuild-1"] == 3
        assert version_map["know-rebuild-1"] == 2

    # Deleted memories must not be enqueued.
    assert "pref-deleted" not in memory_ids
    db.close()


def test_rebuild_projections_dry_run_does_not_write() -> None:
    db = _db()
    with db.session() as session:
        session.add(
            PreferenceRow(
                memory_id="pref-dryrun",
                user_id="user-dryrun",
                tenant_id="tenant-dryrun",
                preference_type="output_style",
                content="Use DOCX",
                status="active",
                version=1,
            )
        )
        session.flush()

    returncode, stdout, _ = _run_script("--db-path", db.db_path, "--dry-run")
    assert returncode == 0
    report = Path(DB_BASE.parent / "rebuild_report.json")
    report.unlink(missing_ok=True)

    outbox = MemoryProjectionOutboxRepository(db)
    assert outbox.list_by_status(("pending",), limit=100) == []
    db.close()


def test_rebuild_projections_report_matches_authority() -> None:
    db = _db()
    with db.session() as session:
        session.add(
            KnowledgeRow(
                memory_id="know-report",
                user_id="user-report",
                tenant_id="tenant-report",
                knowledge_type="workflow",
                name="Deploy",
                content="Deploy workflow",
                status="active",
                version=5,
            )
        )
        session.flush()

    report_path = DB_BASE.parent / f"rebuild_report_{int(time.time() * 1000)}.json"
    returncode, _, _ = _run_script("--db-path", db.db_path, "--report", str(report_path))
    assert returncode == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["enqueued"] == 1
    assert report["memory_ids"] == [
        {"memory_id": "know-report", "memory_type": "knowledge", "content_version": 5}
    ]
    db.close()
