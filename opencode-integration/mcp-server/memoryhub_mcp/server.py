"""MCP stdio server (JSON-RPC 2.0, newline-delimited frames).

Implements just enough of the Model Context Protocol for opencode to list and
call tools: ``initialize``, ``ping``, ``tools/list``, ``tools/call`` and the
``initialized``/``cancelled`` notifications. No third-party ``mcp`` SDK is
required — only stdlib + httpx for the REST calls.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .config import McpConfig, load_config
from .client import MemoryHubClient
from .schemas_bridge import ensure_memoryhub
from .tools import ToolRegistry, handle_tool_error

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "memoryhub-mcp"
SERVER_VERSION = "0.1.0"


def _result(message_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "result": payload}


def _error(message_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


class MemoryHubMcpServer:
    """A single stdio MCP session bound to one MemoryHub configuration."""

    def __init__(self, config: McpConfig | None = None) -> None:
        self.config = config or load_config()
        ensure_memoryhub(self.config.repo_root)
        self.client = MemoryHubClient(
            self.config.api_url,
            timeout=self.config.api_timeout,
            user_id=self.config.user_id,
        )
        self.tools = ToolRegistry(self.client, self.config)

    # ---- JSON-RPC dispatch ----

    def handle(self, message: dict) -> dict | None:
        message_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        if message_id is None:
            # Notification: no response.
            return None

        if method == "initialize":
            requested = params.get("protocolVersion")
            supported = requested if isinstance(requested, str) and requested else PROTOCOL_VERSION
            return _result(
                message_id,
                {
                    "protocolVersion": supported,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            )
        if method == "ping":
            return _result(message_id, {})
        if method == "tools/list":
            return _result(message_id, {"tools": self.tools.list()})
        if method == "tools/call":
            return self._call_tool(message_id, params)
        if method in ("resources/list", "prompts/list"):
            return _result(message_id, {"resources": [], "prompts": []})
        if method in ("resources/templates/list",):
            return _result(message_id, {"resourceTemplates": []})

        return _error(message_id, -32601, f"method not found: {method}")

    def _call_tool(self, message_id: Any, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(message_id, -32602, "tool arguments must be an object")
        try:
            text = self.tools.call(name, arguments)
            if self.config.max_tool_output_chars > 0 and len(text) > self.config.max_tool_output_chars:
                text = text[: self.config.max_tool_output_chars] + "\n…(输出已截断)"
            return _result(message_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as exc:  # noqa: BLE001 - surface every tool failure to the LLM
            return _result(
                message_id,
                {"content": [{"type": "text", "text": handle_tool_error(exc)}], "isError": True},
            )

    # ---- stdio transport ----

    def run_stdio(self) -> None:
        logger.info("%s started, api_url=%s", SERVER_NAME, self.config.api_url)
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            try:
                response = self.handle(message)
            except Exception:  # never let one message kill the server
                logger.exception("unhandled JSON-RPC message")
                if "id" in message:
                    response = _error(message.get("id"), -32603, "internal server error")
                else:
                    response = None
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[memoryhub-mcp] %(levelname)s %(message)s")
    server = MemoryHubMcpServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
