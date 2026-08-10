from memoryhub.core.fact.admission import FactAdmissionPolicy
from memoryhub.core.fact.models import RawTriple


def _triple(predicate="负责人", evidence="项目负责人是张三", confidence=0.9):
    return RawTriple(
        subject_text="项目A",
        subject_type="Other",
        predicate_text=predicate,
        object_text="张三",
        object_type="Person",
        evidence=evidence,
        confidence=confidence,
    )


def test_fact_without_scope_hint_leaves_scope_undecided():
    decision = FactAdmissionPolicy().evaluate(_triple())
    assert decision.is_fact is True
    assert decision.should_remember is True
    assert decision.suggested_scope is None


def test_project_id_is_only_a_hint_and_does_not_decide_scope():
    decision = FactAdmissionPolicy().evaluate(_triple(), project_id="project_a")
    assert decision.should_remember is True
    assert decision.suggested_scope is None


def test_explicit_scope_hint_is_preserved():
    decision = FactAdmissionPolicy().evaluate(
        _triple(), project_id="project_a", scope_hint="project"
    )
    assert decision.suggested_scope == "project"


def test_preference_is_rejected():
    decision = FactAdmissionPolicy().evaluate(
        _triple(predicate="格式偏好", evidence="用户喜欢表格格式")
    )
    assert decision.is_fact is False
    assert decision.should_remember is False
    assert decision.category == "preference"


def test_temporary_fact_is_not_remembered():
    decision = FactAdmissionPolicy().evaluate(
        _triple(evidence="这次项目负责人是张三")
    )
    assert decision.is_fact is True
    assert decision.should_remember is False


def test_project_scope_requires_project_id():
    decision = FactAdmissionPolicy().evaluate(
        _triple(), scope_hint="project"
    )
    assert decision.should_remember is True
    assert decision.suggested_scope is None
