from __future__ import annotations

import hashlib

from memoryhub.adapter.schemas import (
    EventQuality,
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    MemoryDecision,
    MemoryEvent,
    QualityStatus,
    ToolCallResult,
    ToolCallStatus,
)
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from memoryhub.core.knowledge.updater import KnowledgeUpdater
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


# ─── LLM 冲突裁决测试 ─────────────────────────────────────────────────


def _db(tmp_path):
    db = Database(str(tmp_path / "llm_conflict_test.db"))
    db.init_schema()
    return db


class _MockWriteService:
    def __init__(self, know_repo):
        self.know_repo = know_repo

    def upsert_memory(self, memory, *, action=None, **_kwargs):
        self.know_repo.save(memory)
        return memory


class _JudgingLLM:
    """Mock LLM that returns a configurable judgment."""

    def __init__(self, judgment: str, *, merged_name: str = "", merged_steps: list | None = None):
        self._judgment = judgment
        self._merged_name = merged_name
        self._merged_steps = merged_steps
        self.call_count = 0

    def generate(self, prompt: str, system_prompt: str = "", **_kwargs):
        self.call_count += 1
        import json as _json

        data: dict = {"judgment": self._judgment, "reason": "mock"}
        if self._judgment == "concrete_conflict":
            data["merged_name"] = self._merged_name or "merged workflow"
            data["merged_content"] = "merged content"
            data["merged_steps"] = self._merged_steps or ["step A", "step B"]
            data["merged_tools"] = ["tool_a", "tool_b"]
        from memoryhub.llm.base import LLMResponse

        return LLMResponse(content=_json.dumps(data))


def _make_memory(memory_id: str, name: str, content: str, steps: list[str]) -> KnowledgeMemory:
    return KnowledgeMemory(
        memory_id=memory_id,
        user_id="u1",
        knowledge_type=KnowledgeType.WORKFLOW,
        name=name,
        content=content,
        steps=steps,
        tools=["tool_x"],
        confidence=0.9,
        total_count=2,
        success_count=2,
        evidences=[Evidence(event_id="e1", content="run 1")],
    )


def test_llm_judgment_equivalent_merges(tmp_path) -> None:
    db = _db(tmp_path)
    repo = KnowledgeRepository(db)
    writer = _MockWriteService(repo)

    old = _make_memory("k1", "Generate Report", "Collect data and write report", ["collect", "write"])
    repo.save(old)

    llm = _JudgingLLM("equivalent")
    updater = KnowledgeUpdater(write_service=writer, llm_client=llm)
    new = _make_memory("k2", "Generate Reports", "Collect data and write a report", ["collect data", "write report"])
    new.evidences = [Evidence(event_id="e2", content="run 2")]

    result_id = updater.add(new)
    # Should merge: result_id is old's id (since add uses _archive_and_save_version)
    stored_old = repo.get_by_id("k1")
    assert stored_old is not None
    assert stored_old.status.value == "archived"
    assert llm.call_count == 1
    db.close()


def test_llm_judgment_no_conflict_saves_separately(tmp_path) -> None:
    db = _db(tmp_path)
    repo = KnowledgeRepository(db)
    writer = _MockWriteService(repo)

    old = _make_memory("k1", "Deploy to server", "Push code to production server via git", ["git push origin main", "restart service"])
    repo.save(old)

    llm = _JudgingLLM("no_conflict")
    updater = KnowledgeUpdater(write_service=writer, llm_client=llm)
    new = _make_memory("k2", "Deploy to staging", "Push code to staging server via git", ["git push origin staging", "restart service"])

    result_id = updater.add(new)
    # Should be saved as NEW (not merged)
    assert repo.get_by_id("k2") is not None
    # Old should still be active
    stored_old = repo.get_by_id("k1")
    assert stored_old is not None
    assert stored_old.status.value == "active"
    assert llm.call_count == 1
    db.close()


def test_llm_judgment_concrete_conflict_merges_via_llm(tmp_path) -> None:
    db = _db(tmp_path)
    repo = KnowledgeRepository(db)
    writer = _MockWriteService(repo)

    old = _make_memory("k1", "CI/CD Build Pipeline", "Build and deploy the project to production server", ["npm run build", "deploy to production"])
    repo.save(old)

    llm = _JudgingLLM("concrete_conflict", merged_name="Unified Build Deploy", merged_steps=["npm run build", "deploy to production and staging"])
    updater = KnowledgeUpdater(write_service=writer, llm_client=llm)
    new = _make_memory("k2", "Release Build Pipeline", "Build and deploy the project to staging server", ["npm run build", "deploy to staging"])

    result_id = updater.add(new)
    # Old should be archived
    stored_old = repo.get_by_id("k1")
    assert stored_old is not None
    assert stored_old.status.value == "archived"
    # A merged successor should exist (id = k1_v2)
    merged = repo.get_by_id("k1_v2")
    assert merged is not None
    assert merged.name == "Unified Build Deploy"
    assert merged.steps == ["npm run build", "deploy to production and staging"]
    # LLM called twice: once for judgment, once for merge
    assert llm.call_count == 2
    db.close()


def test_llm_unavailable_falls_back_to_no_conflict(tmp_path) -> None:
    db = _db(tmp_path)
    repo = KnowledgeRepository(db)
    writer = _MockWriteService(repo)

    old = _make_memory("k1", "Process A", "Steps for process A", ["step1"])
    repo.save(old)

    updater = KnowledgeUpdater(write_service=writer, llm_client=None)
    new = _make_memory("k2", "Process B", "Steps for process B", ["step2"])

    # Similarity is low so it won't enter ambiguous zone → just saves as NEW
    result_id = updater.add(new)
    assert repo.get_by_id("k2") is not None
    db.close()


def test_llm_judgment_invalid_value_falls_back_to_no_conflict(tmp_path) -> None:
    db = _db(tmp_path)
    repo = KnowledgeRepository(db)
    writer = _MockWriteService(repo)

    old = _make_memory("k1", "Task Alpha", "Do X then Y", ["do X", "do Y"])
    repo.save(old)

    class _BadLLM:
        def generate(self, prompt, system_prompt="", **_kwargs):
            from memoryhub.llm.base import LLMResponse

            return LLMResponse(content='{"judgment": "invalid_value", "reason": "bad"}')

    updater = KnowledgeUpdater(write_service=writer, llm_client=_BadLLM())
    new = _make_memory("k2", "Task Alpha Modified", "Do X then Z", ["do X", "do Z"])

    result_id = updater.add(new)
    # Should save as NEW (invalid judgment treated as no_conflict)
    assert repo.get_by_id("k2") is not None
    db.close()


