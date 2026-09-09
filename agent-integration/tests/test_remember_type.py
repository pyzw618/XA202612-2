import httpx
import pytest

from memoryhub_client import MemoryHubClient, MemoryHubError


def test_remember_bare_knowledge_maps_to_fact():
    """裸 memory_type='knowledge' 自动按 fact 处理并写入 knowledge 路由。"""
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, json_body(request)))
        return httpx.Response(200, json={"ok": True}, request=request)

    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://memoryhub.test", transport=transport)
    with MemoryHubClient("http://memoryhub.test", client=http) as client:
        result = client.remember("周报负责人是李四", memory_type="knowledge")
    assert result == {"ok": True}
    assert seen[0][0] == "POST"
    assert seen[0][1] == "/api/memory/memories/knowledge"
    assert seen[0][2]["knowledge_type"] == "fact"


def test_remember_invalid_type_error_is_actionable():
    with httpx.Client(
        base_url="http://memoryhub.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    ) as http:
        with MemoryHubClient("http://memoryhub.test", client=http) as client:
            with pytest.raises(MemoryHubError) as excinfo:
                client.remember("text", memory_type="banana")
    message = str(excinfo.value)
    assert "banana" in message
    assert "knowledge" in message  # 报错信息列出可用值（含 knowledge 别名）


def json_body(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode("utf-8"))
