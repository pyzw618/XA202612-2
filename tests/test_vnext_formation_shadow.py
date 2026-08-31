from __future__ import annotations

from datetime import datetime, timezone

from memoryhub.application.formation_shadow import (
    DeterministicLegacyExtractionAdapter,
    FormationShadowService,
    InMemoryCandidateRepository,
    LegacyMemoryStub,
)
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.domain.contracts import (
    MemoryEventContract,
    MemoryScope,
)
from memoryhub.observability.trace_models import TraceSpanKind
from memoryhub.observability.trace_store import TraceStore


def _reflection_service() -> ReflectionService:
    return ReflectionService(model=DeterministicReflectionModel())


def _event(
    event_id: str,
    text: str,
    *,
    task_id: str = "task-shadow",
    source_type: str = "user_behavior",
    payload: dict | None = None,
    explicit_long_term: bool = False,
) -> MemoryEventContract:
    return MemoryEventContract(
        tenant_id="tenant-shadow",
        user_id="user-shadow",
        event_id=event_id,
        event_type="user_instruction",
        source_type=source_type,
        task_id=task_id,
        session_id="session-shadow",
        occurred_at=datetime.now(timezone.utc),
        payload=(payload or {"text": text, "explicit_long_term": explicit_long_term}),
        policy_action="ALLOW",
        source_hash=(event_id + "a" * 64)[:64],
        idempotency_key=f"idem-{event_id}",
        trace_id=f"trace-{event_id}",
    )


def test_shadow_runs_vnext_and_legacy_without_active_write() -> None:
    store = TraceStore()
    service = FormationShadowService(reflection_service=_reflection_service(), trace_store=store)
    event = _event("event-shadow-1", "This time use DOCX")

    report = service.compare_event(
        event,
        episode_id="episode-shadow-1",
        working_state={"current_step": "draft"},
    )

    assert report.event_id == "event-shadow-1"
    assert report.vnext_candidate["memory_type"] == "PREFERENCE"
    assert report.vnext_candidate["scope_level"] == MemoryScope.PROJECT.value
    assert report.legacy_results
    assert report.legacy_results[0]["scope_level"] == MemoryScope.GLOBAL.value


def test_shadow_flags_premature_legacy_promotion() -> None:
    service = FormationShadowService(reflection_service=_reflection_service())
    event = _event("event-shadow-2", "Use DOCX for all reports")

    report = service.compare_event(
        event,
        episode_id="episode-shadow-2",
    )

    assert report.premature_promotions, "legacy writes active while vNext reviews"
    assert not report.missed_promotions
    assert report.safe is False


def test_repeated_evidence_reduces_premature_promotion() -> None:
    service = FormationShadowService(reflection_service=_reflection_service())
    event1 = _event(
        "event-shadow-3a",
        "Project-A formal report must use DOCX.",
        task_id="task-shadow-3a",
    )
    event2 = _event(
        "event-shadow-3b",
        "Project-A formal report must use DOCX.",
        task_id="task-shadow-3b",
    )

    report1 = service.compare_event(
        event1,
        episode_id="episode-shadow-3a",
    )
    report2 = service.compare_event(
        event2,
        episode_id="episode-shadow-3b",
    )

    assert report1.vnext_decision["decision"] in {"REVIEW", "REJECT"}
    assert report2.vnext_decision["decision"] == "PROMOTE"
    assert not report2.premature_promotions
    assert not report2.missed_promotions
    assert report2.safe is True


def test_scope_and_type_mismatches_are_reported() -> None:
    service = FormationShadowService(reflection_service=_reflection_service())
    event = _event(
        "event-shadow-4",
        "Fix the report export by restarting the exporter.",
        source_type="tool_result",
        payload={"text": "Fix the report export by restarting the exporter.", "tool_trust": "high"},
    )

    report = service.compare_event(
        event,
        episode_id="episode-shadow-4",
    )

    assert report.vnext_candidate["memory_type"] == "PROCEDURAL"
    assert report.legacy_results[0]["memory_type"] == "PROCEDURAL"
    assert report.scope_mismatches, "legacy GLOBAL vs vNext TASK"


def test_trace_store_records_redacted_formation_chain() -> None:
    store = TraceStore()
    service = FormationShadowService(reflection_service=_reflection_service(), trace_store=store)
    event = _event("event-shadow-5", "Use Markdown")

    service.compare_event(
        event,
        episode_id="episode-shadow-5",
        working_state={"current_step": "draft"},
    )

    chain = store.formation_chain("event-shadow-5")
    assert chain
    kinds = {span.kind for span in chain}
    assert "EVENT" in kinds
    assert "WORKING" in kinds
    assert "EPISODE" in kinds
    assert "CANDIDATE" in kinds
    assert "CONSOLIDATION" in kinds
    assert "LEGACY" in kinds
    # No raw text should be stored in the trace.
    for span in chain:
        assert "text" not in span.hashes


def test_in_memory_candidate_repository_accumulates_frequency() -> None:
    repo = InMemoryCandidateRepository()
    view = repo.create(
        candidate_id="c-1",
        tenant_id="tenant",
        user_id="user",
        memory_type="PREFERENCE",
        normalized_key="preference:format:docx",
        claim={"format": "DOCX"},
        scope_level="PROJECT",
        scope="PROJECT:reporting",
        evidence_refs=["event-1"],
        supporting_episode_ids=["episode-1"],
    )
    assert view.frequency == 1
    updated = repo.add_evidence(
        tenant_id="tenant",
        user_id="user",
        candidate_id="c-1",
        event_id="event-2",
        episode_id="episode-2",
        is_independent=True,
    )
    assert updated.frequency == 2


def test_legacy_adapter_returns_global_stubs() -> None:
    adapter = DeterministicLegacyExtractionAdapter()
    event = _event("event-legacy-1", "Use DOCX")
    stubs = adapter.extract(event)
    assert len(stubs) == 1
    assert stubs[0].memory_type == "PREFERENCE"
    assert stubs[0].scope_level == MemoryScope.GLOBAL.value
    assert stubs[0].would_write_active is True


def test_custom_legacy_adapter_can_be_injected() -> None:
    class CustomAdapter:
        def extract(self, event: MemoryEventContract) -> list[LegacyMemoryStub]:
            return [
                LegacyMemoryStub(
                    memory_id="custom-1",
                    memory_type="EPISODIC",
                    normalized_key="custom:key",
                    scope_level="SESSION",
                    scope="SESSION:test",
                    would_write_active=False,
                )
            ]

    service = FormationShadowService(
        reflection_service=_reflection_service(),
        legacy_adapter=CustomAdapter(),
    )
    event = _event("event-shadow-6", "Use DOCX")
    report = service.compare_event(event, episode_id="episode-shadow-6")
    assert report.legacy_results[0]["memory_type"] == "EPISODIC"
    assert report.legacy_results[0]["scope_level"] == "SESSION"


def test_s2_gate_docx_forms_local_candidate_not_global() -> None:
    """S2 Gate: 'This time use DOCX' only forms a PROJECT Candidate, not GLOBAL."""
    service = FormationShadowService(reflection_service=_reflection_service())
    event = _event(
        "event-shadow-gate-docx",
        "This time please use DOCX for Project-A reports.",
    )
    report = service.compare_event(event, episode_id="episode-shadow-gate-docx")

    assert report.vnext_candidate["memory_type"] == "PREFERENCE"
    assert report.vnext_candidate["scope_level"] == MemoryScope.PROJECT.value
    assert report.vnext_decision["decision"] in {"REVIEW", "REJECT"}
    assert not report.vnext_candidate["scope_level"] == MemoryScope.GLOBAL.value


def test_s2_gate_repeated_evidence_promotes_with_reason_codes() -> None:
    """S2 Gate: multiple independent tasks with clear evidence promote and explain."""
    service = FormationShadowService(reflection_service=_reflection_service())
    event1 = _event(
        "event-shadow-gate-1",
        "Project-A formal report must use DOCX.",
        task_id="task-shadow-gate-1",
    )
    event2 = _event(
        "event-shadow-gate-2",
        "Project-A formal report must use DOCX.",
        task_id="task-shadow-gate-2",
    )

    report1 = service.compare_event(event1, episode_id="episode-shadow-gate-1")
    report2 = service.compare_event(event2, episode_id="episode-shadow-gate-2")

    assert report1.vnext_decision["decision"] in {"REVIEW", "REJECT"}
    assert report2.vnext_decision["decision"] == "PROMOTE"
    assert report2.vnext_decision["reasons"]
    assert report2.safe is True


def test_s2_gate_global_markdown_and_project_docx_coexist() -> None:
    """S2 Gate: GLOBAL Markdown and PROJECT DOCX coexist without overwrite."""
    store = TraceStore()
    service = FormationShadowService(reflection_service=_reflection_service(), trace_store=store)
    events = [
        _event(
            "event-shadow-gate-md",
            "I always use Markdown for reports.",
            payload={
                "text": "I always use Markdown for reports.",
                "explicit_long_term": True,
                "scope_level": "GLOBAL",
                "scope": "GLOBAL",
            },
        ),
        _event(
            "event-shadow-gate-docx-1",
            "Project-A formal report must use DOCX.",
            task_id="task-shadow-gate-docx-1",
            payload={
                "text": "Project-A formal report must use DOCX.",
                "explicit_long_term": True,
            },
        ),
        _event(
            "event-shadow-gate-docx-2",
            "Project-A formal report must use DOCX.",
            task_id="task-shadow-gate-docx-2",
            payload={
                "text": "Project-A formal report must use DOCX.",
                "explicit_long_term": True,
            },
        ),
    ]

    last_report = None
    for idx, event in enumerate(events, start=1):
        last_report = service.compare_event(
            event, episode_id=f"episode-shadow-gate-{idx}"
        )

    candidate_spans = [
        span for span in store.records if span.kind == TraceSpanKind.CANDIDATE
    ]
    scopes_by_key: dict[str, set[str]] = {}
    for span in candidate_spans:
        key = span.classification.get("normalized_key", "")
        scopes_by_key.setdefault(key, set()).add(span.classification.get("scope_level", ""))

    markdown_keys = [k for k in scopes_by_key if "format:markdown" in k]
    docx_keys = [k for k in scopes_by_key if "format:docx" in k]

    assert markdown_keys, "Markdown candidate should be recorded"
    assert any("GLOBAL" in scopes_by_key[k] for k in markdown_keys)
    assert docx_keys, "DOCX candidate should be recorded"
    assert any("PROJECT" in scopes_by_key[k] for k in docx_keys)
    assert last_report is not None
    assert last_report.vnext_decision["decision"] == "PROMOTE"
    assert last_report.vnext_candidate["scope_level"] == MemoryScope.PROJECT.value


def test_s2_gate_repair_forms_procedural_candidate() -> None:
    """S2 Gate: two successful repairs form a PROCEDURAL candidate under review."""
    service = FormationShadowService(reflection_service=_reflection_service())
    event1 = _event(
        "event-shadow-gate-proc-1",
        "Fix report export by restarting the exporter.",
        source_type="tool_result",
        payload={"text": "Fix report export by restarting the exporter.", "tool_trust": "high"},
        task_id="task-shadow-gate-proc-1",
    )
    event2 = _event(
        "event-shadow-gate-proc-2",
        "Fix report export by restarting the exporter.",
        source_type="tool_result",
        payload={"text": "Fix report export by restarting the exporter.", "tool_trust": "high"},
        task_id="task-shadow-gate-proc-2",
    )

    report1 = service.compare_event(event1, episode_id="episode-shadow-gate-proc-1")
    report2 = service.compare_event(event2, episode_id="episode-shadow-gate-proc-2")

    assert report1.vnext_candidate["memory_type"] == "PROCEDURAL"
    assert report2.vnext_candidate["memory_type"] == "PROCEDURAL"
    assert report2.vnext_decision["decision"] in {"REVIEW", "PROMOTE"}
    assert report2.vnext_decision["reasons"]


def test_s2_gate_decisions_are_explainable_by_reason_codes() -> None:
    """S2 Gate: every consolidation decision carries reason codes."""
    service = FormationShadowService(reflection_service=_reflection_service())
    for text in [
        "Project-A formal report must use DOCX.",
        "Fix report export by restarting the exporter.",
        "The active Python version is 3.11.",
    ]:
        report = service.compare_event(
            _event(f"event-shadow-gate-reason-{text[:10]}", text),
            episode_id=f"episode-shadow-gate-reason-{text[:10]}",
        )
        assert report.vnext_decision["reasons"]
