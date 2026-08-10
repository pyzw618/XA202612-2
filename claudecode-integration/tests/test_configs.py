"""Validate the Claude Code integration's JSON configuration files.

Checks structural correctness only (valid JSON, expected keys/hooks), so config
mistakes surface before the plugin is wired into Claude Code.

    D:/Anaconda/envs/py12/python.exe -m pytest claudecode-integration/tests/test_configs.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

INTEGRATION = Path(__file__).resolve().parents[1]  # claudecode-integration/


def _load(rel):
    path = INTEGRATION / rel
    assert path.exists(), f"missing {rel}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_plugin_manifest():
    manifest = _load("plugin/memoryhub/.claude-plugin/plugin.json")
    assert manifest["name"] == "memoryhub"
    assert manifest.get("description")
    assert manifest.get("version")


def test_plugin_mcp_config():
    mcp = _load("plugin/memoryhub/.mcp.json")
    servers = mcp["mcpServers"]
    assert "memoryhub" in servers
    entry = servers["memoryhub"]
    assert entry["type"] == "stdio"
    assert entry["command"] in ("python", "${MEMORYHUB_PYTHON:-python}")
    env = entry.get("env", {})
    assert "PYTHONPATH" in env and "${CLAUDE_PLUGIN_ROOT}" in env["PYTHONPATH"]
    assert "MEMORYHUB_API_URL" in env


def test_plugin_hooks_structure():
    hooks = _load("plugin/memoryhub/hooks/hooks.json")
    h = hooks["hooks"]
    for event in ("PostToolBatch", "Stop", "SessionEnd"):
        assert event in h, f"missing hook {event}"
        handler = h[event][0]["hooks"][0]
        assert handler["type"] == "command"
        assert handler["command"] == "python"
        assert "${CLAUDE_PLUGIN_ROOT}" in handler["args"][0]
    # PostToolBatch must be non-blocking (async)
    assert h["PostToolBatch"][0]["hooks"][0]["async"] is True
    # UserPromptSubmit context injection is optional but wired
    assert "UserPromptSubmit" in h


def test_example_mcp_config():
    mcp = _load("examples/.mcp.json")
    assert "memoryhub" in mcp["mcpServers"]
    assert "${CLAUDE_PROJECT_DIR:-.}" in mcp["mcpServers"]["memoryhub"]["env"]["PYTHONPATH"]


def test_example_settings_hooks():
    settings = _load("examples/settings.local.json")
    h = settings["hooks"]
    for event in ("PostToolBatch", "Stop", "SessionEnd"):
        assert event in h
    args0 = h["Stop"][0]["hooks"][0]["args"][0]
    assert "${CLAUDE_PROJECT_DIR}/claudecode-integration" in args0


def test_record_script_is_stdlib_only():
    import ast

    src = (INTEGRATION / "plugin/memoryhub/scripts/record.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    stdlib = {
        "__future__",
        "dataclasses",
        "datetime",
        "hashlib",
        "importlib",
        "json",
        "os",
        "pathlib",
        "sys",
        "time",
        "typing",
        "urllib",
    }
    # `memoryhub` is the optional repo package imported with a try/except
    # fallback in _finalize_event — not a pip dependency.
    third_party = imports - stdlib - {"memoryhub"}
    assert not third_party, f"record.py must be stdlib-only, found: {third_party}"


def test_plugin_embeds_the_mcp_server_copy():
    """The plugin must be self-contained: its mcp-server copy stays in sync."""
    top = INTEGRATION / "mcp-server" / "memoryhub_mcp"
    inside = INTEGRATION / "plugin" / "memoryhub" / "mcp-server" / "memoryhub_mcp"
    assert inside.is_dir(), "plugin is missing its bundled memoryhub_mcp package"
    for py in sorted(top.glob("*.py")):
        target = inside / py.name
        assert target.exists(), f"plugin bundle missing {py.name}"
        assert py.read_bytes() == target.read_bytes(), f"plugin bundle drifted: {py.name}"
