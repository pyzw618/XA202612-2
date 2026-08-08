"""Clean one raw OS Agent event and print its canonical MemoryEvent 1.1 JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from memoryhub.core.ingestion import IngestionPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / "raw_agent_event.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    raw_data = json.loads(args.input.read_text(encoding="utf-8"))
    result = IngestionPipeline().process(raw_data).model_dump()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
