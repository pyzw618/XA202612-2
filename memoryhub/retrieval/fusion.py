"""Cross-channel candidate fusion for vNext retrieval.

Fusion is responsible for two things:

1. Deduplicating candidates that appear in multiple recall channels,
   keeping the highest ``content_version`` per ``memory_id``.
2. Combining per-channel ranks/scores into a single explainable fused score
   using Reciprocal Rank Fusion (RRF).

The module is stateless and algorithm-only; it does not call retrievers or
external services.  The resulting ``RetrievedMemory`` objects preserve their
original channel scores in ``score_breakdown`` and add the fused score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoryhub.adapter.vnext_schemas import RetrievedMemory


@dataclass(frozen=True, slots=True)
class FusionResult:
    """Outputs of a fusion pass."""

    memories: list[RetrievedMemory]
    total_candidates: int = 0
    deduplicated_count: int = 0
    dropped_versions: list[dict[str, Any]] = field(default_factory=list)
    channel_counts: dict[str, int] = field(default_factory=dict)


class ReciprocalRankFusion:
    """Combine ranked channel results with Reciprocal Rank Fusion.

    RRF is chosen because it is:

    * Score-scale invariant -- each channel can return scores in its own range.
    * Explainable -- the contribution of each channel is a simple rank term.
    * Deterministic -- identical inputs always produce the same fused ranking.

    The constant ``k`` dampens the advantage of being ranked #1 in a single
    channel; a higher ``k`` rewards breadth across channels.
    """

    DEFAULT_K: float = 60.0

    def __init__(self, k: float = DEFAULT_K) -> None:
        if k <= 0:
            raise ValueError("RRF k must be positive")
        self.k = k

    def fuse(
        self,
        channel_results: dict[str, list[RetrievedMemory]],
        *,
        top_k: int | None = None,
        channel_weights: dict[str, float] | None = None,
    ) -> FusionResult:
        """Fuse ranked results from multiple channels.

        Args:
            channel_results: Mapping from channel name to ordered list of
                ``RetrievedMemory`` candidates.  Order within a channel is the
                rank used by RRF; higher original scores should appear first.
            top_k: Optional limit on the number of fused results returned.

        Returns:
            ``FusionResult`` containing deduplicated, reranked memories with
            score breakdowns.
        """
        total_candidates = sum(len(items) for items in channel_results.values())

        # Deduplicate: keep the highest content_version per memory_id.
        # Lower versions of the same memory are tracked for diagnostics but
        # never enter the fused candidate pool.
        by_memory: dict[str, RetrievedMemory] = {}
        dropped_versions: list[dict[str, Any]] = []
        for channel, items in channel_results.items():
            for item in items:
                key = item.memory_id
                existing = by_memory.get(key)
                if existing is None:
                    by_memory[key] = item
                    continue
                if item.content_version > existing.content_version:
                    dropped_versions.append(
                        {
                            "memory_id": key,
                            "dropped_version": existing.content_version,
                            "dropped_channel": channel,
                            "kept_version": item.content_version,
                        }
                    )
                    by_memory[key] = item
                elif item.content_version < existing.content_version:
                    dropped_versions.append(
                        {
                            "memory_id": key,
                            "dropped_version": item.content_version,
                            "dropped_channel": channel,
                            "kept_version": existing.content_version,
                        }
                    )

        # Rank positions per channel.  We use 1-based ranks and only count the
        # highest retained version of each memory within a channel.
        channel_ranks: dict[str, dict[str, int]] = {
            channel: {} for channel in channel_results
        }
        for channel, items in channel_results.items():
            rank = 1
            seen: set[str] = set()
            for item in items:
                key = item.memory_id
                if key in seen:
                    continue
                seen.add(key)
                retained = by_memory[key]
                if item.content_version == retained.content_version:
                    channel_ranks[channel][key] = rank
                rank += 1

        # Compute RRF scores and assemble score breakdowns.
        scored: list[tuple[float, RetrievedMemory]] = []
        for key, item in by_memory.items():
            breakdown: dict[str, float] = {"fused": 0.0}
            channel_scores: dict[str, float] = {}
            for channel, ranks in channel_ranks.items():
                rank = ranks.get(key)
                if rank is not None:
                    weight = max(0.0, float((channel_weights or {}).get(channel, 1.0)))
                    contribution = weight / (self.k + rank)
                    breakdown[channel] = contribution
                    breakdown["fused"] += contribution
                    # Find the original score for this channel.
                    original_score = next(
                        (
                            candidate.score
                            for candidate in channel_results[channel]
                            if candidate.memory_id == key
                            and candidate.content_version == item.content_version
                        ),
                        0.0,
                    )
                    channel_scores[channel] = round(original_score, 6)

            # Preserve original score_breakdown fields (e.g. vector similarity).
            merged_breakdown = dict(item.score_breakdown)
            merged_breakdown.update(breakdown)
            merged_breakdown["channel_scores"] = channel_scores
            merged_breakdown["rrf_k"] = self.k
            merged_breakdown["channel_weights"] = {
                channel: max(0.0, float((channel_weights or {}).get(channel, 1.0)))
                for channel in channel_ranks
            }

            new_item = RetrievedMemory(
                **item.model_dump(
                    exclude={"score", "score_breakdown"}, mode="json"
                ),
                score=round(breakdown["fused"], 6),
                score_breakdown=merged_breakdown,
            )
            scored.append((breakdown["fused"], new_item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        memories = [item for _, item in scored]
        if top_k is not None:
            memories = memories[:top_k]

        return FusionResult(
            memories=memories,
            total_candidates=total_candidates,
            deduplicated_count=len(by_memory),
            dropped_versions=dropped_versions,
            channel_counts={
                channel: len(items) for channel, items in channel_results.items()
            },
        )


class ScoreFusion:
    """Linear weighted score combination across channels.

    Use this when all channels produce comparable scores (e.g. normalised
    similarities).  The default weights favour dense vector similarity but
    give keyword and metadata matches a non-zero voice.
    """

    DEFAULT_WEIGHTS: dict[str, float] = {
        "vector": 0.50,
        "keyword": 0.25,
        "metadata": 0.15,
        "authority": 0.10,
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(weights or self.DEFAULT_WEIGHTS)

    def fuse(
        self,
        channel_results: dict[str, list[RetrievedMemory]],
        *,
        top_k: int | None = None,
    ) -> FusionResult:
        """Fuse results using weighted linear score combination."""
        total_candidates = sum(len(items) for items in channel_results.values())

        by_memory: dict[str, RetrievedMemory] = {}
        dropped_versions: list[dict[str, Any]] = []
        for channel, items in channel_results.items():
            for item in items:
                key = item.memory_id
                existing = by_memory.get(key)
                if existing is None:
                    by_memory[key] = item
                    continue
                if item.content_version > existing.content_version:
                    dropped_versions.append(
                        {
                            "memory_id": key,
                            "dropped_version": existing.content_version,
                            "dropped_channel": channel,
                            "kept_version": item.content_version,
                        }
                    )
                    by_memory[key] = item
                elif item.content_version < existing.content_version:
                    dropped_versions.append(
                        {
                            "memory_id": key,
                            "dropped_version": item.content_version,
                            "dropped_channel": channel,
                            "kept_version": existing.content_version,
                        }
                    )

        # Aggregate scores per channel, keeping the best score for the retained
        # version of each memory.
        channel_best: dict[str, dict[str, float]] = {
            channel: {} for channel in channel_results
        }
        for channel, items in channel_results.items():
            for item in items:
                key = item.memory_id
                retained = by_memory[key]
                if item.content_version != retained.content_version:
                    continue
                current = channel_best[channel].get(key, 0.0)
                channel_best[channel][key] = max(current, item.score)

        scored: list[tuple[float, RetrievedMemory]] = []
        for key, item in by_memory.items():
            breakdown: dict[str, float] = {"fused": 0.0}
            channel_scores: dict[str, float] = {}
            total_weight = 0.0
            for channel, weight in self.weights.items():
                score = channel_best.get(channel, {}).get(key, 0.0)
                channel_scores[channel] = round(score, 6)
                if score > 0.0:
                    breakdown[channel] = score
                    breakdown["fused"] += weight * score
                    total_weight += weight

            # Normalise by the weight of channels that actually had the item so
            # a missing channel does not drag the fused score down artificially.
            if total_weight > 0:
                breakdown["fused"] /= total_weight

            merged_breakdown = dict(item.score_breakdown)
            merged_breakdown.update(breakdown)
            merged_breakdown["channel_scores"] = channel_scores
            merged_breakdown["weights"] = dict(self.weights)

            new_item = RetrievedMemory(
                **item.model_dump(
                    exclude={"score", "score_breakdown"}, mode="json"
                ),
                score=round(breakdown["fused"], 6),
                score_breakdown=merged_breakdown,
            )
            scored.append((breakdown["fused"], new_item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        memories = [item for _, item in scored]
        if top_k is not None:
            memories = memories[:top_k]

        return FusionResult(
            memories=memories,
            total_candidates=total_candidates,
            deduplicated_count=len(by_memory),
            dropped_versions=dropped_versions,
            channel_counts={
                channel: len(items) for channel, items in channel_results.items()
            },
        )


def deduplicate_candidates(
    candidates: list[RetrievedMemory],
) -> tuple[list[RetrievedMemory], list[dict[str, Any]]]:
    """Standalone deduplication helper: highest content_version wins."""
    by_memory: dict[str, RetrievedMemory] = {}
    dropped: list[dict[str, Any]] = []
    for item in candidates:
        key = item.memory_id
        existing = by_memory.get(key)
        if existing is None or item.content_version > existing.content_version:
            if existing is not None:
                dropped.append(
                    {
                        "memory_id": key,
                        "dropped_version": existing.content_version,
                        "kept_version": item.content_version,
                    }
                )
            by_memory[key] = item
        elif item.content_version < existing.content_version:
            dropped.append(
                {
                    "memory_id": key,
                    "dropped_version": item.content_version,
                    "kept_version": existing.content_version,
                }
            )
    return list(by_memory.values()), dropped


__all__ = [
    "FusionResult",
    "ReciprocalRankFusion",
    "ScoreFusion",
    "deduplicate_candidates",
]
