from memoryhub.core.fact.admission import FactAdmissionPolicy
from memoryhub.core.fact.conflict import ConflictDetector
from memoryhub.core.fact.models import PredicateDef, RawTriple
from memoryhub.core.fact.pipeline import FactMemoryPipeline
from memoryhub.core.fact.store import FactStore


class FakeExtractor:
    def __init__(self, triple):
        self.triple = triple

    def extract(self, text, source_id=""):
        return [self.triple]


class FakeNormalizer:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def normalize(self, text, entity_type=None):
        self.calls.append((text, entity_type))
        return self.mapping[text]


def _pipeline(triple):
    pipeline = FactMemoryPipeline.__new__(FactMemoryPipeline)
    pipeline.store = FactStore(":memory:")
    pipeline.store.upsert_predicate(PredicateDef(
        predicate_id="owner",
        canonical_name="负责人",
        aliases=["负责人"],
        single_value=True,
    ))
    pipeline.extractor = FakeExtractor(triple)
    pipeline.entity_norm = FakeNormalizer({
        "项目A": "entity:other:project_a",
        "张三": "entity:person:zhang",
    })
    pipeline.pred_norm = FakeNormalizer({"负责人": "owner"})
    pipeline.detector = ConflictDetector(pipeline.store)
    pipeline.admission = FactAdmissionPolicy()
    return pipeline


def _triple(evidence="项目负责人是张三"):
    return RawTriple(
        subject_text="项目A",
        subject_type="Other",
        predicate_text="负责人",
        object_text="张三",
        object_type="Person",
        evidence=evidence,
        confidence=0.95,
    )


def test_propose_does_not_write_fact():
    pipeline = _pipeline(_triple())
    entity_count_before = pipeline.store._conn.execute(
        "SELECT COUNT(*) FROM entities"
    ).fetchone()[0]
    predicate_count_before = pipeline.store._conn.execute(
        "SELECT COUNT(*) FROM predicates"
    ).fetchone()[0]

    proposals = pipeline.propose("项目负责人是张三", project_id="project_a")

    assert len(proposals) == 1
    assert proposals[0].project_id_hint == "project_a"
    assert proposals[0].admission.suggested_scope is None
    assert pipeline.get_facts() == []
    assert pipeline.entity_norm.calls == []
    assert pipeline.pred_norm.calls == []
    assert pipeline.store._conn.execute(
        "SELECT COUNT(*) FROM entities"
    ).fetchone()[0] == entity_count_before
    assert pipeline.store._conn.execute(
        "SELECT COUNT(*) FROM predicates"
    ).fetchone()[0] == predicate_count_before


def test_commit_writes_explicit_project_fact():
    pipeline = _pipeline(_triple())
    proposal = pipeline.propose(
        "项目负责人是张三", project_id="project_a"
    )[0]
    result = pipeline.commit(
        proposal, scope="project", project_id="project_a"
    )
    assert result.relation == "NEW"
    facts = pipeline.get_facts(scope="project", project_id="project_a")
    assert len(facts) == 1
    assert facts[0].project_id == "project_a"


def test_rejected_proposal_cannot_commit_without_force():
    pipeline = _pipeline(_triple("用户喜欢由张三负责"))
    proposal = pipeline.propose("用户喜欢由张三负责")[0]
    assert proposal.admission.should_remember is False

    try:
        pipeline.commit(proposal)
    except ValueError as exc:
        assert "未通过准入判断" in str(exc)
    else:
        raise AssertionError("拒绝的候选不应被直接提交")


def test_commit_requires_explicit_scope_for_pure_candidate():
    pipeline = _pipeline(_triple())
    proposal = pipeline.propose("项目负责人是张三")[0]

    try:
        pipeline.commit(proposal)
    except ValueError as exc:
        assert "明确指定 scope" in str(exc)
    else:
        raise AssertionError("未指定作用域的候选不应正式提交")
