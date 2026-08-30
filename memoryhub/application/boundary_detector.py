"""Task boundary detector: hard triggers, rule scoring, model suggestion, debounce."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoryhub.domain.contracts import (
    BoundaryCheckpointType,
    BoundaryTriggerKind,
    EpisodeStatus,
)


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    """A non-mutable boundary decision produced by the detector."""

    checkpoint_type: BoundaryCheckpointType
    trigger_kind: BoundaryTriggerKind
    score: float
    reason: str
    debounce_key: str


class BoundaryDetector:
    """Detect task boundaries from events, working state and episode history.

    The detector never mutates episode state itself.  Callers use the returned
    ``BoundaryDecision`` to decide whether to create a snapshot, close an
    episode, or enqueue a reflection task.
    """

    _CONTEXT_PRESSURE_FIELDS = ("constraints", "pending_steps")
    _CONTEXT_PRESSURE_THRESHOLD = 8
    _DEBOUNCE_SECONDS = 5.0
    _TASK_START_EVENT_TYPES = frozenset({"task_start", "task_started", "user_instruction"})

    def __init__(
        self,
        *,
        context_pressure_threshold: int | None = None,
        debounce_seconds: float | None = None,
        model_suggester: Any | None = None,
    ) -> None:
        self.context_pressure_threshold = (
            context_pressure_threshold or self._CONTEXT_PRESSURE_THRESHOLD
        )
        self.debounce_seconds = (
            debounce_seconds if debounce_seconds is not None else self._DEBOUNCE_SECONDS
        )
        self._model_suggester = model_suggester
        # In-memory debounce map keyed by (tenant_id, user_id, task_id, checkpoint_type).
        self._recent: dict[tuple[str, str, str, str], float] = {}

    def detect(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        event_type: str,
        event_payload: dict[str, Any] | None = None,
        episode_status: EpisodeStatus | str = EpisodeStatus.ACTIVE,
        working_state: dict[str, Any] | None = None,
        episode_history: list[dict[str, Any]] | None = None,
        timestamp: float | None = None,
    ) -> BoundaryDecision | None:
        """Return a boundary decision or ``None`` when nothing should happen."""

        payload = event_payload or {}
        status = (
            episode_status
            if isinstance(episode_status, EpisodeStatus)
            else EpisodeStatus(episode_status)
        )

        decision = self._hard_trigger(event_type, payload, status)
        if decision is None:
            decision = self._rule_trigger(
                event_type=event_type,
                payload=payload,
                status=status,
                working_state=working_state or {},
                episode_history=episode_history or [],
            )
        if decision is None and self._model_suggester is not None:
            decision = self._model_suggestion(
                event_type=event_type,
                payload=payload,
                status=status,
                working_state=working_state or {},
                episode_history=episode_history or [],
            )

        if decision is None:
            return None

        if self._debounced(tenant_id, user_id, task_id, decision, timestamp):
            return None

        return decision

    def _hard_trigger(
        self,
        event_type: str,
        payload: dict[str, Any],
        status: EpisodeStatus,
    ) -> BoundaryDecision | None:
        """Explicit or terminal hard triggers always win."""

        explicit = str(payload.get("boundary", "")).strip().upper()
        normalized_event_type = event_type.strip().lower()
        if normalized_event_type in {"task_complete", "task_completed"}:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.COMPLETE,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason="event_type=task_complete",
                debounce_key=f"{event_type}:hard-complete",
            )
        if normalized_event_type in {"task_failed", "task_failure"}:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.FAILED,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason="event_type=task_failed",
                debounce_key=f"{event_type}:hard-failed",
            )
        if explicit in {"COMPLETE", "DONE", "FINISH"}:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.COMPLETE,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason="payload.boundary=complete",
                debounce_key=f"{event_type}:hard-complete",
            )
        if explicit in {"FAILED", "FAIL", "ERROR"}:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.FAILED,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason="payload.boundary=failed",
                debounce_key=f"{event_type}:hard-failed",
            )
        if explicit == "EXPLICIT":
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.EXPLICIT,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason="payload.boundary=explicit",
                debounce_key=f"{event_type}:hard-explicit",
            )

        # Writing into a terminal episode is a hard boundary violation: treat as
        # the same terminal checkpoint so callers can reject or re-open cleanly.
        if status in {EpisodeStatus.COMPLETED, EpisodeStatus.FAILED}:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.COMPLETE
                if status is EpisodeStatus.COMPLETED
                else BoundaryCheckpointType.FAILED,
                trigger_kind=BoundaryTriggerKind.HARD,
                score=1.0,
                reason=f"episode.status={status.value}",
                debounce_key=f"{event_type}:hard-terminal",
            )

        return None

    def _rule_trigger(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        status: EpisodeStatus,
        working_state: dict[str, Any],
        episode_history: list[dict[str, Any]],
    ) -> BoundaryDecision | None:
        """Rule-based scoring for phase changes and context pressure."""

        if status in {EpisodeStatus.COMPLETED, EpisodeStatus.FAILED}:
            return None

        if not episode_history and self._is_task_start(event_type, payload):
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.START,
                trigger_kind=BoundaryTriggerKind.RULE,
                score=0.7,
                reason="task_start_event",
                debounce_key=f"{event_type}:task-start",
            )

        phase = payload.get("phase")
        if phase is not None and episode_history:
            last_phase = episode_history[-1].get("phase")
            if last_phase is not None and str(phase) != str(last_phase):
                return BoundaryDecision(
                    checkpoint_type=BoundaryCheckpointType.PHASE,
                    trigger_kind=BoundaryTriggerKind.RULE,
                    score=0.6,
                    reason=f"phase_changed:{last_phase}->{phase}",
                    debounce_key=f"{event_type}:phase:{phase}",
                )

        pressure_score = self._context_pressure_score(working_state)
        if pressure_score >= 1.0:
            return BoundaryDecision(
                checkpoint_type=BoundaryCheckpointType.CONTEXT_PRESSURE,
                trigger_kind=BoundaryTriggerKind.RULE,
                score=min(0.9, 0.5 + 0.1 * pressure_score),
                reason="context_pressure_threshold_exceeded",
                debounce_key=f"{event_type}:context-pressure",
            )

        return None

    def _is_task_start(self, event_type: str, payload: dict[str, Any]) -> bool:
        if event_type.strip().lower() in self._TASK_START_EVENT_TYPES:
            return True
        return any(
            isinstance(payload.get(key), str) and payload[key].strip()
            for key in ("goal", "instruction", "current_goal")
        )

    def _model_suggestion(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        status: EpisodeStatus,
        working_state: dict[str, Any],
        episode_history: list[dict[str, Any]],
    ) -> BoundaryDecision | None:
        """Placeholder for an LLM-based boundary suggestion.

        B07 keeps this deterministic and local; remote model integration is a
        future batch concern.
        """

        return None

    def _context_pressure_score(self, working_state: dict[str, Any]) -> float:
        count = 0
        for field in self._CONTEXT_PRESSURE_FIELDS:
            value = working_state.get(field)
            if isinstance(value, list):
                count += len(value)
            elif isinstance(value, str):
                count += 1
        if count == 0:
            return 0.0
        return float(count) / float(self.context_pressure_threshold)

    def _debounced(
        self,
        tenant_id: str,
        user_id: str,
        task_id: str,
        decision: BoundaryDecision,
        timestamp: float | None,
    ) -> bool:
        now = timestamp if timestamp is not None else 0.0
        key = (tenant_id, user_id, task_id, decision.checkpoint_type.value)
        last = self._recent.get(key)
        if last is not None and (now - last) < self.debounce_seconds:
            return True
        self._recent[key] = now
        return False


__all__ = ["BoundaryDecision", "BoundaryDetector"]
