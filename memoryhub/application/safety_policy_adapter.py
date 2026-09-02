"""Bridge the legacy SafetyWriteGate to the vNext EventGateway policy contract.

The adapter converts a ``MemoryEventContract`` to the legacy ``MemoryEvent``,
runs it through the mandatory SafetyWriteGate, and maps the resulting action
back to a governed ``MemoryEventContract``.  Policy is therefore applied before
any vNext EventRow/IdempotencyRecord persistence, satisfying the S1 Gate
requirement that policy runs before durable writes, logs or async tasks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memoryhub.adapter.schemas import MemoryEvent, SafetyAction, SourceType, _deep_thaw_json
from memoryhub.core.safety.gate import SafetyWriteGate
from memoryhub.domain.contracts import MemoryEventContract


class SafetyPolicyAdapter:
    """Callable policy processor usable by ``EventGateway``.

    A missing safety gate falls back to ALLOW so the service can start in
    test/development fixtures, but production configuration is required to
    enforce real policy (see ``config.runtime.is_production``).
    """

    def __init__(self, safety_gate: SafetyWriteGate | None = None) -> None:
        self.safety_gate = safety_gate

    def __call__(self, event: MemoryEventContract) -> MemoryEventContract:
        if self.safety_gate is None:
            return event.model_copy(update={"policy_action": "ALLOW"})

        legacy_event = _to_legacy_memory_event(event)
        outcome = self.safety_gate.route(legacy_event)

        if outcome.action is SafetyAction.REJECT:
            return event.model_copy(update={"policy_action": "DROP"})
        if outcome.action is SafetyAction.REVIEW:
            return event.model_copy(update={"policy_action": "REVIEW"})

        approved = outcome.approved
        if approved is None:
            return event.model_copy(update={"policy_action": "DROP"})

        safe_event = approved.safe_event
        new_payload = _deep_thaw_json(dict(safe_event.payload))
        if safe_event.text:
            new_payload["text"] = safe_event.text
        if safe_event.redactions:
            new_payload["redactions"] = [str(r) for r in safe_event.redactions]

        policy_action = "ALLOW" if outcome.action is SafetyAction.ALLOW else "MASK"
        # Fail-closed: MASK must actually change the payload.
        if policy_action == "MASK" and new_payload == event.payload:
            policy_action = "DROP"

        return event.model_copy(
            update={
                "policy_action": policy_action,
                "payload": new_payload,
            }
        )


def _to_legacy_memory_event(event: MemoryEventContract) -> MemoryEvent:
    """Best-effort vNext → legacy event conversion for the safety gate."""
    occurred_at = event.occurred_at
    if isinstance(occurred_at, datetime):
        occurred_at = occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    source_type = event.source_type
    try:
        source_type = SourceType(source_type)
    except ValueError:
        source_type = SourceType.USER_BEHAVIOR

    payload = dict(event.payload)
    text = str(payload.pop("text", "") or "")

    scene = ""
    task_type = ""
    scope = payload.get("scope")
    if isinstance(scope, dict):
        scene = str(scope.get("scene", ""))
        task_type = str(scope.get("task_type", ""))

    quality = payload.get("quality", {})
    if not isinstance(quality, dict):
        quality = {}

    return MemoryEvent(
        event_id=event.event_id,
        source_type=source_type,
        event_type=event.event_type,
        user_id=event.user_id,
        session_id=event.session_id,
        turn_id=payload.get("turn_id", ""),
        scene=scene,
        task_type=task_type,
        occurred_at=occurred_at or "",
        text=text,
        payload=payload,
        tool_calls=payload.get("tool_calls", []),
        source_hash=event.source_hash,
        redactions=payload.get("redactions", []),
        quality=quality,
    )


def build_safety_policy(safety_gate: SafetyWriteGate | None = None) -> Any:
    """Factory returning a policy processor for ``EventGateway``.

    Keeps the legacy gate decoupled from vNext gateway construction.
    """
    return SafetyPolicyAdapter(safety_gate)


__all__ = ["SafetyPolicyAdapter", "build_safety_policy"]
