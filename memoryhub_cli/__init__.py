"""Source-checkout bridge to ``agent-integration/memoryhub_cli``."""

from pathlib import Path

_CANONICAL = Path(__file__).resolve().parents[1] / "agent-integration" / "memoryhub_cli"
__path__ = [str(_CANONICAL)]

from .cli import main, run  # noqa: E402

__all__ = ["main", "run"]
