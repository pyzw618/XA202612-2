from datetime import datetime, timedelta, timezone

from memoryhub.adapter.schemas import SearchRequest, SearchResult
from memoryhub.core.fact.extractor import TripleExtractor
from memoryhub.core.memory.base import BaseMemoryHandler, MemoryCandidate
from memoryhub.core.memory.confidence import (
    ConfidenceFactors,
    UnifiedConfidenceCalculator,
)
from memoryhub.core.memory.evidence import EvidenceMerger
from memoryhub.core.memory.freshness import freshness_score
from memoryhub.core.memory.llm import StructuredLLMAdapter
from memoryhub.retrieval.reranker import Reranker


class _Handler(BaseMemoryHandler):
    memory_type = "fact"

    def extract_candidates(self, source, *, context=None):
        return [MemoryCandidate("fact", source, "u", evidences=source)]

    def find_similar(self, candidate):
        return None

    def build_confidence_factors(self, candidate, existing):
        return ConfidenceFactors(
            0.95,
            0.9,
            self.confidence_calculator.support_from_evidence_count(
                len(candidate.evidences)
            ),
            1.0,
        )

    def apply(self, decision):
        return decision


class _Response:
    content = '{"value": 3}'


class _LLM:
    def generate(self, prompt, system_prompt="", **kwargs):
        assert prompt == "input"
        assert system_prompt == "system"
        assert kwargs["temperature"] == 0.0
        return _Response()


def test_evidence_merger_deduplicates_retries_and_orders_timestamps():
    merger = EvidenceMerger()
    evidences = [
        {
            "event_id": "evt-1",
            "evidence_id": "one",
            "content": "first",
            "timestamp": "2026-08-01T00:00:00Z",
        },
        {
            "event_id": "evt-1",
            "evidence_id": "one",
            "content": "first retry",
            "timestamp": "2026-08-03T00:00:00Z",
        },
        {"source_id": "src", "content": "second", "timestamp": "2026-08-02T00:00:00Z"},
    ]
    merged = merger.normalize_and_merge(evidences)
    assert len(merged) == 2
    assert [item["content"] for item in merged] == ["first", "second"]
    assert merger.summary(merged)["count"] == 2


def test_confidence_is_bounded_and_retries_do_not_raise_support():
    calculator = UnifiedConfidenceCalculator()
    factors = ConfidenceFactors(
        0.95, 0.9, calculator.support_from_evidence_count(3), 1.0
    )
    retried = ConfidenceFactors(
        0.95, 0.9, calculator.support_from_evidence_count(100), 1.0
    )
    assert calculator.calculate(factors) == calculator.calculate(retried)
    assert calculator.calculate(factors) <= 0.95


def test_base_handler_uses_shared_merge_score_and_decision_chain():
    decisions = _Handler().process(
        [
            {
                "event_id": "evt",
                "evidence_id": "a",
                "content": "x",
                "timestamp": datetime(2026, 8, 1),
            },
            {
                "event_id": "evt",
                "evidence_id": "a",
                "content": "x",
                "timestamp": datetime(2026, 8, 1),
            },
        ]
    )
    assert len(decisions) == 1
    assert decisions[0].action == "new"
    assert len(decisions[0].candidate.evidences) == 1


def test_structured_llm_adapter_uses_application_generate_contract():
    result = StructuredLLMAdapter(_LLM()).generate_json(
        task_name="unit",
        system_prompt="system",
        prompt="input",
        parser=lambda value: value["value"],
    )
    assert result == 3


class _TripleResponse:
    content = (
        '{"triples":[{"subject":"??A","subject_type":"Other",'
        '"predicate":"???","object":"??","object_type":"Person",'
        '"evidence":"??A???????","confidence":0.9}]}'
    )


class _TripleLLM:
    def generate(self, prompt, system_prompt="", **kwargs):
        assert "?????" in prompt
        assert system_prompt
        return _TripleResponse()


def test_fact_extractor_uses_application_level_generate_client():
    triples = TripleExtractor(llm_client=_TripleLLM()).extract("??A???????")
    assert len(triples) == 1
    assert triples[0].object_text == "??"


def test_shared_freshness_is_bounded_and_uses_type_half_lives():
    now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    old = (now - timedelta(days=60)).isoformat()
    assert freshness_score(old, memory_type="fact", now=now) == 0.25
    assert freshness_score(old, memory_type="preference", now=now) == 0.5
    assert freshness_score(old, memory_type="knowledge", now=now) > 0.5
    assert freshness_score("invalid", memory_type="fact", now=now) == 0.5
    assert 0.0 <= freshness_score(now.isoformat(), memory_type="fact", now=now) <= 1.0


def test_reranker_records_bounded_confidence_and_freshness_signals():
    now = datetime.now(timezone.utc)
    results = [
        SearchResult(
            memory_id="old-fact",
            memory_type="fact",
            content="project owner alice",
            score=0.8,
            metadata={
                "confidence": 0.9,
                "observed_at": (now - timedelta(days=120)).isoformat(),
            },
        ),
        SearchResult(
            memory_id="fresh-fact",
            memory_type="fact",
            content="project owner bob",
            score=0.8,
            metadata={"confidence": 0.9, "observed_at": now.isoformat()},
        ),
    ]
    reranked = Reranker().rerank(results, SearchRequest(query="project owner"))
    assert reranked[0].memory_id == "fresh-fact"
    for result in reranked:
        assert 0.0 <= result.metadata["confidence_score"] <= 1.0
        assert 0.0 <= result.metadata["freshness_score"] <= 1.0
        assert 0.0 <= result.metadata["rerank_score"] <= 1.0
