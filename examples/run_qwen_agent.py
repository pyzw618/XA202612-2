"""Run the real Qwen weekly-report Agent against a local MemoryHub."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from integrations.agents.config import QwenAgentSettings
from integrations.agents.qwen_agent import QwenMemoryAgent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt",
        nargs="?",
        default="读取本周项目资料并生成 Markdown 周报。",
    )
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--session-id", default="")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(__file__).parent / "demo_workspace",
    )
    args = parser.parse_args()

    try:
        agent = QwenMemoryAgent(QwenAgentSettings.from_env(), args.workspace)
    except RuntimeError as exc:
        parser.error(str(exc))
    try:
        result = agent.run(
            args.prompt,
            user_id=args.user_id,
            session_id=args.session_id,
        )
    finally:
        agent.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
