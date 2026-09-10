"""Segmented vNext retrieval evaluator (S3-10).

Evaluates the unified RetrievalService across five segments:

* ROUTER   – intent routing accuracy and confidence
* RECALL   – Recall@K, Precision@K, MRR, NDCG@K against expected memories
* RANKING  – pairwise rank order accuracy against the ideal ordering
* SCOPE    – forbidden-memory leakage (DELETED/SUPERSEDED/Candidate/other-tenant)
             and expected-scope-level match
* CONTEXT  – context precision/recall, constraint preservation, budget compliance

The evaluator is deterministic and reproducible: a fixed dataset + fixed
RetrievalService configuration always produces the same report.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoryhub.adapter.vnext_schemas import (
    ContextPayload,
    MemoryRetrievalRequest,
    RetrievedMemory,
)
from memoryhub.application.retrieval_service import ChannelExecutor, RetrievalService
from memoryhub.domain.contracts import (
    LifecycleLayer,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)

DEFAULT_TOP_K = 10


class RetrievalEvalSegment:
    """Named segments for the S3-10 segmented report."""

    ROUTER = "ROUTER"
    RECALL = "RECALL"
    RANKING = "RANKING"
    SCOPE = "SCOPE"
    CONTEXT = "CONTEXT"


@dataclass(frozen=True, slots=True)
class VNextRetrievalSampleResult:
    """Per-query segmented results."""

    query_id: str
    query: str
    expected_intent: str
    predicted_intent: str
    router_correct: bool
    recall_at_k: float
    candidate_recall_at_k: float
    selected_precision: float
    selected_recall: float
    precision_at_k: float
    mrr: float
    ndcg_at_k: float
    ranking_score: float
    scope_leak_count: int
    scope_leak_rate: float
    scope_correct: bool
    context_precision: float
    context_recall: float
    constraint_preservation: float
    budget_compliant: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VNextRetrievalEvalReport:
    """Aggregate segmented evaluation report."""

    schema_version: str = "vnext/v1"
    total_queries: int = 0
    router_accuracy: float = 0.0
    router_intent_counts: dict[str, int] = field(default_factory=dict)
    recall_at_k: float = 0.0
    candidate_recall_at_k: float = 0.0
    selected_precision: float = 0.0
    selected_recall: float = 0.0
    precision_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    ranking_score: float = 0.0
    scope_leak_rate: float = 0.0
    scope_accuracy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    constraint_preservation: float = 0.0
    budget_compliance: float = 0.0
    sample_results: list[VNextRetrievalSampleResult] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "total_queries": self.total_queries,
            "router_accuracy": self.router_accuracy,
            "router_intent_counts": self.router_intent_counts,
            "recall_at_k": self.recall_at_k,
            "candidate_recall_at_k": self.candidate_recall_at_k,
            "selected_precision": self.selected_precision,
            "selected_recall": self.selected_recall,
            "precision_at_k": self.precision_at_k,
            "mrr": self.mrr,
            "ndcg_at_k": self.ndcg_at_k,
            "ranking_score": self.ranking_score,
            "scope_leak_rate": self.scope_leak_rate,
            "scope_accuracy": self.scope_accuracy,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "constraint_preservation": self.constraint_preservation,
            "budget_compliance": self.budget_compliance,
            "sample_results": [self._sample_dict(s) for s in self.sample_results],
        }

    @staticmethod
    def _sample_dict(s: VNextRetrievalSampleResult) -> dict[str, Any]:
        return {
            "query_id": s.query_id,
            "query": s.query,
            "expected_intent": s.expected_intent,
            "predicted_intent": s.predicted_intent,
            "router_correct": s.router_correct,
            "recall_at_k": s.recall_at_k,
            "candidate_recall_at_k": s.candidate_recall_at_k,
            "selected_precision": s.selected_precision,
            "selected_recall": s.selected_recall,
            "precision_at_k": s.precision_at_k,
            "mrr": s.mrr,
            "ndcg_at_k": s.ndcg_at_k,
            "ranking_score": s.ranking_score,
            "scope_leak_count": s.scope_leak_count,
            "scope_leak_rate": s.scope_leak_rate,
            "scope_correct": s.scope_correct,
            "context_precision": s.context_precision,
            "context_recall": s.context_recall,
            "constraint_preservation": s.constraint_preservation,
            "budget_compliant": s.budget_compliant,
            "details": s.details,
        }


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------


def _recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected:
        return 1.0
    top_k = set(retrieved[:k])
    hits = sum(1 for e in expected if e in top_k)
    return hits / len(expected)


def _precision_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    k = min(k, len(retrieved)) if retrieved else 0
    if k <= 0:
        return 0.0
    expected_set = set(expected)
    hits = sum(1 for r in retrieved[:k] if r in expected_set)
    return hits / k


def _mrr(expected: list[str], retrieved: list[str]) -> float:
    expected_set = set(expected)
    for rank, rid in enumerate(retrieved, start=1):
        if rid in expected_set:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    expected_set = set(expected)
    dcg = 0.0
    for i, rid in enumerate(retrieved[:k]):
        if rid in expected_set:
            dcg += 1.0 / math.log2(i + 2)
    ideal = min(len(expected_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def _pairwise_rank_accuracy(expected: list[str], retrieved: list[str]) -> float:
    """Fraction of correctly ordered expected-id pairs in the retrieved list."""
    expected_set = set(expected)
    positions = {rid: idx for idx, rid in enumerate(retrieved) if rid in expected_set}
    pairs = 0
    correct = 0
    for i, a in enumerate(expected):
        if a not in positions:
            continue
        for b in expected[i + 1:]:
            if b not in positions:
                continue
            pairs += 1
            if positions[a] < positions[b]:
                correct += 1
    return correct / pairs if pairs else 1.0


def _scope_leak_rate(forbidden: list[str], selected: list[str], context_ids: list[str]) -> float:
    if not forbidden:
        return 0.0
    combined = set(selected) | set(context_ids)
    leaks = sum(1 for fid in forbidden if fid in combined)
    return leaks / len(forbidden)


def _context_precision(expected: list[str], context_ids: list[str]) -> float:
    if not context_ids:
        return 1.0 if not expected else 0.0
    expected_set = set(expected)
    hits = sum(1 for cid in context_ids if cid in expected_set)
    return hits / len(context_ids)


def _context_recall(expected: list[str], context_ids: list[str]) -> float:
    if not expected:
        return 1.0
    context_set = set(context_ids)
    hits = sum(1 for e in expected if e in context_set)
    return hits / len(expected)


def _constraint_preservation(required: list[str], context: ContextPayload) -> float:
    if not required:
        return 1.0
    rendered = (context.rendered_context or "").lower()
    constraints = [c.lower() for c in context.constraints]
    preserved = 0
    for constraint in required:
        needle = constraint.lower()
        if needle in rendered or any(needle in c for c in constraints):
            preserved += 1
    return preserved / len(required)


# ---------------------------------------------------------------------------
# Mock channel executors seeded from the dataset
# ---------------------------------------------------------------------------


def _to_retrieved_memory(memory_map: dict[str, dict[str, Any]], memory_id: str) -> RetrievedMemory:
    raw = memory_map[memory_id]
    return RetrievedMemory(
        tenant_id=raw["tenant_id"],
        user_id=raw["user_id"],
        memory_id=raw["memory_id"],
        memory_type=MemoryType(raw["memory_type"]),
        layer=LifecycleLayer(raw["layer"]),
        scope_level=MemoryScope(raw["scope_level"]),
        scope=raw["scope"],
        content_version=raw["content_version"],
        evolution_status=raw["evolution_status"],
        content=raw["content"],
        score=raw.get("score", 0.5),
        score_breakdown=raw.get("score_breakdown", {}),
        source_ids=raw.get("source_ids", []),
    )


def _make_channel_executor(
    memory_map: dict[str, dict[str, Any]],
    query_map: dict[str, dict[str, Any]],
    channel: str,
) -> ChannelExecutor:
    """Return a deterministic executor that respects tenant/user isolation."""

    def executor(
        request: MemoryRetrievalRequest,
        plan: Any,
        ch: str,
    ) -> list[RetrievedMemory]:
        query = query_map.get(request.request_id)
        if query is None:
            return []
        relevance = query.get("channel_relevance", {})
        memory_ids = relevance.get(channel, [])
        results: list[RetrievedMemory] = []
        for mid in memory_ids:
            raw = memory_map.get(mid)
            if raw is None:
                continue
            # Enforce tenant/user isolation at the executor boundary.
            if raw.get("tenant_id") != request.tenant_id:
                continue
            if raw.get("user_id") != request.user_id:
                continue
            # Candidate memories are not retrievable through ordinary channels
            # (S1-06); the retrieval service must isolate them by default.
            if "candidate" in raw.get("source_ids", []):
                continue
            # Metadata filter: honour layer/type constraints from the plan.
            if plan.required_layers:
                if raw["layer"] not in {layer.value for layer in plan.required_layers}:
                    continue
            if plan.required_types:
                if raw["memory_type"] not in {t.value for t in plan.required_types}:
                    continue
            memory = _to_retrieved_memory(memory_map, mid)
            # Degrade score linearly with rank so fusion/rerank have ordering signal.
            memory = RetrievedMemory(
                **{
                    **memory.model_dump(),
                    "score": max(0.1, memory.score - len(results) * 0.01),
                }
            )
            results.append(memory)
        return results

    return executor


def build_vnext_retrieval_service_for_eval(
    dataset: dict[str, Any],
    *,
    seed: int = 42,
) -> RetrievalService:
    """Build a RetrievalService seeded from a vNext retrieval eval dataset.

    Each query in the dataset declares which memories each channel should
    return via ``channel_relevance``.  The service uses deterministic mock
    executors, so the evaluation is fully reproducible.
    """
    random.seed(seed)
    memory_map = {m["memory_id"]: m for m in dataset["memories"]}
    query_map = {q["query_id"]: q for q in dataset["queries"]}
    channel_executors = {
        channel: _make_channel_executor(memory_map, query_map, channel)
        for channel in ("vector", "keyword", "metadata", "working", "episode", "authority")
    }
    return RetrievalService(channel_executors=channel_executors)


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class VNextRetrievalEvaluator:
    """Segmented evaluator for the vNext unified retrieval pipeline."""

    def __init__(
        self,
        retrieval_service: RetrievalService,
        *,
        top_k: int = DEFAULT_TOP_K,
        seed: int = 42,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.top_k = top_k
        self.seed = seed

    def evaluate(self, dataset_path: str | Path) -> VNextRetrievalEvalReport:
        """Run the segmented evaluation and return a reproducible report."""
        dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        metadata = dataset.get("metadata", {})
        self.top_k = metadata.get("top_k", self.top_k)
        random.seed(metadata.get("seed", self.seed))

        memory_map = {m["memory_id"]: m for m in dataset["memories"]}
        sample_results: list[VNextRetrievalSampleResult] = []

        for query in dataset["queries"]:
            sample_results.append(self._evaluate_query(query, memory_map))

        return self._aggregate(sample_results)

    def _evaluate_query(
        self,
        query: dict[str, Any],
        memory_map: dict[str, dict[str, Any]],
    ) -> VNextRetrievalSampleResult:
        request = self._build_request(query)
        result = self.retrieval_service.retrieve(
            request,
            working_state=query.get("working_state", {}),
            constraints=query.get("active_constraints", []),
        )
        response = result.response
        selected_ids = [m.memory_id for m in response.selected_memories]
        context_ids = list(response.context.relevant_memory_ids)

        expected_intent = query["expected_intent"]
        predicted_intent = response.intent.value
        router_correct = predicted_intent == expected_intent

        candidate_ids = list(query.get("expected_candidate_memory_ids", query.get("expected_memory_ids", [])))
        expected_ids = list(query.get("expected_selected_memory_ids", query.get("expected_memory_ids", [])))
        forbidden_ids = list(query.get("forbidden_memory_ids", []))
        expected_context_ids = list(query.get("expected_context_ids", []))
        required_constraints = list(query.get("required_constraints", []))

        candidate_recall = _recall_at_k(candidate_ids, selected_ids, self.top_k)
        recall = _recall_at_k(expected_ids, selected_ids, self.top_k)
        precision = _precision_at_k(expected_ids, selected_ids, self.top_k)
        mrr = _mrr(expected_ids, selected_ids)
        ndcg = _ndcg_at_k(expected_ids, selected_ids, self.top_k)
        ranking = _pairwise_rank_accuracy(expected_ids, selected_ids)

        combined_ids = set(selected_ids) | set(context_ids)
        leak_count = sum(1 for fid in forbidden_ids if fid in combined_ids)
        leak_rate = _scope_leak_rate(forbidden_ids, selected_ids, context_ids)

        expected_scope_level = query.get("scope_level")
        scope_correct = True
        if expected_scope_level:
            # Scope is correct if at least one selected memory matches the expected level.
            scope_correct = any(
                m.scope_level.value == expected_scope_level
                for m in response.selected_memories
            )

        ctx_precision = _context_precision(expected_context_ids, context_ids)
        ctx_recall = _context_recall(expected_context_ids, context_ids)
        constraint_preservation = _constraint_preservation(
            required_constraints, response.context
        )
        budget_compliant = response.context.selected_tokens <= request.token_budget

        details = {
            "selected_memory_ids": selected_ids,
            "context_memory_ids": context_ids,
            "forbidden_ids": forbidden_ids,
            "leaked_ids": [fid for fid in forbidden_ids if fid in combined_ids],
            "intent_confidence": response.retrieval_plan.get("intent_confidence"),
            "enabled_channels": response.retrieval_plan.get("enabled_channels", []),
            "degraded_channels": response.degraded_channels,
            "completeness": response.completeness,
            "latency_ms": response.context.dropped_reasons.get("__latency_ms", 0.0),
        }

        return VNextRetrievalSampleResult(
            query_id=query["query_id"],
            query=query["query"],
            expected_intent=expected_intent,
            predicted_intent=predicted_intent,
            router_correct=router_correct,
            recall_at_k=recall,
            candidate_recall_at_k=candidate_recall,
            selected_precision=precision,
            selected_recall=recall,
            precision_at_k=precision,
            mrr=mrr,
            ndcg_at_k=ndcg,
            ranking_score=ranking,
            scope_leak_count=leak_count,
            scope_leak_rate=leak_rate,
            scope_correct=scope_correct,
            context_precision=ctx_precision,
            context_recall=ctx_recall,
            constraint_preservation=constraint_preservation,
            budget_compliant=budget_compliant,
            details=details,
        )

    @staticmethod
    def _build_request(query: dict[str, Any]) -> MemoryRetrievalRequest:
        intent_hint = query.get("intent_hint")
        scope_level = query.get("scope_level")
        return MemoryRetrievalRequest(
            request_id=query["query_id"],
            tenant_id=query.get("tenant_id", "tenant-a"),
            user_id=query.get("user_id", "user-1"),
            query=query["query"],
            task_id=query.get("task_id", ""),
            current_goal=query.get("current_goal", ""),
            current_step=query.get("current_step", ""),
            active_constraints=query.get("active_constraints", []),
            scope_level=MemoryScope(scope_level) if scope_level else None,
            scope=query.get("scope", ""),
            intent_hint=RetrievalIntent(intent_hint) if intent_hint else None,
            token_budget=query.get("token_budget", 2000),
            page_size=query.get("page_size", 10),
        )

    def _aggregate(
        self,
        sample_results: list[VNextRetrievalSampleResult],
    ) -> VNextRetrievalEvalReport:
        n = len(sample_results)
        if n == 0:
            return VNextRetrievalEvalReport(total_queries=0, sample_results=sample_results)

        router_intent_counts: dict[str, int] = {}
        for s in sample_results:
            key = s.predicted_intent
            router_intent_counts[key] = router_intent_counts.get(key, 0) + 1

        def mean(getter: Any) -> float:
            return sum(getter(s) for s in sample_results) / n

        return VNextRetrievalEvalReport(
            total_queries=n,
            router_accuracy=mean(lambda s: float(s.router_correct)),
            router_intent_counts=router_intent_counts,
            recall_at_k=mean(lambda s: s.recall_at_k),
            candidate_recall_at_k=mean(lambda s: s.candidate_recall_at_k),
            selected_precision=mean(lambda s: s.selected_precision),
            selected_recall=mean(lambda s: s.selected_recall),
            precision_at_k=mean(lambda s: s.precision_at_k),
            mrr=mean(lambda s: s.mrr),
            ndcg_at_k=mean(lambda s: s.ndcg_at_k),
            ranking_score=mean(lambda s: s.ranking_score),
            scope_leak_rate=mean(lambda s: s.scope_leak_rate),
            scope_accuracy=mean(lambda s: float(s.scope_correct)),
            context_precision=mean(lambda s: s.context_precision),
            context_recall=mean(lambda s: s.context_recall),
            constraint_preservation=mean(lambda s: s.constraint_preservation),
            budget_compliance=mean(lambda s: float(s.budget_compliant)),
            sample_results=sample_results,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_vnext_retrieval_eval(
    dataset_path: str | Path = "evaluation/showcase/datasets/vnext_retrieval_eval.json",
    output_path: str | Path | None = None,
) -> VNextRetrievalEvalReport:
    """Run the segmented retrieval evaluation from a dataset file."""
    dataset = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    service = build_vnext_retrieval_service_for_eval(dataset)
    evaluator = VNextRetrievalEvaluator(
        service,
        top_k=dataset.get("metadata", {}).get("top_k", DEFAULT_TOP_K),
        seed=dataset.get("metadata", {}).get("seed", 42),
    )
    report = evaluator.evaluate(dataset_path)
    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run vNext segmented retrieval evaluation")
    parser.add_argument(
        "--dataset",
        default="evaluation/showcase/datasets/vnext_retrieval_eval.json",
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = run_vnext_retrieval_eval(args.dataset, args.output)
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))


__all__ = [
    "RetrievalEvalSegment",
    "VNextRetrievalEvalReport",
    "VNextRetrievalEvaluator",
    "VNextRetrievalSampleResult",
    "build_vnext_retrieval_service_for_eval",
    "run_vnext_retrieval_eval",
]
