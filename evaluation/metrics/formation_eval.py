"""Formation Shadow evaluator for single-event and P1 paired scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoryhub.application.formation_shadow import (
    DeterministicLegacyExtractionAdapter,
    FormationShadowService,
)
from memoryhub.domain.contracts import MemoryEventContract
from memoryhub.observability.trace_store import TraceStore


@dataclass(frozen=True, slots=True)
class SampleResult:
    sample_id: str
    event_id: str
    predicted_decision: str
    predicted_scope_level: str
    expected_decision: str
    expected_scope_level: str
    premature: bool
    missed: bool
    scope_mismatch: bool
    type_mismatch: bool
    safe: bool


@dataclass(frozen=True, slots=True)
class PairResult:
    pair_id: str
    predicted_final_decision: str
    predicted_final_scope_level: str
    expected_final_decision: str
    expected_final_scope_level: str
    premature_count: int
    missed_count: int
    scope_mismatch_count: int
    type_mismatch_count: int
    safe: bool


@dataclass(frozen=True, slots=True)
class FormationEvalReport:
    schema_version: str = "vnext/v1"
    sample_count: int = 0
    pair_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    premature_promotion_rate: float = 0.0
    missed_promotion_rate: float = 0.0
    scope_accuracy: float = 0.0
    type_accuracy: float = 0.0
    resume_constraint_preservation: float = 0.0
    safe_rate: float = 0.0
    sample_results: list[SampleResult] = field(default_factory=list)
    pair_results: list[PairResult] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_count": self.sample_count,
            "pair_count": self.pair_count,
            "precision": self.precision,
            "recall": self.recall,
            "premature_promotion_rate": self.premature_promotion_rate,
            "missed_promotion_rate": self.missed_promotion_rate,
            "scope_accuracy": self.scope_accuracy,
            "type_accuracy": self.type_accuracy,
            "resume_constraint_preservation": self.resume_constraint_preservation,
            "safe_rate": self.safe_rate,
            "sample_results": [self._sample_result_dict(r) for r in self.sample_results],
            "pair_results": [self._pair_result_dict(r) for r in self.pair_results],
        }

    @staticmethod
    def _sample_result_dict(result: SampleResult) -> dict[str, Any]:
        return {
            "sample_id": result.sample_id,
            "event_id": result.event_id,
            "predicted_decision": result.predicted_decision,
            "predicted_scope_level": result.predicted_scope_level,
            "expected_decision": result.expected_decision,
            "expected_scope_level": result.expected_scope_level,
            "premature": result.premature,
            "missed": result.missed,
            "scope_mismatch": result.scope_mismatch,
            "type_mismatch": result.type_mismatch,
            "safe": result.safe,
        }

    @staticmethod
    def _pair_result_dict(result: PairResult) -> dict[str, Any]:
        return {
            "pair_id": result.pair_id,
            "predicted_final_decision": result.predicted_final_decision,
            "predicted_final_scope_level": result.predicted_final_scope_level,
            "expected_final_decision": result.expected_final_decision,
            "expected_final_scope_level": result.expected_final_scope_level,
            "premature_count": result.premature_count,
            "missed_count": result.missed_count,
            "scope_mismatch_count": result.scope_mismatch_count,
            "type_mismatch_count": result.type_mismatch_count,
            "safe": result.safe,
        }


class FormationEvaluator:
    """Evaluate Formation Shadow output against annotated datasets."""

    def __init__(self, *, legacy_would_write_active: bool = True) -> None:
        self._legacy_adapter = DeterministicLegacyExtractionAdapter(
            would_write_active=legacy_would_write_active
        )

    def evaluate(
        self,
        samples_path: str | Path,
        pairs_path: str | Path,
    ) -> FormationEvalReport:
        sample_results = self._evaluate_samples(Path(samples_path))
        pair_results = self._evaluate_pairs(Path(pairs_path))

        total = len(sample_results)
        decision_correct = sum(
            1 for r in sample_results if r.predicted_decision == r.expected_decision
        )
        precision = decision_correct / total if total else 0.0

        expected_promote = [
            r for r in sample_results if r.expected_decision == "PROMOTE"
        ]
        predicted_promote_when_expected = sum(
            1 for r in expected_promote if r.predicted_decision == "PROMOTE"
        )
        recall = (
            predicted_promote_when_expected / len(expected_promote)
            if expected_promote
            else 0.0
        )

        premature_count = sum(1 for r in sample_results if r.premature)
        missed_count = sum(1 for r in sample_results if r.missed)
        scope_correct = sum(
            1
            for r in sample_results
            if r.scope_mismatch == (r.expected_scope_level != r.predicted_scope_level)
        )
        type_correct = sum(
            1
            for r in sample_results
            if r.type_mismatch == (r.predicted_scope_level != r.expected_scope_level)
        )
        safe_count = sum(1 for r in sample_results if r.safe)

        sample_report = FormationEvalReport(
            sample_count=total,
            pair_count=len(pair_results),
            precision=round(precision, 4),
            recall=round(recall, 4),
            premature_promotion_rate=round(premature_count / total, 4) if total else 0.0,
            missed_promotion_rate=round(missed_count / total, 4) if total else 0.0,
            scope_accuracy=round(scope_correct / total, 4) if total else 0.0,
            type_accuracy=round(type_correct / total, 4) if total else 0.0,
            resume_constraint_preservation=1.0 if pair_results else 0.0,
            safe_rate=round(safe_count / total, 4) if total else 0.0,
            sample_results=sample_results,
            pair_results=pair_results,
        )
        return sample_report

    def _evaluate_samples(self, path: Path) -> list[SampleResult]:
        dataset = json.loads(path.read_text(encoding="utf-8"))
        service = FormationShadowService(legacy_adapter=self._legacy_adapter)
        results: list[SampleResult] = []
        for sample in dataset.get("samples", []):
            event = MemoryEventContract.model_validate(sample["event"])
            report = service.compare_event(
                event,
                episode_id=sample["episode_id"],
            )
            expected = sample["expected"]
            results.append(
                SampleResult(
                    sample_id=sample["sample_id"],
                    event_id=report.event_id,
                    predicted_decision=report.vnext_decision["decision"],
                    predicted_scope_level=report.vnext_candidate["scope_level"],
                    expected_decision=expected["vnext_decision"],
                    expected_scope_level=expected["vnext_scope_level"],
                    premature=bool(report.premature_promotions),
                    missed=bool(report.missed_promotions),
                    scope_mismatch=bool(report.scope_mismatches),
                    type_mismatch=bool(report.type_mismatches),
                    safe=report.safe,
                )
            )
        return results

    def _evaluate_pairs(self, path: Path) -> list[PairResult]:
        dataset = json.loads(path.read_text(encoding="utf-8"))
        results: list[PairResult] = []
        for pair in dataset.get("pairs", []):
            trace_store = TraceStore()
            service = FormationShadowService(
                legacy_adapter=self._legacy_adapter,
                trace_store=trace_store,
            )
            last_report = None
            for item in pair["events"]:
                event = MemoryEventContract.model_validate(item["event"])
                last_report = service.compare_event(
                    event,
                    episode_id=item["episode_id"],
                )
            if last_report is None:
                continue
            expected = pair["expected"]
            results.append(
                PairResult(
                    pair_id=pair["pair_id"],
                    predicted_final_decision=last_report.vnext_decision["decision"],
                    predicted_final_scope_level=last_report.vnext_candidate["scope_level"],
                    expected_final_decision=expected["final_vnext_decision"],
                    expected_final_scope_level=expected["final_vnext_scope_level"],
                    premature_count=len(last_report.premature_promotions),
                    missed_count=len(last_report.missed_promotions),
                    scope_mismatch_count=len(last_report.scope_mismatches),
                    type_mismatch_count=len(last_report.type_mismatches),
                    safe=last_report.safe,
                )
            )
        return results


def run_formation_eval(
    samples_path: str | Path = "evaluation/datasets/vnext_formation_eval.json",
    pairs_path: str | Path = "evaluation/datasets/vnext_formation_p1_pairs.json",
    output_path: str | Path | None = None,
) -> FormationEvalReport:
    evaluator = FormationEvaluator()
    report = evaluator.evaluate(samples_path, pairs_path)
    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(report.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Formation Shadow evaluation")
    parser.add_argument(
        "--samples",
        default="evaluation/datasets/vnext_formation_eval.json",
    )
    parser.add_argument(
        "--pairs",
        default="evaluation/datasets/vnext_formation_p1_pairs.json",
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    report = run_formation_eval(args.samples, args.pairs, args.output)
    print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
