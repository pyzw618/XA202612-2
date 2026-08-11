"""Optional UserPromptSubmit hook: inject MemoryHub context into Claude Code.

When enabled (``MEMORYHUB_CONTEXT_ON_PROMPT=true``), Claude Code calls this
script every time the user submits a prompt. The script sends the prompt to the
MemoryHub REST ``/api/memory/context`` endpoint and prints the retrieved,
prompt-ready memory summary to stdout, where UserPromptSubmit hooks deliver it
to Claude as context.

Safety
------
* Always exits 0. Any failure prints nothing and lets the prompt proceed
  without context — never blocks Claude Code.
* Off by default because every prompt costs one extra REST round-trip.

Configuration (environment variables)
-------------------------------------
MEMORYHUB_CONTEXT_ON_PROMPT   default false — set to true to enable
MEMORYHUB_API_URL             default http://127.0.0.1:8000
MEMORYHUB_USER_ID             default claudecode
MEMORYHUB_TOP_K               default 3
MEMORYHUB_CONTEXT_MAX_CHARS   default 6000 — cap the injected context text
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


@dataclass
class ContextConfig:
    enabled: bool = field(default_factory=lambda: _env("MEMORYHUB_CONTEXT_ON_PROMPT", "false").lower() != "false")
    api_url: str = field(default_factory=lambda: _env("MEMORYHUB_API_URL", "http://127.0.0.1:8000"))
    user_id: str = field(default_factory=lambda: _env("MEMORYHUB_USER_ID", "claudecode"))
    top_k: int = field(default_factory=lambda: int(_env("MEMORYHUB_TOP_K", "3")))
    max_chars: int = field(default_factory=lambda: int(_env("MEMORYHUB_CONTEXT_MAX_CHARS", "6000")))
    timeout: float = field(default_factory=lambda: float(_env("MEMORYHUB_API_TIMEOUT", "30")))


def fetch_context(prompt: str, cfg: ContextConfig) -> str:
    """Retrieve prompt-ready memory context text from MemoryHub."""
    if not prompt.strip():
        return ""
    payload = {
        "user_id": cfg.user_id,
        "query": prompt.strip(),
        "top_k": cfg.top_k,
        "context": {"scene": _env("MEMORYHUB_SCENE", "code"), "task_type": _env("MEMORYHUB_TASK_TYPE", "coding_task"), "app": "claudecode"},
    }
    url = f"{cfg.api_url.rstrip('/')}/api/memory/context"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"[memoryhub-context] warn: context fetch failed: {exc}", file=sys.stderr, flush=True)
        return ""

    text = str(data.get("context_text") or "")
    if cfg.max_chars > 0 and len(text) > cfg.max_chars:
        text = text[:cfg.max_chars] + "\n…(memoryhub context truncated)"
    return text


def main(argv: list[str] | None = None) -> int:
    del argv
    cfg = ContextConfig()
    if not cfg.enabled:
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    prompt = str(payload.get("prompt") or "")
    text = fetch_context(prompt, cfg)
    if text:
        # Plain stdout is delivered to Claude as context by UserPromptSubmit hooks.
        print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
