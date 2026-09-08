import json

from memoryhub_mcp.config import McpConfig
from memoryhub_mcp.tools import ToolRegistry


class FakeClient:
    def health(self):
        return {"reachable": True}

    @staticmethod
    def build_search_payload(**kwargs):
        return kwargs

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
            "memoryhub_decide_facts",
    }
    result = json.loads(registry.call("memoryhub_forget", {"instruction": "old"}))
    assert "preview" in result
