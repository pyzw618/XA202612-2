import pytest

from memoryhub.core.fact.conflict import ConflictDetector
from memoryhub.core.fact.models import Fact, MemoryScope, PredicateDef
from memoryhub.core.fact.store import FactStore


def _fact(value, scope="global", project_id=None):
    return Fact(
        fact_id=Fact.make_id(),
        subject_id="entity:other:project",
        predicate_id="owner",
        object_id=f"entity:person:{value}",
        object_value=value,
        source_text=f"负责人是{value}",
        source_id="test",
        observed_at=Fact.now_iso(),
        confidence=0.9,
        scope=scope,
        project_id=project_id,
    )


@pytest.fixture
def scoped_store():
    store = FactStore(":memory:")
    store.upsert_predicate(PredicateDef(
        predicate_id="owner",
        canonical_name="负责人",
        aliases=["负责人"],
        single_value=True,
    ))
    return store


def test_project_fact_requires_project_id():
    with pytest.raises(ValueError):
        _fact("张三", scope=MemoryScope.PROJECT.value)


def test_global_fact_rejects_project_id():
    with pytest.raises(ValueError):
        _fact("张三", project_id="project_a")


def test_conflicts_are_isolated_by_scope(scoped_store):
    detector = ConflictDetector(scoped_store)
    scoped_store.insert_fact(_fact("张三"))

    project_fact = _fact(
        "李四", scope=MemoryScope.PROJECT.value, project_id="project_a"
    )
    assert detector.check(project_fact).relation == "NEW"


def test_projects_do_not_conflict_with_each_other(scoped_store):
    detector = ConflictDetector(scoped_store)
    scoped_store.insert_fact(
        _fact("张三", scope="project", project_id="project_a")
    )
    other_project = _fact("李四", scope="project", project_id="project_b")
    assert detector.check(other_project).relation == "NEW"


def test_same_project_still_conflicts(scoped_store):
    detector = ConflictDetector(scoped_store)
    scoped_store.insert_fact(
        _fact("张三", scope="project", project_id="project_a")
    )
    changed = _fact("李四", scope="project", project_id="project_a")
    assert detector.check(changed).relation == "CONFLICT"


def test_scope_columns_exist_after_store_initialization(scoped_store):
    columns = {
        row["name"]
        for row in scoped_store._conn.execute("PRAGMA table_info(facts)").fetchall()
    }
    assert {"memory_type", "scope", "project_id"} <= columns
