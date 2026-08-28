from types import SimpleNamespace

import pytest

from memoryhub.adapter.api import FactDecisionInput, _decide_fact_proposal
from memoryhub.config import FactConfig
from memoryhub.core.fact.models import FactAdmissionDecision, FactCandidate, RawTriple


def _proposal() -> FactCandidate:
    return FactCandidate(
        candidate_id="candidate_conflict_mode",
        raw_triple=RawTriple(
            subject_text="用户",
            subject_type="Person",
            predicate_text="所在城市",
            object_text="深圳",
            object_type="Location",
            evidence="用户所在城市是深圳",
            confidence=0.9,
        ),
        admission=FactAdmissionDecision(is_fact=True, should_remember=True),
        scope_hint="global",
    )


class _Store:
    def __init__(self, conflict_mode):
        self.conflict_mode = conflict_mode
        self.updated = None

    def get_fact_proposal(self, proposal_id, *, user_id):
        return {
            "candidate": _proposal(),
            "status": "proposed",
            "committed_fact_id": None,
            "conflict_decision_mode": self.conflict_mode,
        }

    def update_fact_proposal_status(self, proposal_id, **kwargs):
        self.updated = kwargs
        return True


class _Pipeline:
    def __init__(self, conflict_mode):
        self.store = _Store(conflict_mode)
        self.auto_resolve = None

    def commit(self, proposal, **kwargs):
        self.auto_resolve = kwargs["auto_resolve"]
        return SimpleNamespace(
            relation="CONFLICT",
            resolution="escalate",
            reason="test conflict",
            existing_fact=SimpleNamespace(
                fact_id="fact_old", object_value="北京",
                observed_at="2026-08-01T00:00:00Z", confidence=0.9,
            ),
            new_fact=SimpleNamespace(
                fact_id="fact_new", object_value="深圳",
                observed_at="2026-08-28T00:00:00Z", confidence=0.9,
            ),
        )


def test_conflict_mode_is_read_from_persisted_proposal():
    pipeline = _Pipeline("agent_autonomous")
    result = _decide_fact_proposal(
        pipeline,
        "alice",
        FactDecisionInput(proposal_id="candidate_conflict_mode", action="commit"),
    )

    assert pipeline.auto_resolve is True
    assert result["status"] == "awaiting_decision"
    assert result["decision_task"]["decision_type"] == "fact_conflict"
    assert result["conflict_decision_mode"] == "agent_autonomous"


def test_user_review_conflict_mode_stays_awaiting_decision():
    pipeline = _Pipeline("user_review")
    result = _decide_fact_proposal(
        pipeline,
        "alice",
        FactDecisionInput(proposal_id="candidate_conflict_mode", action="commit"),
    )

    assert pipeline.auto_resolve is False
    assert result["status"] == "awaiting_decision"


def test_fact_config_validates_conflict_mode():
    assert FactConfig(conflict_decision_mode="agent_autonomous").conflict_decision_mode == (
        "agent_autonomous"
    )
    with pytest.raises(ValueError):
        FactConfig(conflict_decision_mode="invalid")
