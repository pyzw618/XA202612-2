from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryEvent,
    QualityStatus,
    ToolCallResult,
    ToolCallStatus,
)
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.storage.database import Database, KnowledgeRepository


def _event(
    event_id: str,
    *,
    session: str = "s1",
    quality: float = 0.9,
    payload=None,
    tool_calls=None,
):
    calls = []
    for index, call in enumerate(tool_calls or [], start=1):
        calls.append(
            ToolCallResult(
                call_id=f"{event_id}-{index}",
                tool_name=call["tool_name"],
                status=ToolCallStatus(call["status"]),
                sequence=index,
            )
        )
    return MemoryEvent(
        event_id=event_id,
        source_type="tool_result" if calls else "user_behavior",
        user_id="u1",
        session_id=session,
        turn_id=event_id,
        task_type="report",
        event_type="task_trajectory",
        occurred_at="2026-08-04T08:00:00Z",
        text="safe",
        payload=payload
        or {
            "task_name": "report",
            "steps": ["collect", "write"],
            "status": "success",
            "result": "done",
        },
        tool_calls=calls,
        source_hash=hashlib.sha256(event_id.encode()).hexdigest(),
        quality=EventQuality(
            score=quality,
            status=QualityStatus.ACCEPTED,
            completeness=quality,
            validity=quality,
            consistency=quality,
            freshness=quality,
        ),
    )


def test_extractor_deduplicates_events_and_keeps_one_trajectory_group() -> None:
    extractor = KnowledgeExtractor()
    events = [
        _event("a"),
        _event("a", quality=0.4),
        _event("b"),
        _event("other", session="other"),
    ]
    items = extractor.extract_from_trajectory(events)
    assert items
    assert all({e.event_id for e in item.evidences} <= {"a", "b"} for item in items)


def test_confidence_falls_when_tool_chain_is_inconsistent() -> None:
    extractor = KnowledgeExtractor()
    strong = extractor.extract_case([_event("strong")])
    weak = extractor.extract_case(
        [
            _event(
                "weak",
                tool_calls=[
                    {"tool_name": "search", "status": "error"},
                    {"tool_name": "write", "status": "success"},
                ],
            )
        ]
    )
    assert strong is not None and weak is not None
    assert weak.confidence < strong.confidence


def test_knowledge_repository_preserves_previous_versions(tmp_path) -> None:
    db = Database(str(tmp_path / "knowledge.db"))
    db.init_schema()
    repo = KnowledgeRepository(db)
    first = KnowledgeMemory(
        memory_id="know-history",
        user_id="u1",
        knowledge_type=KnowledgeType.WORKFLOW,
        name="v1",
        content="first",
        version=1,
        evidences=[Evidence(event_id="e1", content="first")],
    )
    second = first.model_copy(deep=True)
    second.name = "v2"
    second.content = "second"
    second.version = 2
    second.evidences.append(Evidence(event_id="e2", content="second"))
    repo.save(first)
    repo.save(second)
    history = repo.get_version_history("know-history", user_id="u1")
    assert [item.version for item in history] == [1, 2]
    assert history[0].content == "first"
    assert history[-1].content == "second"
    db.close()

class _EnrichingLLM:
    def is_available(self):
        return True

    def generate_json(self, **kwargs):
        return {
            "goal": "monthly report",
            "steps": ["collect metrics", "write report"],
            "tools": ["report_writer"],
            "result": "report completed",
        }


def test_llm_fallback_enriches_sparse_trajectory():
    event = _event(
        "llm-enrich",
        payload={"task_name": "report", "steps": ["collect"], "status": "success"},
    )
    items = KnowledgeExtractor(llm_client=_EnrichingLLM()).extract_from_trajectory([event])
    assert items
    case = next(item for item in items if item.knowledge_type is KnowledgeType.CASE)
    assert case.steps == ["collect metrics", "write report"]
    assert "report completed" in case.content
    assert "report_writer" in case.tools


