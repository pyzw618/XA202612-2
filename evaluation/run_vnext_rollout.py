"""Run deterministic rollout/cutover and rollback-window evidence."""

from __future__ import annotations

import argparse

from memoryhub.application.rollout_service import RolloutController
from memoryhub.config import VNextConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="evaluation/results/vnext_shadow/rollout.json",
    )
    args = parser.parse_args(argv)
    controller = RolloutController(VNextConfig(rollback_window_minutes=60))
    controller.observe(5, request_count=1, window_id="demo-5")
    controller.advance(5)
    controller.rollback(reason="rollback rehearsal", target_level=0)
    for level in (5, 25, 50, 100):
        controller.observe(level, request_count=1, window_id=f"demo-{level}")
        controller.advance(level)
    controller.write_snapshot(args.output)
    print(controller.snapshot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
