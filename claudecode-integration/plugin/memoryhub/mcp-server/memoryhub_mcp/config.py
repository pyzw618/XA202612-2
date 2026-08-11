"""Configuration for the MemoryHub MCP server.

All values can be overridden through environment variables so opencode can
inject them via the ``environment`` block of an MCP server entry.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def _find_repo_root() -> str:
    """Locate the memoryhub repo root (directory containing ``memoryhub/``).

    Resolution order:
      1. MEMORYHUB_REPO_ROOT environment variable
      2. CLAUDE_PROJECT_DIR (set by Claude Code in the MCP server's env)
      3. The parent of this MCP package (``<repo>/opencode-integration/..``)
      4. Walk upward from the current working directory
    """
    explicit = os.environ.get("MEMORYHUB_REPO_ROOT", "").strip()
    if explicit:
        return explicit

    candidates = [
        os.environ.get("CLAUDE_PROJECT_DIR", "").strip(),
        Path(__file__).resolve().parents[3],  # opencode-integration/..
        Path(os.getcwd()).resolve(),
    ]
    for start in candidates:
        if not start:
            continue
        probe = Path(start)
        for _ in range(6):
            if (probe / "memoryhub").is_dir():
                return str(probe)
            parent = probe.parent
            if parent == probe:
                break
            probe = parent
    return str(Path(os.getcwd()).resolve())


def _project_root() -> str:
    """Claude Code's stable project root (launch directory); fallback to cwd."""
    return os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()


@dataclass
class McpConfig:
    api_url: str = field(default_factory=lambda: _env("MEMORYHUB_API_URL", "http://127.0.0.1:8000"))
    api_timeout: float = field(default_factory=lambda: float(_env("MEMORYHUB_API_TIMEOUT", "30")))
    user_id: str = field(default_factory=lambda: _env("MEMORYHUB_USER_ID", "default"))
    repo_root: str = field(default_factory=_find_repo_root)
    project_root: str = field(default_factory=_project_root)
    default_top_k: int = field(default_factory=lambda: int(_env("MEMORYHUB_TOP_K", "5")))
    max_tool_output_chars: int = field(
        default_factory=lambda: int(_env("MEMORYHUB_TOOL_OUTPUT_CHARS", "20000"))
    )

    def validate(self) -> None:
        if not self.api_url.startswith(("http://", "https://")):
            raise ValueError(f"invalid MEMORYHUB_API_URL: {self.api_url!r}")


def load_config() -> McpConfig:
    cfg = McpConfig()
    cfg.validate()
    return cfg
