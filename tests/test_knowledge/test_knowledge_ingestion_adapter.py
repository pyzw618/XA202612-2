import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus, SourceType


class StubLLMClient:
    def generate(self, prompt: str, system_prompt: str = "", **kwargs) -> object:
        return type("Resp", (), {"content": "工作流已生成", "model": "stub"})()

    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        return {"summary": "工作流已生成"}

    def is_available(self) -> bool:
        return True


def test_extract_from_trajectory_accepts_raw_ingestion_payloads() -> None:
    raw_event = {
        "event_id": "evt-001",
        "source_type": "tool_result",
        "event_type": "task_trajectory",
        "user_id": "u-1",
        "session_id": "s-1",
        "turn_id": "turn-1",
        "scene": "office",
        "task_type": "office.weekly_report",
        "occurred_at": "2026-07-30T00:00:00Z",
        "text": "生成周报",
        "payload": {
            "task_name": "周报生成",
            "steps": ["收集数据", "整理结论", "生成周报"],
            "tools": ["file_search", "note_tool"],
            "result": "完成周报",
        },
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": "a" * 64,
        "redactions": [],
        "quality": {
            "score": 0.9,
            "status": "accepted",
            "completeness": 1.0,
            "validity": 1.0,
            "consistency": 1.0,
            "freshness": 1.0,
            "issues": [],
        },
    }

    extractor = KnowledgeExtractor(llm_client=StubLLMClient())
    knowledge = extractor.extract_from_trajectory([raw_event])

    assert knowledge
    assert any(item.knowledge_type.value == "workflow" for item in knowledge)
    assert any(item.knowledge_type.value == "template" for item in knowledge)
