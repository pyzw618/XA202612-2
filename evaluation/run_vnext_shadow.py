"""Emit a deterministic redacted Formation/dual-read Shadow report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.application.shadow_read_service import ShadowReadService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="evaluation/results/vnext_shadow/shadow.json",
    )
    args = parser.parse_args(argv)
    service = ShadowReadService(
        reflection_service=ReflectionService(model=DeterministicReflectionModel())
    )
    request = MemoryRetrievalRequest(
        request_id="shadow-demo-request",
        tenant_id="tenant-demo",
        user_id="user-demo",
        query="demo query is never persisted in the report",
        token_budget=256,
    )
    service.dual_read(
        request,
        legacy_reader=lambda _: [{"memory_id": "legacy-demo", "tenant_id": "tenant-demo"}],
        vnext_reader=lambda _: [{"memory_id": "vnext-demo", "tenant_id": "tenant-demo"}],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(service.report.to_redacted_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(service.report.to_redacted_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
