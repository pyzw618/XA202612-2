from types import SimpleNamespace

from memoryhub.core.fact.event_adapter import FactIngestionAdapter
from memoryhub.core.fact.models import (
    FactAdmissionDecision,
    FactCandidate,
    FactProposalStatus,
    RawTriple,
)
from memoryhub.core.fact.store import FactStore


def _candidate() -> FactCandidate:
    return FactCandidate(
        candidate_id="candidate_persisted",
        raw_triple=RawTriple(
            subject_text="用户",
            subject_type="Person",
            predicate_text="生日",
            object_text="6月6日",
            object_type="Date",
            evidence="用户生日是6月6日",
            confidence=0.9,
        ),
        admission=FactAdmissionDecision(
            is_fact=True,
            should_remember=True,
            suggested_scope="global",
            category="personal",
            confidence=0.9,
            reason="durable personal fact",
        ),
        source_id="turn-1",
        scope_hint="global",
        metadata={"user_id": "alice"},
    )


def test_fact_proposal_survives_restart_and_is_owner_scoped(tmp_path):
    path = tmp_path / "facts.db"
    first = FactStore(str(path))
    candidate = _candidate()
    first.save_fact_proposal(candidate, user_id="alice")
    first.update_fact_proposal_status(
        candidate.proposal_id,
        user_id="alice",
        status=FactProposalStatus.COMMITTED.value,
        committed_fact_id="fact_1",
    )
    first.close()

    reopened = FactStore(str(path))
    stored = reopened.get_fact_proposal(candidate.proposal_id, user_id="alice")
    assert stored is not None
    assert stored["status"] == FactProposalStatus.COMMITTED.value
    assert stored["committed_fact_id"] == "fact_1"
    assert reopened.get_fact_proposal(candidate.proposal_id, user_id="bob") is None
    reopened.close()


class _RecordingStore:
    def __init__(self):
        self.saved = []
        self.statuses = []

    def save_fact_proposal(self, proposal, **kwargs):
        self.saved.append((proposal, kwargs))

    def update_fact_proposal_status(self, proposal_id, **kwargs):
        self.statuses.append((proposal_id, kwargs))


class _RecordingPipeline:
    def __init__(self):
        self.store = _RecordingStore()
        self.propose_calls = []
        self.commit_calls = []

    def propose(self, text, **kwargs):
        self.propose_calls.append((text, kwargs))
        candidate = _candidate()
        candidate.metadata["user_id"] = "alice"
        return [candidate]

    def commit(self, proposal, **kwargs):
        self.commit_calls.append((proposal, kwargs))
        return SimpleNamespace(
            relation="NEW",
            resolution=None,
            existing_fact=None,
            new_fact=SimpleNamespace(fact_id="fact_new"),
        )


def _event():
    return SimpleNamespace(
        event_id="evt-1",
        user_id="alice",
        project_id=None,
        payload={},
        text="用户生日是6月6日",
        tool_calls=[],
        source_type="user_behavior",
        event_type="user_action",
        session_id="s1",
        turn_id="t1",
        scene="chat",
        task_type="chat",
        quality=None,
    )


def test_autonomous_event_uses_one_propose_and_commits_admitted_candidate():
    pipeline = _RecordingPipeline()
    adapter = FactIngestionAdapter(pipeline, decision_mode="agent_autonomous")

    outcome = adapter.ingest_event(_event())

    assert len(pipeline.propose_calls) == 1
    assert len(pipeline.commit_calls) == 1
    assert outcome.proposal_ids == ["candidate_persisted"]
    assert outcome.committed_fact_ids == ["fact_new"]
    assert outcome.awaiting_decision_ids == []
    assert pipeline.store.statuses[-1][1]["status"] == FactProposalStatus.COMMITTED.value
