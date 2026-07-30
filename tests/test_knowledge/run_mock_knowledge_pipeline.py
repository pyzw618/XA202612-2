"""用 mock 数据演示：原始事件 -> 清洗 -> 标准化 -> 质量评分 -> 知识提取。
不调用真实 LLM；MockLLM 只模拟结构化补全响应，便于离线检查完整链路。
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from typing import Any
from memoryhub.adapter.schemas import EventQuality, MemoryEvent, QualityStatus
from memoryhub.core.knowledge.extractor import KnowledgeExtractor

OUT = Path(__file__).with_name("mock_pipeline_result.json")

class MockLLM:
    def is_available(self) -> bool: return True
    def generate(self, prompt: str, system_prompt: str = "", **kwargs: Any):
        return type("Response", (), {"content": "生成周报", "model": "mock-llm"})()
    def generate_json(self, prompt: str, schema: dict, system_prompt: str = "") -> dict:
        return {"steps": ["收集数据", "整理结论", "生成周报"]}

def clean(raw: dict) -> dict:
    """模拟清洗：裁剪文本、去除空工具名、保留原始 payload。"""
    cleaned = dict(raw)
    cleaned["text"] = str(raw.get("text", "")).strip()
    payload = dict(raw.get("payload", {}))
    payload["steps"] = [str(x).strip() for x in payload.get("steps", []) if str(x).strip()]
    payload["tools"] = list(dict.fromkeys(str(x).strip() for x in payload.get("tools", []) if str(x).strip()))
    cleaned["payload"] = payload
    cleaned["quality"] = {"score": 0.0, "status": "accepted", "completeness": 0.0, "validity": 0.0, "consistency": 0.0, "freshness": 0.0, "issues": []}
    return cleaned

def normalize(cleaned: dict) -> MemoryEvent:
    """模拟标准化：生成 MemoryEvent，并把质量评分挂到标准事件上。"""
    return MemoryEvent.model_validate(cleaned)

def score(event: MemoryEvent) -> MemoryEvent:
    quality = EventQuality(score=0.95, status=QualityStatus.ACCEPTED, completeness=1.0, validity=1.0, consistency=0.95, freshness=0.9, issues=[])
    return event.model_copy(update={"quality": quality})

def main() -> None:
    raw_events = [{
        "event_id": "mock-evt-001", "source_type": "tool_result", "event_type": "task_trajectory",
        "user_id": "demo-user", "session_id": "demo-session", "turn_id": "turn-001",
        "scene": "office", "task_type": "office.weekly_report", "occurred_at": "2026-07-30T08:00:00Z",
        "text": "  生成周报  ", "payload": {"task_name": "生成周报", "steps": [" 收集数据 ", "整理结论", "生成周报", ""], "tools": ["file_search", "note_tool", "file_search"], "result": "周报已完成"},
        "tool_calls": [{"sequence": 1, "call_id": "call-001", "tool_name": "file_search", "arguments": {"query": "weekly data"}, "result": "data found", "status": "success"}], "schema_version": "1.1", "source_hash": "b" * 64, "redactions": []
    }]
    cleaned = [clean(item) for item in raw_events]
    normalized = [normalize(item) for item in cleaned]
    scored = [score(item) for item in normalized]
    knowledge = KnowledgeExtractor(llm_client=MockLLM()).extract_from_trajectory(scored)
    result = {"raw_events": raw_events, "cleaned_events": cleaned, "normalized_events": [e.model_dump(mode="json") for e in normalized], "scored_events": [e.model_dump(mode="json") for e in scored], "knowledge": [k.model_dump(mode="json") for k in knowledge]}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {OUT}")
    print("knowledge types:", [k.knowledge_type.value for k in knowledge])
    for k in knowledge: print(f"- {k.knowledge_type.value}: {k.name}; steps={k.steps}; tools={k.tools}")

if __name__ == "__main__": main()






