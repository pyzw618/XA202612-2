"""End-to-end tests for the Claude Code copy of the MemoryHub MCP server.

Boots the real MemoryHub FastAPI app (dev mode: mock embedding + faiss) with
uvicorn on an ephemeral port, then drives the MCP JSON-RPC handler. Run with
the project's Python (>= 3.10):

    D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_mcp_server.py -v
"""

from __future__ import annotations

import base64
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent  # claudecode-integration/tests
INTEGRATION = HERE.parent  # claudecode-integration
REPO_ROOT = INTEGRATION.parent  # repo root
MCP_DIR = INTEGRATION / "mcp-server"
SCRIPTS_DIR = INTEGRATION / "scripts"

os.environ["MEMORYHUB_AUDIT_HMAC_KEY"] = base64.b64encode(b"A" * 32).decode()
os.environ["MEMORYHUB_QUARANTINE_KEY"] = base64.b64encode(b"B" * 32).decode()
os.environ["MEMORYHUB_USER_RULE_KEY"] = base64.b64encode(b"C" * 32).decode()

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(MCP_DIR))

from memoryhub_compat import apply_re_parser_shim, patch_event_repository  # noqa: E402

apply_re_parser_shim()
patch_event_repository()

import pytest  # noqa: E402
import uvicorn  # noqa: E402
from memoryhub_mcp.config import McpConfig  # noqa: E402
from memoryhub_mcp.server import SERVER_INSTRUCTIONS, MemoryHubMcpServer  # noqa: E402

from memoryhub.app import create_app  # noqa: E402
from memoryhub.config import (  # noqa: E402
    AppConfig,
    EmbeddingConfig,
    SafetyConfig,
    StorageConfig,
)


@pytest.fixture(scope="module")
def running_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("memoryhub")
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp / "memoryhub.db"),
            vector_index_path=str(tmp / "vector_index"),
            evidence_path=str(tmp / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="mock", dimension=64),
        safety=SafetyConfig(user_rules={"enabled": False}),
    )
    app = create_app(config)
    server_config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(server_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"
    port = server.servers[0].sockets[0].getsockname()[1]

    mcp = MemoryHubMcpServer(
        McpConfig(
            api_url=f"http://127.0.0.1:{port}",
            user_id="u1",
            repo_root=str(REPO_ROOT),
        )
    )
    yield mcp, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def _rpc(mcp, method, params, message_id=1):
    return mcp.handle({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})


def _call_tool(mcp, name, arguments):
    return _rpc(mcp, "tools/call", {"name": name, "arguments": arguments})


def test_initialize_with_instructions(running_server):
    mcp, _ = running_server
    response = _rpc(mcp, "initialize", {"protocolVersion": "2025-06-18"})
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["capabilities"]["tools"]["listChanged"] is True
    assert response["result"]["serverInfo"]["name"] == "memoryhub-mcp"
    # Claude Code tool-search reads this to decide when to load the tools.
    assert response["result"]["instructions"] == SERVER_INSTRUCTIONS
    assert "memoryhub_search" in SERVER_INSTRUCTIONS


def test_roots_list(running_server):
    mcp, _ = running_server
    response = _rpc(mcp, "roots/list", {})
    roots = response["result"]["roots"]
    assert len(roots) == 1
    assert roots[0]["uri"].startswith("file://")


def test_tools_list(running_server):
    mcp, _ = running_server
    tools = _rpc(mcp, "tools/list", {})["result"]["tools"]
    names = [tool["name"] for tool in tools]
    for expected in [
        "memoryhub_health",
        "memoryhub_search",
        "memoryhub_get_context",
        "memoryhub_write_event",
        "memoryhub_write_preference",
        "memoryhub_write_knowledge",
        "memoryhub_forget",
        "memoryhub_list_memories",
        "memoryhub_get_memory",
        "memoryhub_feedback",
        "memoryhub_list_conflicts",
        "memoryhub_resolve_conflict",
    ]:
        assert expected in names, f"missing tool {expected}"
    for tool in tools:
        assert "description" in tool and "inputSchema" in tool


def test_write_preference_then_search(running_server):
    mcp, _ = running_server
    write = _call_tool(
        mcp,
        "memoryhub_write_preference",
        {
            "text": "用户喜欢用 Markdown 生成周报",
            "preference_type": "format_preference",
            "scene": "office",
            "task_type": "office.weekly_report",
            "user_id": "u1",
        },
    )
    assert write["result"]["isError"] is False, write
    assert "memory_id=" in write["result"]["content"][0]["text"]

    search = _call_tool(
        mcp,
        "memoryhub_search",
        {"query": "Markdown 周报", "user_id": "u1", "top_k": 5},
    )
    assert search["result"]["isError"] is False, search
    text = search["result"]["content"][0]["text"]
    assert "用户偏好" in text
    assert "Markdown" in text


def test_write_event_agent_response(running_server):
    mcp, _ = running_server
    response = _call_tool(
        mcp,
        "memoryhub_write_event",
        {
            "event_type": "agent_response",
            "text": "已根据配置生成项目周报",
            "session_id": "sess_test_1",
            "turn_id": "turn_test_1",
            "scene": "office",
            "task_type": "office.weekly_report",
            "tool_calls": [
                {
                    "tool_name": "file_search",
                    "arguments": {"query": "周报"},
                    "result": {"files": ["report.md"]},
                    "status": "success",
                    "sequence": 1,
                }
            ],
            "user_id": "u1",
        },
    )
    assert response["result"]["isError"] is False, response
    text = response["result"]["content"][0]["text"]
    assert "accepted=1" in text
    # With fact extraction enabled, preference and fact extraction both enter
    # the retry queue when no LLM is available; the event itself stays accepted.
    assert "extraction_failures=2" in text
    assert "retry_tasks_enqueued=2" in text


def test_unknown_method_error(running_server):
    mcp, _ = running_server
    response = _rpc(mcp, "unknown/method", {})
    assert response["error"]["code"] == -32601


def test_health(running_server):
    mcp, _ = running_server
    response = _call_tool(mcp, "memoryhub_health", {})
    assert response["result"]["isError"] is False
    assert "可达" in response["result"]["content"][0]["text"]


def test_stdlib_smoke():
    """The server must run from the copied package without an mcp SDK."""
    import subprocess

    env = dict(os.environ)
    env["PYTHONPATH"] = str(MCP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", "import memoryhub_mcp.server; print('ok')"],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
