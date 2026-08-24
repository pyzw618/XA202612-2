"""Environment-backed MCP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


@dataclass(frozen=True)
class McpConfig:
    api_url: str = "http://127.0.0.1:8099"
    user_id: str = "opencode"
    tenant_id: str = "default"
    api_timeout: float = 30.0
    max_tool_output_chars: int = 8000
    project_root: str = ""


def load_config() -> McpConfig:
    project = Path(_env("MEMORYHUB_PROJECT", str(Path.cwd()))).expanduser().resolve()
    return McpConfig(
        api_url=_env("MEMORYHUB_API_URL", "http://127.0.0.1:8099").rstrip("/"),
        user_id=_env("MEMORYHUB_USER_ID", "opencode"),
        tenant_id=_env("MEMORYHUB_TENANT_ID", "default"),
        api_timeout=float(_env("MEMORYHUB_API_TIMEOUT", "30")),
        max_tool_output_chars=max(0, int(_env("MEMORYHUB_MAX_TOOL_OUTPUT_CHARS", "8000"))),
        project_root=str(project),
    )
