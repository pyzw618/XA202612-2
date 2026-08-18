"""Source-checkout bridge to ``agent-integration/memoryhub_mcp``."""

from pathlib import Path

_CANONICAL = Path(__file__).resolve().parents[1] / "agent-integration" / "memoryhub_mcp"
__path__ = [str(_CANONICAL)]

from .server import MemoryHubMcpServer  # noqa: E402

__all__ = ["MemoryHubMcpServer"]
