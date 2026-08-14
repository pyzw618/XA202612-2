"""Mandatory safety boundary for explicit preference and knowledge writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Generic, TypeVar

from memoryhub.adapter.schemas import (
    EventQuality,
    KnowledgeMemory,
    MemoryEvent,
    PreferenceMemory,
    QualityStatus,
    SafetyAction,
    SourceType,
    canonical_sha256,
)
from memoryhub.core.safety.gate import ApprovedWrite, SafetyGateError, SafetyWriteGate

Memory = PreferenceMemory | KnowledgeMemory
SinkResult = TypeVar("SinkResult")

_OPERATIONS = frozenset({"explicit_write", "feedback_update", "memory_sync"})


class MemoryWriteSafetyError(ValueError):
    """Stable failure raised when a safe memory projection cannot be produced."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class GuardedMemoryWriteResult(Generic[SinkResult]):
    """Result of routing one explicit memory mutation through the write gate."""

    action: SafetyAction
    audit_id: str
    memory: Memory | None = None
    sink_result: SinkResult | None = None


def _memory_class(memory: Memory):
    if isinstance(memory, KnowledgeMemory):
        return KnowledgeMemory
    if isinstance(memory, PreferenceMemory):
        return PreferenceMemory
    raise MemoryWriteSafetyError("memory_write.unsupported_type")


def _memory_envelope(
    memory: Memory, operation: str
) -> tuple[dict[str, Any], dict[str, str]]:
    if operation not in _OPERATIONS:
        raise MemoryWriteSafetyError("memory_write.invalid_operation")
    memory_class = _memory_class(memory)
    dumped = memory.model_dump(mode="json")
    identity = {
        "memory_id": str(dumped.pop("memory_id")),
        "memory_type": str(dumped.pop("memory_type")),
        "user_id": str(dumped.pop("user_id")),
    }
    expected_type = "knowledge" if memory_class is KnowledgeMemory else "preference"
    if identity["memory_type"] != expected_type or not identity["memory_id"]:
        raise MemoryWriteSafetyError("memory_write.invalid_identity")
    return (
        {
            "operation": operation,
            "memory_type": expected_type,
            "memory": dumped,
        },
        identity,
    )


def build_memory_write_event(
    memory: Memory, *, operation: str = "explicit_write"
) -> MemoryEvent:
    """Project every content-bearing memory field into one canonical gate event."""

    envelope, identity = _memory_envelope(memory, operation)
    source_hash = canonical_sha256(
        {
            "operation": operation,
            "memory_id": identity["memory_id"],
            "memory_type": identity["memory_type"],
            "user_id": identity["user_id"],
            "content": envelope["memory"],
        }
    )
    scope = memory.scope
    return MemoryEvent(
        event_id=f"memory_write_{source_hash[:24]}",
        source_type=SourceType.MANUAL_CONFIG,
        event_type="explicit_memory_write",
        user_id=identity["user_id"],
        scene=scope.scene,
        task_type=scope.task_type,
        occurred_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        payload=envelope,
        source_hash=source_hash,
        quality=EventQuality(
            score=1.0,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
        ),
    )


def _memory_from_approved(
    gate: SafetyWriteGate,
    approved: ApprovedWrite,
    *,
    memory_class,
    identity: dict[str, str],
    operation: str,
) -> Memory:
    verified = gate.verify_approved(approved)
    try:
        safe_event = verified.safe_event
        payload = safe_event.model_dump(mode="json")["payload"]
        if (
            safe_event.user_id != identity["user_id"]
            or payload["operation"] != operation
            or payload["memory_type"] != identity["memory_type"]
            or not isinstance(payload["memory"], dict)
        ):
            raise MemoryWriteSafetyError("memory_write.envelope_mismatch")
        safe_memory = dict(payload["memory"])
        safe_memory.update(identity)
        return memory_class.model_validate(safe_memory)
    except MemoryWriteSafetyError:
        raise
    except Exception:
        raise MemoryWriteSafetyError("memory_write.invalid_safe_projection") from None


def guard_memory_write(
    gate: SafetyWriteGate,
    memory: Memory,
    sink: Callable[[Memory], SinkResult],
    *,
    operation: str = "explicit_write",
) -> GuardedMemoryWriteResult[SinkResult]:
    """Audit and sanitize a memory, then invoke its sink with only the safe projection."""

    if not isinstance(gate, SafetyWriteGate):
        raise SafetyGateError("gate.service_unavailable")
    if not callable(sink):
        raise MemoryWriteSafetyError("memory_write.invalid_sink")
    memory_class = _memory_class(memory)
    _, identity = _memory_envelope(memory, operation)
    outcome = gate.route(build_memory_write_event(memory, operation=operation))
    if outcome.approved is None:
        return GuardedMemoryWriteResult(
            action=outcome.action,
            audit_id=outcome.audit_id,
        )

    safe_memory: Memory | None = None

    def guarded_sink(approved: ApprovedWrite) -> SinkResult:
        nonlocal safe_memory
        safe_memory = _memory_from_approved(
            gate,
            approved,
            memory_class=memory_class,
            identity=identity,
            operation=operation,
        )
        return sink(safe_memory)

    sink_result = gate.guarded_call(outcome.approved, guarded_sink)
    if safe_memory is None:
        raise MemoryWriteSafetyError("memory_write.safe_projection_missing")
    return GuardedMemoryWriteResult(
        action=outcome.action,
        audit_id=outcome.audit_id,
        memory=safe_memory,
        sink_result=sink_result,
    )
