import json

from memoryhub_client import MemoryHubClient
from memoryhub_mcp.config import McpConfig
from memoryhub_mcp.tools import ToolRegistry


class FakeClient:
    # 复用真实实现构造检索 payload，避免假实现与契约漂移。
    build_search_payload = staticmethod(MemoryHubClient.build_search_payload)

    def health(self):
        return {"reachable": True}

    def search(self, payload):
        return {"results": [], "payload": payload}

    def get_context(self, payload):
        return {"context": "", "payload": payload}

    def remember(self, text, **kwargs):
        return {"text": text, **kwargs}

    def write_events(self, events):
        return {"accepted": len(events)}

    def forget_preview(self, payload):
        return {"preview": payload}

    def forget(self, payload):
        return {"forgotten": payload}

    def feedback(self, payload):
        return payload

    def propose_knowledge_fact(self, triples, **kwargs):
        return {"triples": triples, **kwargs}


def test_tool_surface_and_safe_forget():
    registry = ToolRegistry(FakeClient(), McpConfig(project_root="/tmp/project"))
    names = {item["name"] for item in registry.list()}
    assert names == {
        "memoryhub_health", "memoryhub_search", "memoryhub_get_context",
            "memoryhub_write_event", "memoryhub_remember", "memoryhub_forget",
            "memoryhub_feedback", "memoryhub_vnext_feedback",
            "memoryhub_resume_task", "memoryhub_knowledge_fact_propose",
    }
    result = json.loads(registry.call("memoryhub_forget", {"instruction": "old"}))
    assert "preview" in result


def test_search_payload_is_unscoped_unless_caller_narrows_it():
    """MCP 检索默认不带作用域，避免自我限定成 APPLICATION:memoryhub-mcp。

    ``context.app`` 在 legacy 契约里是作用域选择器；MCP 曾把它硬编码成自己的
    名字，导致所有由 CLI / 插件 / 桌面端写入的记忆（scope 为 TASK:...）被过滤掉。
    """
    registry = ToolRegistry(FakeClient(), McpConfig(user_id="lcz"))

    payload = json.loads(registry.call("memoryhub_search", {"query": "word"}))["payload"]
    assert payload["user_id"] == "lcz"
    assert payload["context"] == {"scene": "", "task_type": "", "app": ""}
    assert payload["project_id"] == ""

    narrowed = json.loads(
        registry.call(
            "memoryhub_search",
            {"query": "word", "scene": "code", "task_type": "coding_task"},
        )
    )["payload"]
    assert narrowed["context"] == {"scene": "code", "task_type": "coding_task", "app": ""}

