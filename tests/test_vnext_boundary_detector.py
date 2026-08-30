from __future__ import annotations

import pytest

from memoryhub.application.boundary_detector import BoundaryDecision, BoundaryDetector
from memoryhub.domain.contracts import BoundaryCheckpointType, BoundaryTriggerKind, EpisodeStatus
from memoryhub.domain.episode import is_terminal_boundary


@pytest.fixture()
def detector() -> BoundaryDetector:
    return BoundaryDetector(debounce_seconds=0.0)


def test_hard_complete(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        event_payload={"boundary": "complete"},
    )
    assert isinstance(decision, BoundaryDecision)
    assert decision.checkpoint_type is BoundaryCheckpointType.COMPLETE
    assert decision.trigger_kind is BoundaryTriggerKind.HARD
    assert decision.score == 1.0
    assert is_terminal_boundary(decision.checkpoint_type.value)


def test_hard_failed(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        event_payload={"boundary": "failed"},
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.FAILED
    assert decision.trigger_kind is BoundaryTriggerKind.HARD


@pytest.mark.parametrize(
    ("event_type", "checkpoint_type"),
    [
        ("task_completed", BoundaryCheckpointType.COMPLETE),
        ("task_failed", BoundaryCheckpointType.FAILED),
    ],
)
def test_terminal_event_types_are_hard_boundaries(
    detector: BoundaryDetector,
    event_type: str,
    checkpoint_type: BoundaryCheckpointType,
) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type=event_type,
    )
    assert decision is not None
    assert decision.checkpoint_type is checkpoint_type
    assert decision.trigger_kind is BoundaryTriggerKind.HARD


def test_hard_explicit(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        event_payload={"boundary": "explicit"},
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.EXPLICIT
    assert decision.trigger_kind is BoundaryTriggerKind.HARD


def test_task_start_is_a_meaningful_rule_boundary(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="user_instruction",
        event_payload={"text": "Repair the reconnect flow"},
        episode_history=[],
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.START
    assert decision.trigger_kind is BoundaryTriggerKind.RULE


def test_terminal_status_is_hard_boundary(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        event_payload={"text": "anything"},
        episode_status=EpisodeStatus.COMPLETED,
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.COMPLETE
    assert decision.trigger_kind is BoundaryTriggerKind.HARD


def test_phase_change_produces_light_checkpoint(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="PHASE_CHANGED",
        event_payload={"phase": "review"},
        episode_history=[{"phase": "draft"}],
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.PHASE
    assert decision.trigger_kind is BoundaryTriggerKind.RULE
    assert not is_terminal_boundary(decision.checkpoint_type.value)


def test_short_phase_switch_does_not_close_task(detector: BoundaryDetector) -> None:
    # rapid back-and-forth phase switches should only produce light PHASE checkpoints
    for _ in range(3):
        decision = detector.detect(
            tenant_id="t",
            user_id="u",
            task_id="task",
            event_type="PHASE_CHANGED",
            event_payload={"phase": "review"},
            episode_history=[{"phase": "draft"}],
        )
        assert decision is None or decision.checkpoint_type is BoundaryCheckpointType.PHASE


def test_context_pressure_produces_light_checkpoint(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        working_state={
            "constraints": ["DOCX", "no tables", "formal", "project-a"],
            "pending_steps": ["a", "b", "c", "d", "e"],
        },
    )
    assert decision is not None
    assert decision.checkpoint_type is BoundaryCheckpointType.CONTEXT_PRESSURE
    assert decision.trigger_kind is BoundaryTriggerKind.RULE
    assert not is_terminal_boundary(decision.checkpoint_type.value)


def test_debounce_suppresses_duplicate_context_pressure(detector: BoundaryDetector) -> None:
    # Use a long debounce to make the suppression deterministic.
    detector.debounce_seconds = 60.0
    first = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        working_state={"constraints": ["c"] * 10},
        timestamp=0.0,
    )
    assert first is not None
    second = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        working_state={"constraints": ["c"] * 10},
        timestamp=1.0,
    )
    assert second is None


def test_no_boundary_for_normal_event(detector: BoundaryDetector) -> None:
    decision = detector.detect(
        tenant_id="t",
        user_id="u",
        task_id="task",
        event_type="USER_MESSAGE",
        event_payload={"text": "hello"},
        working_state={"pending_steps": ["one"]},
    )
    assert decision is None
