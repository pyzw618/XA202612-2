from __future__ import annotations

from pathlib import Path

from evaluation.metrics.formation_eval import (
    FormationEvaluator,
    run_formation_eval,
)

ROOT = Path(__file__).parents[1]
SAMPLES = ROOT / "evaluation" / "datasets" / "vnext_formation_eval.json"
PAIRS = ROOT / "evaluation" / "datasets" / "vnext_formation_p1_pairs.json"


def test_evaluator_loads_and_scores_samples() -> None:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(SAMPLES, PAIRS)

    assert report.sample_count == 4
    assert report.pair_count == 3
    assert 0.0 <= report.precision <= 1.0
    assert 0.0 <= report.recall <= 1.0
    assert 0.0 <= report.premature_promotion_rate <= 1.0
    assert 0.0 <= report.safe_rate <= 1.0


def test_sample_results_match_expected_shape() -> None:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(SAMPLES, PAIRS)

    for result in report.sample_results:
        assert result.sample_id
        assert result.predicted_decision in {"PROMOTE", "REVIEW", "REJECT"}
        assert result.expected_decision in {"PROMOTE", "REVIEW", "REJECT"}


def test_pair_results_cover_p1_scenarios() -> None:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(SAMPLES, PAIRS)

    pair_ids = {r.pair_id for r in report.pair_results}
    assert "E2E-P1-01" in pair_ids
    assert "E2E-P1-03" in pair_ids
    assert "E2E-P1-06" in pair_ids

    for result in report.pair_results:
        assert result.predicted_final_decision in {"PROMOTE", "REVIEW", "REJECT"}
        assert result.expected_final_decision in {"PROMOTE", "REVIEW", "REJECT"}


def test_pair_expected_matches_predicted() -> None:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(SAMPLES, PAIRS)

    for result in report.pair_results:
        assert result.predicted_final_decision == result.expected_final_decision
        assert result.predicted_final_scope_level == result.expected_final_scope_level


def test_sample_expected_matches_predicted() -> None:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(SAMPLES, PAIRS)

    for result in report.sample_results:
        assert result.predicted_decision == result.expected_decision
        assert result.predicted_scope_level == result.expected_scope_level


def test_run_formation_eval_cli_shape() -> None:
    report = run_formation_eval(str(SAMPLES), str(PAIRS))
    dump = report.model_dump()
    assert "sample_count" in dump
    assert "pair_count" in dump
    assert "precision" in dump
    assert "safe_rate" in dump
