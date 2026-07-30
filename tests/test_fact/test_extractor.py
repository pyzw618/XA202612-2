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
