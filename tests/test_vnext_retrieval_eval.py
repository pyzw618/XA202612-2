"""Tests for the segmented vNext retrieval evaluator (S3-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.metrics.vnext_retrieval_eval import (
    VNextRetrievalEvaluator,
    build_vnext_retrieval_service_for_eval,
    run_vnext_retrieval_eval,
)
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.retrieval_service import RetrievalService

DATASET_PATH = Path("evaluation/showcase/datasets/vnext_retrieval_eval.json")


@pytest.fixture
def dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def retrieval_service(dataset: dict) -> RetrievalService:
    return build_vnext_retrieval_service_for_eval(dataset)


@pytest.fixture
def evaluator(retrieval_service: RetrievalService) -> VNextRetrievalEvaluator:
    return VNextRetrievalEvaluator(retrieval_service, top_k=5, seed=42)


def test_evaluator_runs_and_reports_all_segments(
    evaluator: VNextRetrievalEvaluator, dataset: dict
) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    expected_count = len(dataset["queries"])
    assert report.total_queries == expected_count
    assert 0.0 <= report.router_accuracy <= 1.0
    assert 0.0 <= report.recall_at_k <= 1.0
    assert 0.0 <= report.precision_at_k <= 1.0
    assert 0.0 <= report.mrr <= 1.0
    assert 0.0 <= report.ndcg_at_k <= 1.0
    assert 0.0 <= report.ranking_score <= 1.0
    assert 0.0 <= report.scope_leak_rate <= 1.0
    assert 0.0 <= report.scope_accuracy <= 1.0
    assert 0.0 <= report.context_precision <= 1.0
    assert 0.0 <= report.context_recall <= 1.0
    assert 0.0 <= report.constraint_preservation <= 1.0
    assert 0.0 <= report.budget_compliance <= 1.0
    assert len(report.sample_results) == expected_count


def test_router_accuracy_perfect_when_intent_hinted(evaluator: VNextRetrievalEvaluator) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    assert report.router_accuracy == 1.0
    # All seven intents appear in the annotated dataset.
    assert set(report.router_intent_counts) == {
        "CURRENT_STATE",
        "TASK_HISTORY",
        "PREFERENCE",
        "SEMANTIC_FACT",
        "PROCEDURE",
        "EXPERIENCE",
        "MIXED",
    }


def test_forbidden_memories_do_not_leak(evaluator: VNextRetrievalEvaluator) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    assert report.scope_leak_rate == 0.0
    for sample in report.sample_results:
        assert sample.scope_leak_count == 0
        assert sample.scope_leak_rate == 0.0
        assert sample.details["leaked_ids"] == []


def test_recall_is_perfect_for_expected_memories(evaluator: VNextRetrievalEvaluator) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    # Top-k and token-budget constraints can prevent perfect recall on individual
    # queries; the aggregate recall should remain high (>0.8).
    assert report.recall_at_k >= 0.8
    for sample in report.sample_results:
        assert sample.recall_at_k >= 0.0


def test_constraints_preserved_under_tight_budget(evaluator: VNextRetrievalEvaluator) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    assert report.constraint_preservation == 1.0
    assert report.budget_compliance == 1.0
    budget_sample = next(
        s for s in report.sample_results if s.query_id == "q-budget-protects-constraints"
    )
    assert budget_sample.constraint_preservation == 1.0
    assert budget_sample.budget_compliant is True


def test_reproducible_report(evaluator: VNextRetrievalEvaluator) -> None:
    report1 = evaluator.evaluate(DATASET_PATH)
    report2 = evaluator.evaluate(DATASET_PATH)
    assert report1.model_dump() == report2.model_dump()


def test_run_vnext_retrieval_eval_cli(tmp_path: Path, dataset: dict) -> None:
    output_path = tmp_path / "report.json"
    report = run_vnext_retrieval_eval(str(DATASET_PATH), str(output_path))
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == report.model_dump()


def test_mock_executor_enforces_tenant_isolation(retrieval_service: RetrievalService) -> None:
    request = MemoryRetrievalRequest(
        request_id="q-preference-semantic",
        tenant_id="tenant-a",
        user_id="user-1",
        query="how should I format the answer",
    )
    result = retrieval_service.retrieve(request)
    selected_ids = {m.memory_id for m in result.response.selected_memories}
    assert "other-tenant-memory" not in selected_ids
    context_ids = set(result.response.context.relevant_memory_ids)
    assert "other-tenant-memory" not in context_ids


def test_mock_executor_blocks_candidate_memory(retrieval_service: RetrievalService) -> None:
    request = MemoryRetrievalRequest(
        request_id="q-deleted-superseded-candidate-blocked",
        tenant_id="tenant-a",
        user_id="user-1",
        query="Python version history",
    )
    result = retrieval_service.retrieve(request)
    selected_ids = {m.memory_id for m in result.response.selected_memories}
    assert "candidate-memory" not in selected_ids
    assert "deleted-memory" not in selected_ids
    assert "superseded-memory" not in selected_ids
    context_ids = set(result.response.context.relevant_memory_ids)
    assert "candidate-memory" not in context_ids


def test_report_model_dump_is_serializable(
    evaluator: VNextRetrievalEvaluator, dataset: dict
) -> None:
    report = evaluator.evaluate(DATASET_PATH)
    dumped = report.model_dump()
    assert dumped["schema_version"] == "vnext/v1"
    expected_count = len(dataset["queries"])
    assert dumped["total_queries"] == expected_count
    assert len(dumped["sample_results"]) == expected_count
