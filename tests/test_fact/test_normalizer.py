"""
测试 normalizer.py — 实体归一化 + 谓词归一化
"""

import pytest
from memoryhub.core.fact.store import FactStore
from memoryhub.core.fact.normalizer import EntityNormalizer, PredicateNormalizer
from memoryhub.core.fact.models import Entity, FactDecisionRequired


class TestEntityNormalizer:
    def test_exact_canonical_name_match(self):
        store = FactStore(":memory:")
        # 预写入实体
        store.upsert_entity(Entity(
            entity_id="entity:organization:byd_001",
            canonical_name="比亚迪股份有限公司",
            entity_type="Organization",
            aliases=["比亚迪", "BYD"],
        ))
        norm = EntityNormalizer(store)

        result = norm.normalize("比亚迪股份有限公司", "Organization")
        assert result == "entity:organization:byd_001"

    def test_alias_match(self):
        store = FactStore(":memory:")
        store.upsert_entity(Entity(
            entity_id="entity:organization:byd_001",
            canonical_name="比亚迪股份有限公司",
            entity_type="Organization",
            aliases=["比亚迪", "BYD"],
        ))
        norm = EntityNormalizer(store)

        result = norm.normalize("比亚迪", "Organization")
        assert result == "entity:organization:byd_001"

        result2 = norm.normalize("BYD", "Organization")
        assert result2 == "entity:organization:byd_001"

    def test_cross_type_rejected(self):
        """跨类型匹配全部拒绝——即使语义相关的类型对也不行"""
        store = FactStore(":memory:")
        store.upsert_entity(Entity(
            entity_id="entity:organization:byd_001",
            canonical_name="比亚迪股份有限公司",
            entity_type="Organization",
            aliases=["比亚迪"],
        ))
        norm = EntityNormalizer(store)

        # 即使 Organization ↔ Location 语义相关，跨类型也不允许
        result = norm.normalize("比亚迪", "Location")
        assert result.startswith("entity:location:")  # 创建新 Location 实体，不链接到 Organization

    def test_cross_type_rejected_device_org(self):
        """跨类型 Device↔Organization 也被拒绝——苹果手机≠苹果公司"""
        store = FactStore(":memory:")
        store.upsert_entity(Entity(
            entity_id="entity:organization:apple_001",
            canonical_name="苹果公司",
            entity_type="Organization",
            aliases=["苹果"],
        ))
        norm = EntityNormalizer(store)

        # 创建新 Device 实体，不链接到 Organization
        result = norm.normalize("苹果", "Device")
        assert result.startswith("entity:device:")  # 新建 Device，"苹果公司" 不受影响

    def test_create_new_entity(self):
        store = FactStore(":memory:")
        norm = EntityNormalizer(store)

        result = norm.normalize("华为技术有限公司", "Organization")
        assert result.startswith("entity:organization:")
        # 确认实体已写入
        entity = store.get_entity(result)
        assert entity is not None
        assert entity.canonical_name == "华为技术有限公司"

    def test_add_alias(self):
        store = FactStore(":memory:")
        store.upsert_entity(Entity(
            entity_id="entity:person:wang_chuanfu",
            canonical_name="王传福",
            entity_type="Person",
            aliases=["王传福"],
        ))
        norm = EntityNormalizer(store)
        norm.add_alias("entity:person:wang_chuanfu", "老王")

        result = norm.normalize("老王", "Person")
        assert result == "entity:person:wang_chuanfu"


class TestPredicateNormalizer:
    def test_exact_alias_match(self):
        store = FactStore(":memory:")
        norm = PredicateNormalizer(store)

        result = norm.normalize("总部位于")
        assert result == "headquarters_location"

        result2 = norm.normalize("CEO")
        assert result2 == "chief_executive_officer"

    def test_partial_match(self):
        """文本包含别名应能匹配"""
        store = FactStore(":memory:")
        norm = PredicateNormalizer(store)

        # "总部在" contains in "总部所在地"? No... let me check
        # aliases: ["总部位于", "总部在", "总部所在地", "总部设于", "总部地址"]
        # "总部在" is an exact alias
        result = norm.normalize("总部在")
        assert result == "headquarters_location"

    def test_unknown_predicate(self):
        store = FactStore(":memory:")
        norm = PredicateNormalizer(store, api_key="dummy")

        result = norm.normalize("最喜欢的颜色是")
        assert result is not None
        assert result.startswith("pred:")
        # 验证已写入 store
        pred = store.get_predicate(result)
        assert pred is not None
        assert pred.canonical_name == "最喜欢的颜色是"

    def test_ambiguous_predicate_delegates_to_host_agent(self):
        store = FactStore(":memory:")
        norm = PredicateNormalizer(store)
        norm._keyword_match = lambda _text: None
        norm._index.search = lambda *_args, **_kwargs: [
            ("headquarters_location", 0.70),
            ("located_in", 0.68),
        ]

        with pytest.raises(FactDecisionRequired) as exc_info:
            norm.normalize("所在地")
        assert exc_info.value.decision_type == "predicate_resolution"
        assert "create_new" in exc_info.value.allowed_actions

    def test_ontology_loaded_into_store(self):
        store = FactStore(":memory:")
        PredicateNormalizer(store)

        pred = store.get_predicate("headquarters_location")
        assert pred is not None
        assert pred.canonical_name == "总部所在地"
        assert pred.single_value is True

        pred2 = store.get_predicate("founder")
        assert pred2 is not None
        assert pred2.single_value is False
