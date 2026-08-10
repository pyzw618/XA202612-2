"""End-to-end tests for the MemoryHub MCP server.

Boots the real MemoryHub FastAPI app (dev mode: mock embedding + faiss) with
uvicorn on an ephemeral port, then drives the MCP JSON-RPC handler over that
HTTP backend. Run with the project's Python (>= 3.10):

    D:/Anaconda/envs/py12/python.exe -m pytest opencode-integration/tests/test_mcp_server.py -v
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_DIR = REPO_ROOT / "mcp-server"

os.environ["MEMORYHUB_AUDIT_HMAC_KEY"] = base64.b64encode(b"A" * 32).decode()
os.environ["MEMORYHUB_QUARANTINE_KEY"] = base64.b64encode(b"B" * 32).decode()

# Keep imports deterministic: compat first, then memoryhub.
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(MCP_DIR))

from memoryhub_compat import apply_re_parser_shim, ensure_safety_keys, patch_event_repository  # noqa: E402

apply_re_parser_shim()
ensure_safety_keys()
patch_event_repository()

import pytest  # noqa: E402
import uvicorn  # noqa: E402

from memoryhub.app import create_app  # noqa: E402
from memoryhub.config import AppConfig, EmbeddingConfig, SafetyConfig, StorageConfig  # noqa: E402

from memoryhub_mcp.config import McpConfig  # noqa: E402
from memoryhub_mcp.server import MemoryHubMcpServer  # noqa: E402


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


def test_initialize(running_server):
    mcp, _ = running_server
    response = _rpc(mcp, "initialize", {"protocolVersion": "2025-06-18"})
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["capabilities"]["tools"]["listChanged"] is True
    assert response["result"]["serverInfo"]["name"] == "memoryhub-mcp"


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


def test_health(running_server):
    mcp, _ = running_server
    response = _call_tool(mcp, "memoryhub_health", {})
    assert response["result"]["isError"] is False
    assert "可达" in response["result"]["content"][0]["text"]


def test_write_event_then_search_preference(running_server):
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
    assert "extraction_failures=1" in text  # 无 LLM，抽取进入重试队列，事件本身已接受


def test_forget(running_server):
    mcp, _ = running_server
    response = _call_tool(
        mcp,
        "memoryhub_forget",
        {"instruction": "忘掉我关于周报格式的偏好", "user_id": "u1"},
    )
    assert response["result"]["isError"] is False, response
    assert "deleted=" in response["result"]["content"][0]["text"]


def test_contract_error_is_surfaced(running_server):
    mcp, _ = running_server
    # 违反 MemoryEvent 契约：tool_calls 序列不连续
    response = _call_tool(
        mcp,
        "memoryhub_write_event",
        {
            "tool_calls": [
                {"tool_name": "bash", "arguments": {}, "status": "success", "sequence": 1},
                {"tool_name": "bash", "arguments": {}, "status": "success", "sequence": 1},
            ],
            "user_id": "u1",
        },
    )
    assert response["result"]["isError"] is True
    assert "contract" in response["result"]["content"][0]["text"].lower() or "invalid" in response["result"]["content"][0]["text"].lower()


def test_stdio_framing_smoke(running_server):
    """Spawn the real stdio server and speak JSON-RPC over pipes."""
    mcp, api_url = running_server
    env = dict(os.environ)
    env["MEMORYHUB_API_URL"] = api_url
    env["MEMORYHUB_USER_ID"] = "u1"
    env["MEMORYHUB_REPO_ROOT"] = str(REPO_ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "memoryhub_mcp"],
        cwd=str(MCP_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        encoding="utf-8",
    )
    try:
        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}) + "\n"
        )
        proc.stdin.flush()
        line = proc.stdout.readline()
        initialize = json.loads(line)
        assert initialize["result"]["serverInfo"]["name"] == "memoryhub-mcp"

        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n")
        proc.stdin.flush()
        tools = json.loads(proc.stdout.readline())["result"]["tools"]
        assert len(tools) == 12
    finally:
        proc.stdin.close()
        proc.terminate()
