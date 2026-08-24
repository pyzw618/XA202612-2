"""Tests for S3-04 Fusion and vNext Reranker."""

from __future__ import annotations

import pytest

from memoryhub.adapter.vnext_schemas import RetrievedMemory
from memoryhub.domain.contracts import LifecycleLayer, MemoryScope, MemoryType
from memoryhub.retrieval.fusion import (
    ReciprocalRankFusion,
    ScoreFusion,
    deduplicate_candidates,
)
from memoryhub.retrieval.reranker import VNextReranker


def _memory(
    memory_id: str,
    *,
    score: float = 0.5,
    version: int = 1,
    layer: LifecycleLayer = LifecycleLayer.LONG_TERM,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
    content: dict | None = None,
) -> RetrievedMemory:
    return RetrievedMemory(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id=memory_id,
        memory_type=memory_type,
        layer=layer,
        scope_level=scope_level,
        scope=scope,
        content_version=version,
        evolution_status="ACTIVE",
        content=content or {"text": f"content of {memory_id}"},
        score=score,
        score_breakdown={},
        source_ids=[f"src:{memory_id}"],
    )


class TestDeduplication:
    def test_keeps_highest_content_version(self):
        v1 = _memory("m1", score=0.9, version=1)
        v2 = _memory("m1", score=0.5, version=2)
        kept, dropped = deduplicate_candidates([v1, v2])
        assert len(kept) == 1
        assert kept[0].content_version == 2
        assert len(dropped) == 1
        assert dropped[0]["dropped_version"] == 1

    def test_reports_all_dropped_versions(self):
        v1 = _memory("m1", score=0.9, version=1)
        v2 = _memory("m1", score=0.8, version=2)
        v3 = _memory("m1", score=0.7, version=3)
        kept, dropped = deduplicate_candidates([v1, v2, v3])
        assert kept[0].content_version == 3
        assert len(dropped) == 2


class TestReciprocalRankFusion:
    def test_fuses_two_channels_and_keeps_best_ranked(self):
        vector_results = [
            _memory("m1", score=0.9),
            _memory("m2", score=0.7),
        ]
        keyword_results = [
            _memory("m2", score=0.95),
            _memory("m3", score=0.6),
        ]
        rrf = ReciprocalRankFusion(k=60)
        result = rrf.fuse(
            {"vector": vector_results, "keyword": keyword_results}
        )
        ids = [m.memory_id for m in result.memories]
        assert set(ids) == {"m1", "m2", "m3"}
        # m2 appears in both channels, so it should have the highest fused score.
        assert ids[0] == "m2"
        for memory in result.memories:
            assert "fused" in memory.score_breakdown
            assert "channel_scores" in memory.score_breakdown

    def test_deduplicates_during_fusion(self):
        v1 = _memory("m1", score=0.9, version=1)
        v2 = _memory("m1", score=0.5, version=2)
        rrf = ReciprocalRankFusion()
        result = rrf.fuse({"vector": [v1], "keyword": [v2]})
        assert result.deduplicated_count == 1
        assert result.total_candidates == 2
        assert len(result.dropped_versions) == 1

    def test_respects_top_k(self):
        memories = [_memory(f"m{i}", score=1.0 - i * 0.1) for i in range(10)]
        rrf = ReciprocalRankFusion()
        result = rrf.fuse({"vector": memories}, top_k=3)
        assert len(result.memories) == 3


class TestScoreFusion:
    def test_weighted_combination(self):
        vector_results = [_memory("m1", score=0.9)]
        keyword_results = [_memory("m1", score=0.5)]
        fusion = ScoreFusion(weights={"vector": 0.7, "keyword": 0.3})
        result = fusion.fuse(
            {"vector": vector_results, "keyword": keyword_results}
        )
        assert len(result.memories) == 1
        m = result.memories[0]
        assert m.score_breakdown["vector"] == pytest.approx(0.9)
        assert m.score_breakdown["keyword"] == pytest.approx(0.5)
        assert m.score > 0.0

    def test_missing_channel_does_not_deflate_score(self):
        fusion = ScoreFusion(weights={"vector": 0.5, "keyword": 0.5})
        result = fusion.fuse({"vector": [_memory("m1", score=0.8)]})
        assert result.memories[0].score == pytest.approx(0.8)


class TestVNextReranker:
    def test_score_breakdown_includes_all_factors(self):
        candidates = [
            _memory("m1", score=0.9, content={"text": "hello world"}),
            _memory("m2", score=0.6, content={"text": "foo bar"}),
        ]
        reranker = VNextReranker()
        result = reranker.rerank(candidates, query="hello world")
        assert len(result) == 2
        top = result[0]
        assert top.memory_id == "m1"
        breakdown = top.score_breakdown
        assert "final_score" in breakdown
        assert "base_score" in breakdown
        assert "relevance_score" in breakdown
        assert "scope_match_score" in breakdown
        assert "confidence_score" in breakdown
        assert "freshness_score" in breakdown
        assert "health_score" in breakdown

    def test_scope_match_prefers_exact_scope(self):
        global_mem = _memory(
            "m1",
            score=0.9,
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
        )
        project_mem = _memory(
            "m2",
            score=0.6,
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p1",
        )
        reranker = VNextReranker()
        result = reranker.rerank(
            [global_mem, project_mem],
            query="",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:p1",
        )
        # Project-scoped memory should outrank global even with lower base score.
        assert result[0].memory_id == "m2"

    def test_intent_type_boost(self):
        pref = _memory(
            "m1",
            score=0.7,
            memory_type=MemoryType.PREFERENCE,
            content={"text": "prefer markdown"},
        )
        semantic = _memory(
            "m2",
            score=0.8,
            memory_type=MemoryType.SEMANTIC,
            content={"text": "fact about python"},
        )
        boosts = {"PREFERENCE": {"PREFERENCE": 1.5}}
        reranker = VNextReranker(intent_type_boosts=boosts)
        result = reranker.rerank(
            [pref, semantic], query="prefer", intent="PREFERENCE"
        )
        assert result[0].memory_id == "m1"

    def test_top_k_truncation(self):
        candidates = [_memory(f"m{i}", score=1.0 - i * 0.05) for i in range(10)]
        reranker = VNextReranker()
        result = reranker.rerank(candidates, top_k=4)
        assert len(result) == 4

    def test_input_objects_not_mutated(self):
        candidate = _memory("m1", score=0.5)
        original_score = candidate.score
        reranker = VNextReranker()
        reranker.rerank([candidate], query="hello")
        assert candidate.score == original_score
        assert "final_score" not in candidate.score_breakdown
