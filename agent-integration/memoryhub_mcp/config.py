"""Environment-backed MCP configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from memoryhub_client.config import ClientConfig, current_user_id


def _env(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


@dataclass(frozen=True)
class McpConfig:
    api_url: str = "http://127.0.0.1:8099"
    user_id: str = field(default_factory=current_user_id)
    tenant_id: str = "default"
    api_timeout: float = 30.0
    max_tool_output_chars: int = 8000
    project_root: str = ""


def load_config() -> McpConfig:
    project = Path(_env("MEMORYHUB_PROJECT", str(Path.cwd()))).expanduser().resolve()
    shared = ClientConfig.load(cwd=project)
    return McpConfig(
        api_url=shared.api_url,
        user_id=shared.user_id,
        tenant_id=shared.tenant_id,
        api_timeout=shared.timeout,
        max_tool_output_chars=max(0, int(_env("MEMORYHUB_MAX_TOOL_OUTPUT_CHARS", "8000"))),
        project_root=str(project),
    )
