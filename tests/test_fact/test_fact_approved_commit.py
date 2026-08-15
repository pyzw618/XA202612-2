from __future__ import annotations

from types import SimpleNamespace

import pytest

from memoryhub.adapter.schemas import MemoryProvenance, SafetyAction, SourceType
from memoryhub.core.fact.admission import FactAdmissionPolicy
from memoryhub.core.fact.conflict import ConflictDetector
from memoryhub.core.fact.models import PredicateDef, RawTriple
from memoryhub.core.fact.pipeline import FactMemoryPipeline
from memoryhub.core.fact.store import FactStore


class _Extractor:
    def __init__(self, triple: RawTriple):
        self.triple = triple
        self.last_error = None

    def extract(self, _text: str, _source_id: str = "") -> list[RawTriple]:
        return [self.triple]


class _Normalizer:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def normalize(self, text: str, _entity_type=None) -> str:
        return self.mapping[text]


class _AllowingGate:
    def route(self, event):
        return SimpleNamespace(
            approved=SimpleNamespace(safe_event=event),
            audit_id="audit_fact_1",
            action=SafetyAction.MASK,
        )


class _BlockingGate:
    def route(self, _event):
        return SimpleNamespace(
            approved=None,
            audit_id="audit_fact_blocked",
            action=SafetyAction.REJECT,
        )


def _pipeline(*, safety_gate=None) -> FactMemoryPipeline:
    pipeline = FactMemoryPipeline.__new__(FactMemoryPipeline)
    pipeline.store = FactStore(":memory:")
    pipeline.store.upsert_predicate(
        PredicateDef(
            predicate_id="owner",
            canonical_name="负责人",
            aliases=["负责人"],
            single_value=True,
        )
    )
    pipeline.extractor = _Extractor(
        RawTriple(
            subject_text="项目A",
            subject_type="Other",
            predicate_text="负责人",
            object_text="张三",
            object_type="Person",
            evidence="项目A的负责人是张三",
            confidence=0.95,
        )
    )
    pipeline.entity_norm = _Normalizer(
        {"项目A": "entity:project:a", "张三": "entity:person:zhang"}
    )
    pipeline.pred_norm = _Normalizer({"负责人": "owner"})
    pipeline.detector = ConflictDetector(pipeline.store)
    pipeline.admission = FactAdmissionPolicy()
    pipeline.index_service = None
    pipeline.safety_gate = safety_gate
    return pipeline


def test_commit_routes_through_safety_and_persists_fact_evidence_provenance():
    pipeline = _pipeline(safety_gate=_AllowingGate())
    proposal = pipeline.propose(
        "项目A的负责人是张三",
        source_id="event-1",
        scope_hint="global",
        metadata={"event_id": "evt_1", "source_hash": "a" * 64},
    )[0]

    result = pipeline.commit(proposal, scope="global")

    evidence = pipeline.store.list_fact_evidence(result.new_fact.fact_id, "default")
    assert len(evidence) == 1
    assert evidence[0]["event_id"].startswith("fact_commit_")
    assert evidence[0]["source_hash"]
    assert evidence[0]["safety_audit_id"] == "audit_fact_1"
    assert evidence[0]["safety_action"] == "mask"


def test_commit_approved_requires_a_safety_audit_provenance():
    pipeline = _pipeline()
    proposal = pipeline.propose("项目A的负责人是张三", scope_hint="global")[0]

    with pytest.raises(ValueError, match="approval_provenance_required"):
        pipeline.commit_approved(
            proposal,
            scope="global",
            provenance=MemoryProvenance(
                event_id="evt_1",
                source_hash="b" * 64,
                source_type=SourceType.USER_BEHAVIOR,
            ),
        )


def test_blocked_fact_commit_has_no_normalization_or_persistence_side_effects():
    pipeline = _pipeline(safety_gate=_BlockingGate())
    proposal = pipeline.propose("项目A的负责人是张三", scope_hint="global")[0]

    with pytest.raises(ValueError, match="fact_commit.blocked:reject"):
        pipeline.commit(proposal, scope="global")

    assert pipeline.get_facts() == []
    assert pipeline.store._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0


def test_commit_unsafe_for_test_is_explicit_and_writes_unsafety_provenance():
    pipeline = _pipeline()
    proposal = pipeline.propose("项目A的负责人是张三", scope_hint="global")[0]

    result = pipeline.commit_unsafe_for_test(proposal, scope="global")

    evidence = pipeline.store.list_fact_evidence(result.new_fact.fact_id, "default")
    assert evidence[0]["safety_audit_id"] == ""
    assert evidence[0]["event_id"].startswith("fact_candidate_")
