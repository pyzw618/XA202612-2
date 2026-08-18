"""Source-checkout bridge to ``agent-integration/memoryhub_client``."""

from pathlib import Path

_CANONICAL = Path(__file__).resolve().parents[1] / "agent-integration" / "memoryhub_client"
__path__ = [str(_CANONICAL)]

from .client import MemoryHubClient, MemoryHubError  # noqa: E402

__all__ = ["MemoryHubClient", "MemoryHubError"]
