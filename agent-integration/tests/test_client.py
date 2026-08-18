from pathlib import Path

import httpx

from memoryhub_client import MemoryHubClient
from memoryhub_client.config import ClientConfig


def test_project_defaults_to_git_root(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    config = ClientConfig.load(cwd=tmp_path)
    assert config.project == str(tmp_path)


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

