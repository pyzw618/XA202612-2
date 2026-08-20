import json
from pathlib import Path

import httpx

from memoryhub_client import MemoryHubClient
from memoryhub_client.config import ClientConfig


def test_project_defaults_to_git_root(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    config = ClientConfig.load(cwd=tmp_path)
    assert config.project == str(tmp_path)


def test_linux_global_config_uses_xdg_config_home(tmp_path: Path, monkeypatch):
    config_home = tmp_path / "xdg"
    config_file = config_home / "memoryhub" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"user_id": "ethan", "api_url": "http://127.0.0.1:9000"}))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.delenv("APPDATA", raising=False)

    config = ClientConfig.load(cwd=tmp_path)

    assert config.user_id == "ethan"
    assert config.api_url == "http://127.0.0.1:9000"


def test_client_maps_memory_and_agent_routes():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/decision"):
            return httpx.Response(200, json={"status": "committed"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://memoryhub.test", transport=transport)
    with MemoryHubClient("http://memoryhub.test", client=http) as client:
        assert client.system_status() == {"ok": True}
        assert client.decide_knowledge_fact("proposal_1", commit=True) == {"status": "committed"}
    assert seen == [
        ("GET", "/api/memory/system/status"),
        ("POST", "/api/agent/actions/proposal_1/decision"),
    ]

