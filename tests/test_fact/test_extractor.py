"""
测试 extractor.py — LLM 三元组提取（含 mock 测试）
"""

import json
import pytest

from memoryhub.core.fact.extractor import TripleExtractor
from memoryhub.core.fact.models import RawTriple


MOCK_LLM_RESPONSE = {
    "triples": [
        {
            "subject": "比亚迪股份有限公司",
            "subject_type": "Organization",
            "predicate": "总部位于",
            "object": "深圳",
            "object_type": "Location",
            "evidence": "比亚迪股份有限公司总部位于深圳",
            "confidence": 0.95,
        },
        {
            "subject": "比亚迪股份有限公司",
            "subject_type": "Organization",
            "predicate": "成立于",
            "object": "1995年",
            "object_type": "Date",
            "evidence": "成立于1995年",
            "confidence": 0.93,
        },
    ]
}

MOCK_EMPTY_RESPONSE = {"triples": []}


class TestTripleExtractorParsing:
    """测试 JSON 解析逻辑（不需要真实 LLM）"""

    def test_parse_valid_response(self):
        extractor = TripleExtractor(api_key="dummy")

        results = extractor._parse_response(
            json.dumps(MOCK_LLM_RESPONSE, ensure_ascii=False),
            "test_001",
        )
        assert len(results) == 2
        assert results[0].subject_text == "比亚迪股份有限公司"
        assert results[0].predicate_text == "总部位于"
        assert results[0].object_text == "深圳"
        assert results[0].confidence == 0.95

    def test_parse_empty_response(self):
        extractor = TripleExtractor(api_key="dummy")

        results = extractor._parse_response(
            json.dumps(MOCK_EMPTY_RESPONSE),
            "test_002",
        )
        assert results == []

    def test_parse_with_markdown_wrapper(self):
        extractor = TripleExtractor(api_key="dummy")

        raw = "```json\n" + json.dumps(MOCK_LLM_RESPONSE, ensure_ascii=False) + "\n```"
        results = extractor._parse_response(raw, "test_003")
        assert len(results) == 2

    def test_parse_missing_fields(self):
        extractor = TripleExtractor(api_key="dummy")

        bad_json = '{"triples": [{"subject": "test", "predicate": "is"}]}'
        results = extractor._parse_response(bad_json, "test_004")
        assert results == []  # 缺失字段的三元组被丢弃

    def test_parse_invalid_json(self):
        extractor = TripleExtractor(api_key="dummy")

        results = extractor._parse_response("not json at all", "test_005")
        assert results == []

    def test_empty_text_returns_empty(self):
        extractor = TripleExtractor(api_key="dummy")
        results = extractor.extract("", "test_006")
        assert results == []


class TestTripleExtractorRuleFallback:
    """无 LLM 时确定性规则降级抽取（FCT-01 客观事实仍需可写入）"""

    @pytest.fixture
    def extractor(self):
        return TripleExtractor()

    def test_chinese_attribute(self, extractor):
        results = extractor.extract("项目A的负责人是张三。", source_id="r1")
        assert len(results) == 1
        r = results[0]
        assert (r.subject_text, r.predicate_text, r.object_text) == ("项目A", "负责人", "张三")
        assert r.object_type == "Person"

    def test_chinese_location(self, extractor):
        results = extractor.extract("苹果公司总部位于深圳。", source_id="r2")
        assert (results[0].subject_text, results[0].predicate_text, results[0].object_text) == (
            "苹果公司总部", "位于", "深圳")
        assert results[0].object_type == "Location"

    def test_chinese_founding_date(self, extractor):
        results = extractor.extract("华为公司成立于1987年。", source_id="r3")
        assert (results[0].predicate_text, results[0].object_text) == ("成立于", "1987年")
        assert results[0].object_type == "Date"

    def test_english_role_swaps_subject(self, extractor):
        results = extractor.extract("Tim Cook is the CEO of Apple.", source_id="r4")
        assert (results[0].subject_text, results[0].predicate_text, results[0].object_text) == (
            "Apple", "ceo", "Tim Cook")
        assert results[0].object_type == "Person"

    def test_english_location_and_date(self, extractor):
        results = extractor.extract(
            "Acme Inc is located in Berlin. OpenAI was founded in 2015.", source_id="r5")
        by_pred = {r.predicate_text: r for r in results}
        assert by_pred["located in"].object_text == "Berlin"
        assert by_pred["founded in"].object_text == "2015"

    def test_confidence_is_conservative(self, extractor):
        results = extractor.extract("项目A的负责人是张三。", source_id="r6")
        assert results[0].confidence == 0.7

    def test_no_match_sets_last_error(self, extractor):
        results = extractor.extract("这个文本没有任何客观断言结构。", source_id="r7")
        assert results == []
        assert extractor.last_error is not None

    def test_empty_text_no_error(self, extractor):
        assert extractor.extract("", source_id="r8") == []
        assert extractor.last_error is None


class TestTripleExtractorIntegration:
    """需要 API key 的集成测试，默认跳过"""

    @pytest.mark.skip(reason="需要真实 API key")
    def test_real_extraction(self):
        extractor = TripleExtractor()
        text = "苹果公司总部位于加利福尼亚州库比蒂诺，CEO是Tim Cook。"
        results = extractor.extract(text, source_id="test_real")

        assert len(results) >= 1
        for r in results:
            assert r.subject_text
            assert r.predicate_text
            assert r.object_text
            assert r.evidence
            assert 0 <= r.confidence <= 1
