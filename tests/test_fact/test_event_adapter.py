from types import SimpleNamespace

from memoryhub.core.fact.event_adapter import FactIngestionAdapter
from memoryhub.core.fact.models import FactAdmissionDecision, FactCandidate, RawTriple


class RecordingPipeline:
    def __init__(self):
        self.calls = []

    def propose(
        self,
        text,
        source_id="",
        project_id=None,
        scope_hint=None,
        metadata=None,
    ):
        self.calls.append({
            "text": text,
            "source_id": source_id,
            "project_id": project_id,
            "scope_hint": scope_hint,
            "metadata": metadata,
        })
        triple = RawTriple(
            subject_text="项目A",
            subject_type="Other",
            predicate_text="负责人",
            object_text="张三",
            object_type="Person",
            evidence=text,
            confidence=0.9,
        )
        return [FactCandidate(
            candidate_id=FactCandidate.make_id(),
            raw_triple=triple,
            admission=FactAdmissionDecision(
                is_fact=True,
                should_remember=True,
            ),
            source_id=source_id,
            project_id_hint=project_id,
            metadata=metadata or {},
        )]


def _call(call_id, tool_name, result, status="success", arguments=None):
    return SimpleNamespace(
        call_id=call_id,
        tool_name=tool_name,
        arguments=arguments or {},
        result=result,
        status=status,
        sequence=1,
        error="",
    )


def _event(text="", tool_calls=None, quality_status="review"):
    return SimpleNamespace(
        event_id="evt-001",
        source_type="tool_result",
        event_type="agent_response",
        session_id="session-1",
        turn_id="turn-1",
        scene="office",
        task_type="weekly_report",
        text=text,
        payload={"project_id": "project-a"},
        tool_calls=tool_calls or [],
        quality=SimpleNamespace(score=0.2, status=quality_status),
    )


def test_adapter_processes_text_and_successful_tool_results():
    pipeline = RecordingPipeline()
    adapter = FactIngestionAdapter(pipeline)
    event = _event(
        text="项目A负责人是张三",
        tool_calls=[
            _call(
                "call-1",
                "project_info",
                {"owner": "张三"},
                arguments={"project_id": "project-a"},
            ),
        ],
    )

    candidates = adapter.propose_from_event(event)

    assert len(candidates) == 2
    assert [call["source_id"] for call in pipeline.calls] == [
        "evt-001:text",
        "evt-001:call-1",
    ]
    assert all(call["project_id"] == "project-a" for call in pipeline.calls)
    assert "工具返回结果" in pipeline.calls[1]["text"]
    assert '"owner": "张三"' in pipeline.calls[1]["text"]


def test_adapter_ignores_quality_status_for_now():
    pipeline = RecordingPipeline()
    adapter = FactIngestionAdapter(pipeline)

    candidates = adapter.propose_from_event(
        _event(text="项目A负责人是张三", quality_status="rejected")
    )

    assert len(candidates) == 1
    assert candidates[0].metadata["quality_status"] == "rejected"


def test_adapter_skips_failed_or_empty_tool_results():
    pipeline = RecordingPipeline()
    adapter = FactIngestionAdapter(pipeline)
    event = _event(tool_calls=[
        _call("call-1", "project_info", {"owner": "张三"}, status="error"),
        _call("call-2", "project_info", None, status="success"),
        _call("call-3", "project_info", {"owner": "李四"}, status="partial"),
    ])

    candidates = adapter.propose_from_event(event)

    assert len(candidates) == 1
    assert pipeline.calls[0]["source_id"] == "evt-001:call-3"


def test_adapter_does_not_decide_scope():
    pipeline = RecordingPipeline()
    adapter = FactIngestionAdapter(pipeline)

    candidate = adapter.propose_from_event(
        _event(text="项目A负责人是张三")
    )[0]

    assert candidate.project_id_hint == "project-a"
    assert candidate.scope_hint is None
    assert candidate.admission.suggested_scope is None
