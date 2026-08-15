from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from memoryhub.adapter.schemas import (
    MemoryDecision,
    MemoryProvenance,
    MemoryWriteReceipt,
    SafetyAction,
    SourceType,
)
from memoryhub.storage.database import Database
from memoryhub.storage.models import MemoryEvidenceRow


def test_memory_write_contract_dtos_capture_action_and_provenance() -> None:
    provenance = MemoryProvenance(
        event_id="evt_1",
        source_hash="a" * 64,
        source_type=SourceType.USER_BEHAVIOR,
        safety_audit_id="audit_1",
        safety_action=SafetyAction.ALLOW,
    )

    receipt = MemoryWriteReceipt(
        memory_id="pref_1",
        memory_type="preference",
        action=MemoryDecision.REINFORCE,
        lineage_id="lin_1",
        evidence_ids=["evidence_1"],
        outbox_id="outbox_1",
        provenance=provenance,
    )

    assert receipt.action is MemoryDecision.REINFORCE
    assert receipt.provenance.safety_action is SafetyAction.ALLOW


def test_memory_write_contract_schema_is_created_idempotently(tmp_path) -> None:
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    db.init_schema()

    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    assert {
        "memory_lineage",
        "memory_evidence",
        "memory_projection_outbox",
    } <= table_names

    evidence_constraints = inspector.get_unique_constraints("memory_evidence")
    assert any(
        constraint["column_names"] == ["memory_id", "event_id", "source_hash"]
        for constraint in evidence_constraints
    )

    outbox_indexes = inspector.get_indexes("memory_projection_outbox")
    assert any(
        index["column_names"] == ["status", "next_retry_at"]
        for index in outbox_indexes
    )
    db.close()


def test_memory_evidence_rejects_duplicate_event_source_for_same_memory(tmp_path) -> None:
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()

    with db.session() as session:
        session.add(
            MemoryEvidenceRow(
                evidence_id="evidence_1",
                memory_id="pref_1",
                memory_type="preference",
                event_id="evt_1",
                source_hash="b" * 64,
                source_type=SourceType.USER_BEHAVIOR.value,
                excerpt="sanitized evidence",
            )
        )
        session.commit()

        session.add(
            MemoryEvidenceRow(
                evidence_id="evidence_2",
                memory_id="pref_1",
                memory_type="preference",
                event_id="evt_1",
                source_hash="b" * 64,
                source_type=SourceType.USER_BEHAVIOR.value,
                excerpt="same sanitized evidence",
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate evidence must violate the unique constraint")
    db.close()
