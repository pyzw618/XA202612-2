"""
测试 conflict.py — 冲突检测四种关系: NEW / DUPLICATE / CONFLICT / COEXIST
"""

import pytest

from memoryhub.core.fact.conflict import ConflictDetector
from memoryhub.core.fact.models import Fact, PredicateDef
from memoryhub.core.fact.store import FactStore


def _make_fact(subject_id="entity:org:bytd", predicate_id="headquarters_location",
               object_id="entity:loc:shenzhen", object_value="深圳", **kwargs):
    return Fact(
        fact_id=Fact.make_id(),
        subject_id=subject_id,
        predicate_id=predicate_id,
        object_id=object_id,
        object_value=object_value,
        source_text="测试文本",
        source_id="test",
        observed_at=Fact.now_iso(),
        confidence=0.9,
        **kwargs,
    )


@pytest.fixture
def store_with_predicates():
    store = FactStore(":memory:")
    # 写入谓词
    store.upsert_predicate(PredicateDef(
        predicate_id="headquarters_location",
        canonical_name="总部所在地",
        aliases=["总部位于", "总部在"],
        domain=["Organization"],
        range=["Location"],
        single_value=True,
    ))
    store.upsert_predicate(PredicateDef(
        predicate_id="founder",
        canonical_name="创始人",
        aliases=["创始人是"],
        domain=["Organization"],
        range=["Person"],
        single_value=False,  # 多值
    ))
    store.upsert_predicate(PredicateDef(
        predicate_id="founding_date",
        canonical_name="成立时间",
        aliases=["成立于"],
        domain=["Organization"],
        range=["Date"],
        single_value=True,
    ))
    return store


class TestConflictDetector:
    def test_new_fact(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)
        fact = _make_fact()
        result = detector.check(fact)
        assert result.relation == "NEW"
        assert result.existing_fact is None

    def test_duplicate(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)

        # 先写入一条
        fact1 = _make_fact()
        store_with_predicates.insert_fact(fact1)

        # 相同 S+P+O
        fact2 = _make_fact()
        result = detector.check(fact2)
        assert result.relation == "DUPLICATE"
        assert result.existing_fact is not None

    def test_conflict_single_value(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)

        # 已有：总部在深圳
        fact1 = _make_fact(object_id="entity:loc:shenzhen", object_value="深圳")
        store_with_predicates.insert_fact(fact1)

        # 新：总部在北京（单值谓词 → 冲突）
        fact2 = _make_fact(object_id="entity:loc:beijing", object_value="北京")
        result = detector.check(fact2)
        assert result.relation == "CONFLICT"

    def test_coexist_multi_value(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)

        # 已有：创始人是王传福
        fact1 = _make_fact(
            subject_id="entity:org:byd",
            predicate_id="founder",
            object_id="entity:person:wang",
            object_value="王传福",
        )
        store_with_predicates.insert_fact(fact1)

        # 新：创始人是吕向阳（多值谓词 → 共存）
        fact2 = _make_fact(
            subject_id="entity:org:byd",
            predicate_id="founder",
            object_id="entity:person:lv",
            object_value="吕向阳",
        )
        result = detector.check(fact2)
        assert result.relation == "COEXIST"

    def test_duplicate_multi_value(self, store_with_predicates):
        """多值谓词下完全相同的值仍判 DUPLICATE"""
        detector = ConflictDetector(store_with_predicates)

        fact1 = _make_fact(
            subject_id="entity:org:byd",
            predicate_id="founder",
            object_id="entity:person:wang",
            object_value="王传福",
        )
        store_with_predicates.insert_fact(fact1)

        fact2 = _make_fact(
            subject_id="entity:org:byd",
            predicate_id="founder",
            object_id="entity:person:wang",
            object_value="王传福",
        )
        result = detector.check(fact2)
        assert result.relation == "DUPLICATE"

    def test_different_predicate_no_conflict(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)

        # 总部在深圳
        fact1 = _make_fact(
            predicate_id="headquarters_location",
            object_id="entity:loc:shenzhen", object_value="深圳",
        )
        store_with_predicates.insert_fact(fact1)

        # 成立时间 1995（不同谓词 → NEW）
        fact2 = _make_fact(
            predicate_id="founding_date",
            object_id="entity:date:1995", object_value="1995年",
        )
        result = detector.check(fact2)
        assert result.relation == "NEW"

    def test_different_subject_no_conflict(self, store_with_predicates):
        detector = ConflictDetector(store_with_predicates)

        # 比亚迪总部在深圳
        fact1 = _make_fact(
            subject_id="entity:org:byd",
            object_id="entity:loc:shenzhen", object_value="深圳",
        )
        store_with_predicates.insert_fact(fact1)

        # 华为总部在深圳（不同主体 → NEW）
        fact2 = _make_fact(
            subject_id="entity:org:huawei",
            object_id="entity:loc:shenzhen", object_value="深圳",
        )
        result = detector.check(fact2)
        assert result.relation == "NEW"

    def test_multiple_existing_conflicting(self, store_with_predicates):
        """多个已有 fact 都不同 → 仍判 CONFLICT"""
        detector = ConflictDetector(store_with_predicates)

        # 已有两个冲突项（模拟之前的冲突没处理）
        f1 = _make_fact(object_id="entity:loc:shenzhen", object_value="深圳")
        f2 = _make_fact(object_id="entity:loc:beijing", object_value="北京", status="disputed")
        store_with_predicates.insert_fact(f1)
        store_with_predicates.insert_fact(f2)

        # 新值上海 → 仍冲突
        f3 = _make_fact(object_id="entity:loc:shanghai", object_value="上海")
        result = detector.check(f3)
        assert result.relation == "CONFLICT"

    def test_inverse_relation_is_duplicate(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="father_of", canonical_name="父亲是",
            inverse_of="son_of", single_value=False,
            object_single_value=True, irreflexive=True,
        ))
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="son_of", canonical_name="儿子是",
            inverse_of="father_of", single_value=True, irreflexive=True,
        ))
        old = _make_fact(
            subject_id="entity:person:a", predicate_id="son_of",
            object_id="entity:person:b", object_value="B",
        )
        store_with_predicates.insert_fact(old)

        new = _make_fact(
            subject_id="entity:person:b", predicate_id="father_of",
            object_id="entity:person:a", object_value="A",
        )
        result = ConflictDetector(store_with_predicates).check(new)
        assert result.relation == "DUPLICATE"
        assert result.conflict_type == "inverse_equivalent"

    def test_inverse_cardinality_conflict(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="father_of", canonical_name="父亲是",
            inverse_of="son_of", single_value=False,
            object_single_value=True,
        ))
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="son_of", canonical_name="儿子是",
            inverse_of="father_of", single_value=True,
        ))
        store_with_predicates.insert_fact(_make_fact(
            subject_id="entity:person:b", predicate_id="father_of",
            object_id="entity:person:a", object_value="A",
        ))
        result = ConflictDetector(store_with_predicates).check(_make_fact(
            subject_id="entity:person:a", predicate_id="son_of",
            object_id="entity:person:c", object_value="C",
        ))
        assert result.relation == "CONFLICT"
        assert result.conflict_type == "object_cardinality"

    def test_symmetric_relation_is_duplicate(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="spouse_of", canonical_name="配偶是",
            symmetric=True, single_value=True, object_single_value=True,
        ))
        store_with_predicates.insert_fact(_make_fact(
            subject_id="entity:person:a", predicate_id="spouse_of",
            object_id="entity:person:b", object_value="B",
        ))
        result = ConflictDetector(store_with_predicates).check(_make_fact(
            subject_id="entity:person:b", predicate_id="spouse_of",
            object_id="entity:person:a", object_value="A",
        ))
        assert result.relation == "DUPLICATE"
        assert result.conflict_type == "symmetric_equivalent"

    def test_irreflexive_relation_rejected_for_review(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="parent_of", canonical_name="父母是", irreflexive=True,
        ))
        result = ConflictDetector(store_with_predicates).check(_make_fact(
            subject_id="entity:person:a", predicate_id="parent_of",
            object_id="entity:person:a", object_value="A",
        ))
        assert result.relation == "CONFLICT"
        assert result.conflict_type == "irreflexive_violation"

    def test_exclusive_predicates_conflict(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="is_alive", canonical_name="健在",
            exclusive_with=["is_deceased"],
        ))
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="is_deceased", canonical_name="已故",
            exclusive_with=["is_alive"],
        ))
        store_with_predicates.insert_fact(_make_fact(
            subject_id="entity:person:a", predicate_id="is_alive",
            object_id="entity:other:true", object_value="是",
        ))
        result = ConflictDetector(store_with_predicates).check(_make_fact(
            subject_id="entity:person:a", predicate_id="is_deceased",
            object_id="entity:other:true", object_value="是",
        ))
        assert result.relation == "CONFLICT"
        assert result.conflict_type == "mutually_exclusive_predicate"

    def test_acyclic_relation_detects_cycle(self, store_with_predicates):
        store_with_predicates.upsert_predicate(PredicateDef(
            predicate_id="part_of", canonical_name="属于组成部分",
            single_value=False, acyclic=True,
        ))
        store_with_predicates.insert_fact(_make_fact(
            subject_id="entity:other:a", predicate_id="part_of",
            object_id="entity:other:b", object_value="B",
        ))
        store_with_predicates.insert_fact(_make_fact(
            subject_id="entity:other:b", predicate_id="part_of",
            object_id="entity:other:c", object_value="C",
        ))
        result = ConflictDetector(store_with_predicates).check(_make_fact(
            subject_id="entity:other:c", predicate_id="part_of",
            object_id="entity:other:a", object_value="A",
        ))
        assert result.relation == "CONFLICT"
        assert result.conflict_type == "relation_cycle"
