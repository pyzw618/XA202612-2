from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from memoryhub.adapter.schemas import Evidence, KnowledgeMemory, PreferenceMemory, SourceType
from memoryhub.core.fact.models import Fact
from memoryhub.core.fact.store import FactStore
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import MemoryEvidenceRow, MemoryLineageRow

SCRIPT = Path(__file__).parents[1] / "scripts" / "migrate_memory_provenance.py"


def _legacy_database(tmp_path) -> str:
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path)
    db.init_schema()
    PreferenceRepository(db).save(
        PreferenceMemory(
            user_id="u-pref",
            text="Legacy markdown preference",
            payload={"target": "format", "value": "markdown"},
            evidences=[
                Evidence(
                    event_id="evt_pref",
                    content="legacy pref evidence",
                    source_type=SourceType.USER_BEHAVIOR,
                )
            ],
        )
    )
    KnowledgeRepository(db).save(
        KnowledgeMemory(
            user_id="u-know",
            name="Legacy workflow",
            content="Legacy knowledge content",
            evidences=[
                Evidence(
                    event_id="evt_know",
                    content="legacy knowledge evidence",
                    source_type=SourceType.TOOL_RESULT,
                )
            ],
        )
    )
    db.close()

    fact_store = FactStore(db_path)
    fact = Fact(
        fact_id="fact_legacy",
        subject_id="entity:project:a",
        predicate_id="owner",
        object_id="entity:person:alice",
        object_value="Alice",
        source_text="legacy fact evidence",
        source_id="evt_fact",
        observed_at="2026-08-15T00:00:00Z",
        confidence=0.9,
        user_id="u-fact",
    )
    fact_store.insert_fact(fact)
    fact_store.save_fact_evidence(fact)
    fact_store.close()
    return db_path


def _run(db_path: str, *extra: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", db_path, *extra],
        cwd=str(SCRIPT.parents[1]),
        check=False,
        capture_output=True,
        text=True,
    )


def test_migration_dry_run_is_write_free_and_reports_planned_counts(tmp_path):
    db_path = _legacy_database(tmp_path)
    report = tmp_path / "dry-report.json"

    run = _run(db_path, "--dry-run", "--report", str(report))

    assert run.returncode == 0, run.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert payload["counters"]["preference.lineage.planned"] == 1
    assert payload["counters"]["fact.evidence.planned"] == 1

    db = Database(db_path)
    db.init_schema()
    with db.session() as session:
        assert session.query(MemoryLineageRow).count() == 0
        assert session.query(MemoryEvidenceRow).count() == 0
    db.close()


def test_migration_is_idempotent_and_emits_checkpoint_validation_and_rollback(tmp_path):
    db_path = _legacy_database(tmp_path)
    report = tmp_path / "report.json"
    rollback = tmp_path / "rollback.sql"

    first = _run(db_path, "--report", str(report), "--rollback-sql", str(rollback))
    assert first.returncode == 0, first.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["validation"]["owner_scope_valid"] is True
    assert payload["counters"]["preference.lineage.inserted"] == 1
    assert payload["counters"]["knowledge.evidence.inserted"] == 1
    assert payload["counters"]["fact.evidence.inserted"] == 1
    assert "DELETE FROM memory_evidence" in rollback.read_text(encoding="utf-8")

    db = Database(db_path)
    db.init_schema()
    with db.session() as session:
        assert session.query(MemoryLineageRow).count() == 3
        assert session.query(MemoryEvidenceRow).count() == 3
        checkpoint = (
            session.connection()
            .exec_driver_sql(
                "SELECT status FROM memory_migration_checkpoint WHERE migration_name = ?",
                ("main_to_remem_provenance_v1",),
            )
            .scalar_one()
        )
        assert checkpoint == "completed"
    db.close()

    second = _run(db_path, "--report", str(report))
    assert second.returncode == 0, second.stderr
    repeated = json.loads(report.read_text(encoding="utf-8"))
    assert repeated["counters"]["preference.lineage.existing"] == 1
    assert repeated["counters"]["fact.evidence.existing"] == 1
