"""Minimal JSON-RPC MCP stdio transport backed by the shared client."""

from __future__ import annotations

import json
import sys
from typing import Any

from memoryhub_client import MemoryHubClient

from .config import load_config
from .tools import ToolRegistry

PROTOCOL_VERSION = "2024-11-05"


def _result(message_id: Any, payload: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": payload}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


class MemoryHubMcpServer:
    def __init__(self, config=None) -> None:
        self.config = config or load_config()
        self.client = MemoryHubClient(
            self.config.api_url,
            self.config.api_timeout,
            self.config.user_id,
            tenant_id=self.config.tenant_id,
        )
        self.tools = ToolRegistry(self.client, self.config)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        message_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}
        if message_id is None:
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            return _result(message_id, {"protocolVersion": requested or PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "memoryhub", "version": "2.0.0"}})
        if method == "ping":
            return _result(message_id, {})
        if method == "tools/list":
            return _result(message_id, {"tools": self.tools.list()})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _error(message_id, -32602, "tools/call requires name and object arguments")
            text = self.tools.call(name, arguments)
            return _result(message_id, {"content": [{"type": "text", "text": text}], "isError": '"error"' in text[:32]})
        if method in {"resources/list", "resources/templates/list", "prompts/list"}:
            key = "resourceTemplates" if method.endswith("templates/list") else "resources" if method == "resources/list" else "prompts"
            return _result(message_id, {key: []})
        return _error(message_id, -32601, f"method not found: {method}")

    def run_stdio(self) -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
                response = self.handle(message) if isinstance(message, dict) else None
            except (json.JSONDecodeError, TypeError):
                response = None
            except Exception:
                response = _error(message.get("id") if isinstance(message, dict) else None, -32603, "internal server error")
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
                sys.stdout.flush()


def main() -> None:
    MemoryHubMcpServer().run_stdio()


if __name__ == "__main__":
    main()
