#!/usr/bin/env python3
"""Rebuild vector/BM25 projections from the Authority Store.

Authority (preferences, knowledge and their lineage/evidence) is the only
source of truth.  Projections are disposable: deleting the index and running
this script must restore the same memory_id/content_version pairs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Allow running from repo root without package installation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryhub.storage.database import (  # noqa: E402
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository  # noqa: E402
from memoryhub.storage.models import KnowledgeRow, PreferenceRow  # noqa: E402

logger = logging.getLogger(__name__)


def _active_preferences(session) -> list[PreferenceRow]:
    return (
        session.query(PreferenceRow)
        .filter(PreferenceRow.status.in_(["active"]))
        .all()
    )


def _active_knowledge(session) -> list[KnowledgeRow]:
    return (
        session.query(KnowledgeRow)
        .filter(KnowledgeRow.status.in_(["active"]))
        .all()
    )


def _content_version(row: PreferenceRow | KnowledgeRow) -> int:
    """Authority version exposed to projections.  Preferences/Knowledge currently use
    the ``version`` column as their content version; a dedicated
    ``content_version`` column can be added later without changing the script
    contract because ``version`` remains the authoritative fallback.
    """
    return max(1, int(row.version or 1))


def _row_payload(row: PreferenceRow | KnowledgeRow) -> dict[str, Any]:
    """Minimal payload that lets the projection worker reconstruct the memory."""
    return {
        "memory_id": row.memory_id,
        "memory_type": row.memory_type,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "content_version": _content_version(row),
        "text": getattr(row, "text", None) or getattr(row, "content", None) or "",
    }


def rebuild_projections(
    db: Database,
    *,
    clear_existing: bool = False,
    run_worker: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan Authority and enqueue projection upserts for every active memory.

    Args:
        db: Initialized Database instance.
        clear_existing: If True, delete existing projection outbox rows first so
            the rebuild starts from a clean queue.
        run_worker: If True, also run the projection worker once after enqueueing.
        dry_run: If True, report what would be done without writing anything.

    Returns:
        A report with counts, the list of projected memory IDs and any errors.
    """
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    outbox = MemoryProjectionOutboxRepository(db)

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "cleared": 0,
        "enqueued": 0,
        "skipped": 0,
        "memory_ids": [],
        "errors": [],
    }

    with db.session() as session:
        if clear_existing and not dry_run:
            # We refer to the model directly below.
            from memoryhub.storage.models import MemoryProjectionOutboxRow

            report["cleared"] = (
                session.query(MemoryProjectionOutboxRow).delete(synchronize_session=False)
            )

        preferences = _active_preferences(session)
        knowledge = _active_knowledge(session)
        rows = [(row, "preference") for row in preferences] + [
            (row, "knowledge") for row in knowledge
        ]

        for row, memory_type in rows:
            payload = _row_payload(row)
            report["memory_ids"].append(
                {
                    "memory_id": row.memory_id,
                    "memory_type": memory_type,
                    "content_version": payload["content_version"],
                }
            )
            if dry_run:
                continue
            try:
                outbox.enqueue(
                    memory_id=row.memory_id,
                    memory_type=memory_type,
                    operation="upsert",
                    payload=payload,
                    session=session,
                    tenant_id=row.tenant_id,
                    user_id=row.user_id,
                    content_version=payload["content_version"],
                    projection_type="vector",
                )
                report["enqueued"] += 1
            except Exception as exc:  # noqa: BLE001
                report["errors"].append({"memory_id": row.memory_id, "error": str(exc)})
                report["skipped"] += 1
        if not dry_run:
            session.flush()

    if run_worker and not dry_run:
        try:
            from memoryhub.core.memory_write import MemoryWriteService
            from memoryhub.storage.projection_outbox import ProjectionOutboxWorker

            worker = ProjectionOutboxWorker(
                pref_repo=pref_repo,
                know_repo=know_repo,
                memory_write_service=MemoryWriteService(
                    pref_repo=pref_repo,
                    know_repo=know_repo,
                    project_immediately=False,
                ),
                outbox_repo=outbox,
            )
            result = worker.run_once(limit=max(1, report["enqueued"]))
            report["worker"] = {
                "succeeded": len(result.succeeded),
                "failed": len(result.failed),
                "failed_ids": result.failed,
            }
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"worker": str(exc)})

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild vector/BM25 projections from the Authority Store."
    )
    parser.add_argument("--db-path", required=True, help="Path to the SQLite database.")
    parser.add_argument(
        "--clear", action="store_true", help="Delete existing projection outbox rows first."
    )
    parser.add_argument(
        "--run-worker", action="store_true", help="Run the projection worker once after enqueueing."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be enqueued without writing."
    )
    parser.add_argument("--report", help="Write JSON report to this path.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = Database(args.db_path)
    db.init_schema()
    report = rebuild_projections(
        db,
        clear_existing=args.clear,
        run_worker=args.run_worker,
        dry_run=args.dry_run,
    )

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
