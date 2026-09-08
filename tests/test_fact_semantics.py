from types import SimpleNamespace

from memoryhub.core.fact.conflict import FactConflictDetector
from memoryhub.core.fact.models import Entity, PredicateDef
from memoryhub.core.fact.normalizer import EntityNormalizer


class Repo:
    def __init__(self):
        self.entities = {}
        self.predicates = {}
        self.bindings = []

    def get_entity(self, entity_id, tenant_id="default", user_id="default"):
        item = self.entities.get(entity_id)
        return item if item and item.tenant_id == tenant_id and item.user_id == user_id else None

    def list_entities(self, tenant_id, user_id, entity_type=""):
        return [e for e in self.entities.values() if e.tenant_id == tenant_id and e.user_id == user_id and (not entity_type or entity_type == "Other" or e.entity_type == entity_type)]

    def find_entities(self, text, tenant_id, user_id, entity_type=""):
        return [e for e in self.list_entities(tenant_id, user_id, entity_type) if e.canonical_name.casefold() == text.casefold() or text.casefold() in [a.casefold() for a in e.aliases]]

    def entity_dict(self, e):
        return {"entity_id": e.entity_id, "canonical_name": e.canonical_name, "entity_type": e.entity_type, "aliases": e.aliases}

    def save_entity(self, e): self.entities[e.entity_id] = e
    def add_alias(self, entity_id, alias, tenant_id, user_id): self.entities[entity_id].aliases.append(alias)
    def get_predicate(self, pid): return self.predicates.get(pid)
    def list_predicates(self): return list(self.predicates.values())
    def find_predicates(self, text): return [p for p in self.predicates.values() if text.casefold() in [p.canonical_name.casefold(), *(a.casefold() for a in p.aliases)]]
    def save_predicate(self, p): self.predicates[p.predicate_id] = p
    def add_predicate_alias(self, pid, alias): self.predicates[pid].aliases.append(alias)
    def predicate_dict(self, p): return {"predicate_id": p.predicate_id, "canonical_name": p.canonical_name, "aliases": p.aliases}
    def list_bindings(self, user_id, tenant_id, scope): return [b for b in self.bindings if b.user_id == user_id and b.tenant_id == tenant_id and b.scope == scope and b.status == "active"]


def test_entity_alias_is_reused():
    repo = Repo()
    first = Entity("e1", "北京大学", "Organization", ["北京大学"], "u1", "t1")
    repo.save_entity(first)
    assert EntityNormalizer(repo).normalize("北京大学", "Organization", user_id="u1", tenant_id="t1") == "e1"


def test_inverse_relationship_has_one_canonical_key():
    repo = Repo()
    pred_a = PredicateDef("father_of", "父亲", inverse_of="son_of")
    pred_b = PredicateDef("son_of", "儿子", inverse_of="father_of", single_value=True)
    repo.save_predicate(pred_a)
    repo.save_predicate(pred_b)
    repo.bindings.append(SimpleNamespace(memory_id="m1", user_id="u1", tenant_id="t1", scope="global", subject_id="father", predicate_id="father_of", object_id="son", status="active"))
    result = FactConflictDetector(repo).check(user_id="u1", tenant_id="t1", scope="global", subject_id="son", predicate_id="son_of", object_id="father")
    assert result.relation == "DUPLICATE"


def test_mutually_exclusive_predicates_are_symmetric():
    repo = Repo()
    alive = PredicateDef("is_alive", "健在", exclusive_with=["is_deceased"])
    deceased = PredicateDef("is_deceased", "已故", exclusive_with=["is_alive"])
    repo.save_predicate(alive)
    repo.save_predicate(deceased)
    repo.bindings.append(SimpleNamespace(
        memory_id="m1", user_id="u1", tenant_id="t1", scope="global",
        subject_id="person", predicate_id="is_alive", object_id="yes", status="active",
    ))
    result = FactConflictDetector(repo).check(
        user_id="u1", tenant_id="t1", scope="global", subject_id="person",
        predicate_id="is_deceased", object_id="yes",
    )
    assert result.relation == "CONFLICT"
    assert "mutually_exclusive_predicate" in result.conflict_types


def test_entity_ids_are_tenant_scoped():
    first = Entity.make_id("Organization", "同名公司", "u1", "tenant-a")
    second = Entity.make_id("Organization", "同名公司", "u1", "tenant-b")
    assert first != second


def test_normalizer_prepare_mode_does_not_register_new_entity():
    repo = Repo()
    pending = []
    entity_id = EntityNormalizer(repo).normalize(
        "C++", "Software", user_id="u1", tenant_id="t1",
        persist=False, pending_operations=pending,
    )
    assert entity_id.startswith("entity:software:")
    assert repo.entities == {}
    assert pending and pending[0]["kind"] == "entity_create"


def test_force_new_allows_same_name_entities():
    repo = Repo()
    normalizer = EntityNormalizer(repo)
    first = normalizer.normalize(
        "同名项目", "Organization", user_id="u1", tenant_id="t1", force_new=True
    )
    second = normalizer.normalize(
        "同名项目", "Organization", user_id="u1", tenant_id="t1", force_new=True
    )
    assert first != second


def test_project_fact_same_key_is_independent_from_global():
    repo = Repo()
    predicate = PredicateDef("member_of", "成员属于", single_value=False)
    repo.save_predicate(predicate)
    repo.bindings.append(SimpleNamespace(
        memory_id="global-1", user_id="u1", tenant_id="t1", scope="global",
        subject_id="person", predicate_id="member_of", object_id="org", status="active",
    ))
    result = FactConflictDetector(repo).check(
        user_id="u1", tenant_id="t1", scope="project:p1",
        subject_id="person", predicate_id="member_of", object_id="org",
    )
    assert result.relation == "NEW"


def test_pending_entity_type_is_checked_without_persisting():
    repo = Repo()
    predicate = PredicateDef(
        "located_in", "所在地", domain=["Organization"], range=["Location"]
    )
    repo.save_predicate(predicate)
    result = FactConflictDetector(repo).check(
        user_id="u1", tenant_id="t1", scope="global",
        subject_id="new-subject", predicate_id="located_in", object_id="new-object",
        subject_type="Person", object_type="Location",
    )
    assert result.relation == "CONFLICT"
    assert "domain_type_violation" in result.conflict_types
