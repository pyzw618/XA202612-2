from __future__ import annotations

from memoryhub.domain.contracts import LongTermEnvelope, MemoryScope, MemoryType
from memoryhub.domain.long_term import (
    LongTermContentValidator,
)


def _envelope(
    *,
    memory_type: MemoryType,
    content: dict,
    evidence_refs: list[str] | None = None,
) -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id="tenant-a",
        user_id="user-a",
        memory_id="memory-1",
        memory_type=memory_type,
        normalized_key="test:key",
        content=content,
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:reporting",
        evolution_status="ACTIVE",
        confidence=0.9,
        utility=0.8,
        evidence_refs=evidence_refs if evidence_refs is not None else ["event-1"],
    )


def test_valid_preference_passes() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.PREFERENCE,
        content={"value": "Use DOCX", "payload": {"format": "DOCX"}},
    )
    result = validator.validate(envelope)
    assert result.ok is True
    assert result.issues == []


def test_preference_without_value_fails() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(memory_type=MemoryType.PREFERENCE, content={"_placeholder": ""})
    result = validator.validate(envelope)
    assert result.ok is False
    assert any(issue.code == "PREFERENCE_VALUE_MISSING" for issue in result.issues)


def test_valid_semantic_triple_passes() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.SEMANTIC,
        content={"subject": "Python", "predicate": "version", "object_value": "3.11"},
    )
    result = validator.validate(envelope)
    assert result.ok is True


def test_valid_semantic_statement_passes() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.SEMANTIC,
        content={"statement": "Python 3.11 is the active version"},
    )
    result = validator.validate(envelope)
    assert result.ok is True


def test_semantic_without_fact_fails() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.SEMANTIC,
        content={"subject": "Python"},
    )
    result = validator.validate(envelope)
    assert result.ok is False
    assert any(issue.code == "SEMANTIC_FACT_INCOMPLETE" for issue in result.issues)


def test_complete_procedure_passes() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.PROCEDURAL,
        content={
            "trigger": "report export fails",
            "preconditions": ["user has admin rights"],
            "steps": ["inspect log", "restart exporter", "verify output"],
            "verification": ["output file exists", "no errors in log"],
            "failure_recovery": [
                {"condition": "restart fails", "action": "rollback to last known good"}
            ],
        },
        evidence_refs=["event-1", "event-2"],
    )
    result = validator.validate(envelope)
    assert result.ok is True


def test_procedure_missing_fields_fails() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.PROCEDURAL,
        content={"steps": ["inspect log"]},
        evidence_refs=["event-1"],
    )
    result = validator.validate(envelope)
    assert result.ok is False
    codes = {issue.code for issue in result.issues}
    assert "PROCEDURE_TRIGGER_MISSING" in codes
    assert "PROCEDURE_PRECONDITIONS_MISSING" in codes
    assert "PROCEDURE_VERIFICATION_MISSING" in codes
    assert "PROCEDURE_FAILURE_RECOVERY_MISSING" in codes
    assert "PROCEDURE_INSUFFICIENT_EVIDENCE" in codes


def test_procedure_from_failed_episode_fails() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.PROCEDURAL,
        content={
            "trigger": "report export fails",
            "preconditions": ["user has admin rights"],
            "steps": ["inspect log"],
            "verification": ["output file exists"],
            "failure_recovery": [{"condition": "all fails", "action": "escalate"}],
            "outcome": "failed",
        },
        evidence_refs=["event-1", "event-2"],
    )
    result = validator.validate(envelope)
    assert result.ok is False
    assert any(issue.code == "PROCEDURE_FROM_FAILED_EPISODE" for issue in result.issues)


def test_procedure_needs_conditional_recovery() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.PROCEDURAL,
        content={
            "trigger": "report export fails",
            "preconditions": ["user has admin rights"],
            "steps": ["inspect log"],
            "verification": ["output file exists"],
            "failure_recovery": ["call support"],
        },
        evidence_refs=["event-1", "event-2"],
    )
    result = validator.validate(envelope)
    assert result.ok is False
    assert any(issue.code == "PROCEDURE_FAILURE_RECOVERY_INCOMPLETE" for issue in result.issues)


def test_valid_episodic_passes() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.EPISODIC,
        content={"content": "Recovered the report after exporter restart"},
    )
    result = validator.validate(envelope)
    assert result.ok is True


def test_episodic_without_content_or_refs_fails() -> None:
    validator = LongTermContentValidator()
    envelope = _envelope(
        memory_type=MemoryType.EPISODIC,
        content={"_placeholder": ""},
        evidence_refs=["event-1"],
    )
    result = validator.validate(envelope)
    assert result.ok is False
    assert any(issue.code == "EPISODIC_CONTENT_MISSING" for issue in result.issues)
