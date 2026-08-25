"""S5-09 documentation validation.

These tests verify that the vNext operations runbooks exist, reference valid
commands/scripts, and that the documented CLI/MCP/SDK commands execute in a
clean environment.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs" / "spec"
AGENT_README = ROOT / "agent-integration" / "README.md"


@pytest.mark.parametrize(
    "doc",
    [
        DOCS / "VNEXT_DEPLOYMENT.md",
        DOCS / "VNEXT_BACKUP_RECOVERY.md",
        DOCS / "VNEXT_FAULT_HANDLING.md",
        DOCS / "VNEXT_MIGRATION.md",
        DOCS / "VNEXT_ROLLOUT.md",
        DOCS / "VNEXT_ACCEPTANCE.md",
        AGENT_README,
    ],
)
def test_s5_09_documentation_exists(doc: Path) -> None:
    assert doc.exists(), f"{doc} is missing"
    assert doc.stat().st_size > 0


def test_cli_help_is_executable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "memoryhub_cli.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "memoryhub" in result.stdout


def test_mcp_initialize_is_executable() -> None:
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        ensure_ascii=False,
    )
    result = subprocess.run(
        [sys.executable, "-m", "memoryhub_mcp"],
        input=init + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout.splitlines()[0])
    assert response["result"]["serverInfo"]["name"] == "memoryhub"


def test_sdk_import_is_executable() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from memoryhub_client import MemoryHubClient; print(MemoryHubClient)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "MemoryHubClient" in result.stdout


def test_deployment_doc_references_valid_commands() -> None:
    text = (DOCS / "VNEXT_DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "memoryhub --help" in text
    assert "memoryhub search" in text
    assert "python -m memoryhub_mcp" in text
    assert "vnext.mode" in text
