from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from memoryhub_qml.controller import MemoryHubController


class FakeApi(QObject):
    succeeded = Signal(str, str, object)
    failed = Signal(str, str, int, str)
    base_url = "http://127.0.0.1:8000"

    def __init__(self):
        super().__init__()
        self.calls = []

    def health(self):
        self.calls.append(("health", {}))
        return "health-token"

    def post(self, operation, path, payload):
        self.calls.append((operation, path, payload))
        return f"{operation}-token"


def test_controller_executes_step_and_advances(qtbot, tmp_path):
    replay = tmp_path / "replay.json"
    replay.write_text(
        '{"schema_version":"conversation-replay/1.0","session_id":"s","turns":['
        '{"turn_id":"t1","user_message":"记住中文","assistant_message":"好的"},'
        '{"turn_id":"t2","user_message":"怎么表达？","assistant_message":"使用中文"}]}',
        encoding="utf-8",
    )
    api = FakeApi()
    controller = MemoryHubController(api, replay)
    controller.start()
    api.succeeded.emit("health-token", "health", {"status": "ok"})
    assert controller.online

    controller.executeCurrent()
    _, path, payload = api.calls[-1]
    assert path == "/api/agent/step"
    assert payload["turn_id"] == "t1"
    api.succeeded.emit(
        "step-token",
        "step",
        {
            "candidate_memories": [
                {
                    "memory_id": "p1",
                    "memory_type": "preference",
                    "title": "中文",
                    "summary": "使用中文",
                    "relevance": 0.9,
                }
            ],
            "used_memory_ids": ["p1"],
            "tool_calls": [
                {
                    "call_id": "m1",
                    "tool_name": "memory_search",
                    "status": "success",
                    "sequence": 1,
                }
            ],
            "write_summary": ["写入 1 条偏好"],
            "fact_proposals": [],
            "retrieval_latency_ms": 12,
        },
    )
    assert controller.currentExecuted
    assert controller.memoryModel.count == 1
    assert controller.toolModel.count == 1
    assert controller.canGoNext
    controller.nextTurn()
    assert controller.currentIndex == 1


def test_controller_does_not_execute_when_backend_is_offline(qtbot, tmp_path):
    replay = tmp_path / "replay.json"
    replay.write_text('{"turns":[{"turn_id":"t1","user_message":"hi"}]}', encoding="utf-8")
    api = FakeApi()
    controller = MemoryHubController(api, replay)
    controller.loadDemo()
    before = len(api.calls)
    controller.executeCurrent()
    assert len(api.calls) == before
    assert "后端未连接" in controller.notice
