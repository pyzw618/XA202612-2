#!/usr/bin/env python3
"""Point and offline repair for Authority->Projection drift.

Examples:
    python scripts/repair_projections.py --db-path data/memoryhub.db --dry-run
    python scripts/repair_projections.py --db-path data/memoryhub.db --run-worker
    python scripts/repair_projections.py --db-path data/memoryhub.db --memory-id m123
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryhub.core.memory_write import MemoryWriteService  # noqa: E402
from memoryhub.storage.authority_repository import AuthorityRepository  # noqa: E402
from memoryhub.storage.database import (  # noqa: E402
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository  # noqa: E402
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker  # noqa: E402
from memoryhub.storage.repair import RepairService, RepairWorker  # noqa: E402

logger = logging.getLogger(__name__)


def repair_projections(
    db: Database,
    *,
    memory_id: str | None = None,
    memory_type: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    run_worker: bool = False,
    dry_run: bool = False,
    limit: int = 1000,
) -> dict[str, Any]:
    """Run point or offline repair and optionally execute the resulting outbox."""
    authority_repository = AuthorityRepository(db)
    outbox_repo = MemoryProjectionOutboxRepository(db)
    repair_service = RepairService(db, authority_repository, outbox_repo=outbox_repo)

    report: dict[str, Any] = {
        "dry_run": dry_run,
        "mode": "point" if memory_id else "scan",
        "diagnostics": [],
        "errors": [],
    }

    try:
        if memory_id:
            diagnostic = repair_service.repair_one(
                memory_id, memory_type, dry_run=dry_run
            )
            report["diagnostics"].append(diagnostic.__dict__)
        else:
            worker = RepairWorker(repair_service, outbox_repo=outbox_repo)
            diagnostics = worker.run_once(
                tenant_id=tenant_id,
                user_id=user_id,
                dry_run=dry_run,
                limit=limit,
            )
            report["diagnostics"] = [d.__dict__ for d in diagnostics]
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
        return report

    if run_worker and not dry_run:
        try:
            pref_repo = PreferenceRepository(db)
            know_repo = KnowledgeRepository(db)
            projection_worker = ProjectionOutboxWorker(
                pref_repo=pref_repo,
                know_repo=know_repo,
                memory_write_service=MemoryWriteService(
                    pref_repo=pref_repo,
                    know_repo=know_repo,
                    project_immediately=False,
                ),
                outbox_repo=outbox_repo,
            )
            result = projection_worker.run_once(limit=max(1, len(report["diagnostics"])))
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
        description="Repair Authority->Projection drift by re-enqueueing outbox work."
    )
    parser.add_argument("--db-path", required=True, help="Path to the SQLite database.")
    parser.add_argument("--memory-id", help="Repair a single memory by ID.")
    parser.add_argument("--memory-type", help="Optional memory type hint for point repair.")
    parser.add_argument("--tenant-id", help="Limit scan to a tenant.")
    parser.add_argument("--user-id", help="Limit scan to a user.")
    parser.add_argument(
        "--run-worker",
        action="store_true",
        help="Run the projection worker after enqueueing repairs.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report diagnostics without writing."
    )
    parser.add_argument(
        "--limit", type=int, default=1000, help="Maximum authority rows to scan."
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
    report = repair_projections(
        db,
        memory_id=args.memory_id,
        memory_type=args.memory_type,
        tenant_id=args.tenant_id,
        user_id=args.user_id,
        run_worker=args.run_worker,
        dry_run=args.dry_run,
        limit=args.limit,
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
