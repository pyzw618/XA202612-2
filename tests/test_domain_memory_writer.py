from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    MemoryDecision,
    MemoryProvenance,
    PreferenceMemory,
    SourceType,
)
from memoryhub.core.domain_writer import DomainMemoryWriter
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.core.preference.updater import PreferenceUpdater
from memoryhub.core.safety import SensitiveDetector
from memoryhub.core.safety.audit_log import SafetyAuditLog
from memoryhub.core.safety.gate import SafetyWriteGate
from memoryhub.core.safety.quarantine import ReviewQuarantineStore
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.memory_metadata import MemoryProjectionOutboxRepository
from memoryhub.storage.models import (
    KnowledgeRow,
    MemoryEvidenceRow,
    MemoryLineageRow,
    MemoryProjectionOutboxRow,
    PreferenceRow,
)


def _writer(tmp_path, *, outbox_repo=None):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    return db, DomainMemoryWriter(
        db=db,
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
        outbox_repo=outbox_repo,
    )


@pytest.mark.parametrize(
    ("memory", "action"),
    [
        (PreferenceMemory(user_id="u1", text="Prefer concise reports"), MemoryDecision.NEW),
        (
            KnowledgeMemory(
                user_id="u1",
                name="Weekly report workflow",
                content="Gather updates and draft a concise report.",
            ),
            MemoryDecision.NEW,
        ),
    ],
)
def test_domain_writer_persists_memory_lineage_evidence_and_outbox_atomically(
    tmp_path, memory, action
):
    db, writer = _writer(tmp_path)
    memory.evidences = [
        Evidence(
            event_id="evt_1",
            content="sanitized source excerpt",
            source_type=SourceType.USER_BEHAVIOR,
            timestamp=datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
    ]
    provenance = MemoryProvenance(
        event_id="evt_1",
        source_hash="a" * 64,
        source_type=SourceType.USER_BEHAVIOR,
        safety_audit_id="audit_1",
    )

    receipt = writer.write(memory, action=action, provenance=provenance)

    with db.session() as session:
        if memory.memory_type == "preference":
            assert session.get(PreferenceRow, memory.memory_id) is not None
        else:
            assert session.get(KnowledgeRow, memory.memory_id) is not None
        lineage = session.get(MemoryLineageRow, receipt.lineage_id)
        evidence = session.get(MemoryEvidenceRow, receipt.evidence_ids[0])
        outbox = session.get(MemoryProjectionOutboxRow, receipt.outbox_id)

        assert lineage.root_memory_id == memory.memory_id
        assert lineage.transition_action == action.value
        assert evidence.safety_audit_id == "audit_1"
        assert evidence.source_hash == "a" * 64
        assert outbox.operation == "upsert"
        assert outbox.status == "pending"
    db.close()


def test_domain_writer_deduplicates_same_memory_event_source_evidence(tmp_path):
    db, writer = _writer(tmp_path)
    memory = PreferenceMemory(user_id="u1", text="Use markdown")
    memory.evidences = [
        Evidence(
            event_id="evt_1",
            content="sanitized source excerpt",
            source_type=SourceType.USER_BEHAVIOR,
        )
    ]
    provenance = MemoryProvenance(
        event_id="evt_1",
        source_hash="b" * 64,
        source_type=SourceType.USER_BEHAVIOR,
    )

    first = writer.write(memory, action=MemoryDecision.NEW, provenance=provenance)
    second = writer.write(memory, action=MemoryDecision.REINFORCE, provenance=provenance)

    with db.session() as session:
        evidence_rows = session.query(MemoryEvidenceRow).all()
        lineage_rows = session.query(MemoryLineageRow).all()
        assert len(evidence_rows) == 1
        assert first.evidence_ids == second.evidence_ids
        assert len(lineage_rows) == 2
        assert lineage_rows[-1].evidence_revision == 2
    db.close()


class _FailingOutboxRepository(MemoryProjectionOutboxRepository):
    def enqueue(self, **_kwargs):
        raise RuntimeError("outbox.enqueue_failed")


def test_domain_writer_rolls_back_memory_lineage_and_evidence_when_outbox_fails(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    writer = DomainMemoryWriter(
        db=db,
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
        outbox_repo=_FailingOutboxRepository(db),
    )
    memory = PreferenceMemory(user_id="u1", text="This write must roll back")

    with pytest.raises(RuntimeError, match="outbox.enqueue_failed"):
        writer.write(memory, action=MemoryDecision.NEW)

    with db.session() as session:
        assert session.get(PreferenceRow, memory.memory_id) is None
        assert session.query(MemoryLineageRow).count() == 0
        assert session.query(MemoryEvidenceRow).count() == 0
        assert session.query(MemoryProjectionOutboxRow).count() == 0
    db.close()


def test_memory_write_service_uses_domain_writer_for_preference_writes(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=KnowledgeRepository(db),
    )
    memory = PreferenceMemory(user_id="u1", text="Use markdown headings")

    receipt = writer.upsert_memory(memory)

    assert receipt is not None
    assert receipt.action is MemoryDecision.NEW
    with db.session() as session:
        assert session.get(PreferenceRow, memory.memory_id) is not None
        assert session.get(MemoryLineageRow, receipt.lineage_id) is not None
        assert session.get(MemoryProjectionOutboxRow, receipt.outbox_id) is not None
    db.close()


def _evidence(event_id: str) -> Evidence:
    return Evidence(
        event_id=event_id,
        content=f"sanitized excerpt for {event_id}",
        source_type=SourceType.USER_BEHAVIOR,
    )


def test_preference_updater_emits_explicit_reinforce_and_supersede_actions(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    service = MemoryWriteService(pref_repo=pref_repo, know_repo=KnowledgeRepository(db))
    updater = PreferenceUpdater(pref_repo=pref_repo, write_service=service)

    original = PreferenceMemory(
        user_id="u1",
        text="Keep reports concise",
        payload={"target": "report_style", "value": "concise"},
        evidences=[_evidence("evt_pref_1")],
    )
    updater.add(original)
    updater.add(
        PreferenceMemory(
            user_id="u1",
            text="Keep reports concise",
            payload={"target": "report_style", "value": "concise"},
            evidences=[_evidence("evt_pref_2")],
        )
    )
    successor = PreferenceMemory(
        user_id="u1",
        text="Make reports detailed",
        payload={"target": "report_style", "value": "detailed"},
        extract_source="explicit_feedback",
        evidences=[_evidence("evt_pref_3")],
    )
    updater.add(successor)

    with db.session() as session:
        original_actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == original.memory_id)
            .order_by(MemoryLineageRow.evidence_revision.asc())
            .all()
        ]
        successor_actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == successor.memory_id)
            .all()
        ]

    assert original_actions == ["new", "reinforce", "supersede"]
    assert successor_actions == ["supersede"]
    db.close()


def test_knowledge_updater_emits_explicit_reinforce_and_revise_actions(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    service = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
    )
    updater = KnowledgeUpdater(write_service=service)
    original = KnowledgeMemory(
        user_id="u1",
        name="Weekly report workflow",
        content="Collect updates and publish a concise report.",
        steps=["Collect updates", "Publish report"],
        evidences=[_evidence("evt_know_1")],
    )
    updater.add(original)
    updater.add(
        original.model_copy(
            update={"evidences": [_evidence("evt_know_2")]},
            deep=True,
        )
    )
    updater.add(
        original.model_copy(
            update={
                "content": "Collect updates, verify them, and publish a concise report.",
                "steps": ["Collect updates", "Verify updates", "Publish report"],
                "evidences": [_evidence("evt_know_3")],
            },
            deep=True,
        )
    )

    successor_id = f"{original.memory_id}_v3"
    with db.session() as session:
        original_actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == original.memory_id)
            .order_by(MemoryLineageRow.evidence_revision.asc())
            .all()
        ]
        successor_actions = [
            row.transition_action
            for row in session.query(MemoryLineageRow)
            .filter(MemoryLineageRow.memory_id == successor_id)
            .all()
        ]

    assert original_actions == ["new", "reinforce", "revise"]
    assert successor_actions == ["revise"]
    db.close()


def _allow_gate(tmp_path):
    return SafetyWriteGate(
        SensitiveDetector(),
        SafetyAuditLog(tmp_path / "audit", fingerprint_key=b"a" * 32),
        quarantine=ReviewQuarantineStore(
            tmp_path / "review",
            encryption_key=b"q" * 32,
        ),
    )


def test_gated_upsert_memory_returns_write_receipt(tmp_path):
    """R8: the production safety-gated path must surface the MemoryWriteReceipt."""
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    service = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        safety_gate=_allow_gate(tmp_path),
        require_safety=True,
        project_immediately=False,
    )
    memory = PreferenceMemory(
        user_id="u1",
        text="Prefer concise reports",
        status="active",
    )
    receipt = service.upsert_memory(memory, action=MemoryDecision.NEW)
    assert receipt is not None
    assert receipt.receipt_id
    assert receipt.memory_id == memory.memory_id
    assert receipt.action == MemoryDecision.NEW
    db.close()
