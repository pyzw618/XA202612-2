"""
偏好提取评测模块

评测偏好提取的准确率、精确率、召回率、F1。
REFACTOR_PLAN_V2 §4.7.2（Phase F / I-10）：填实空壳评测器。
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time

from memoryhub.adapter.schemas import (
    EvalReport,
    EvalResult,
    EvalSample,
    EventQuality,
    MemoryEvent,
    QualityStatus,
    SourceType,
)
from memoryhub.core.preference.extractor import PreferenceExtractor


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _build_event(sample: EvalSample) -> MemoryEvent:
    """把评测样本构造成 MemoryEvent（规则抽取无需 LLM 即可产出偏好）。"""
    scene = sample.scene or "office"
    return MemoryEvent(
        event_id=f"eval_{sample.sample_id}",
        user_id="eval_user",
        session_id="eval_session",
        scene=scene,
        task_type="eval.task",
        source_type=SourceType.USER_BEHAVIOR,
        event_type="user_message",
        text=sample.input_text,
        occurred_at="2026-01-01T00:00:00Z",
        source_hash=hashlib.sha256(sample.input_text.encode()).hexdigest(),
        payload={"action": "message"},
        quality=EventQuality(
            score=1.0,
            status=QualityStatus.ACCEPTED,
            completeness=1.0,
            validity=1.0,
            consistency=1.0,
            freshness=1.0,
            issues=[],
        ),
    )


class PreferenceEvaluator:
    """
    偏好提取评测器

    使用方式:
        evaluator = PreferenceEvaluator(extractor)
        report = evaluator.run("evaluation/showcase/datasets/preference_golden_v1.json")
    """

    def __init__(self, preference_extractor=None):
        """
        参数:
            preference_extractor: PreferenceExtractor 实例
        """
        self.extractor = preference_extractor or PreferenceExtractor(llm_client=None)

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行偏好提取评测

        测试数据集格式:
            [
                {
                    "sample_id": "s001",
                    "input_text": "以后都用 Markdown 写周报",
                    "expected_output": "项目周报默认使用 Markdown",
                    "expected_type": "format_preference",
                    "scene": "office"
                },
                ...
            ]
        """
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        samples = data["samples"] if isinstance(data, dict) and "samples" in data else data
        results = [
            self.evaluate_single(EvalSample(**sample)) for sample in samples
        ]
        metrics = self.compute_metrics(results)
        return EvalReport(
            task_name="preference_extraction",
            total_samples=len(results),
            accuracy=metrics["accuracy"],
            precision=metrics["precision"],
            recall=metrics["recall"],
            f1=metrics["f1"],
            avg_latency_ms=metrics["avg_latency_ms"],
            p95_latency_ms=_percentile([r.latency_ms for r in results], 95),
            details=results,
        )

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """
        评测单条样本：提取指定偏好类型，与期望类型/输出对比。
        """
        started = time.perf_counter()
        event = _build_event(sample)
        predicted_text, predicted_type, found = "", "", False
        for memory in self.extractor.extract(event):
            if not memory:
                continue
            predicted_type = getattr(memory.preference_type, "value", str(memory.preference_type))
            predicted_text = str(getattr(memory, "text", "") or "")
            found = True
            break  # 取首选偏好

        latency_ms = (time.perf_counter() - started) * 1000

        expected_type = (sample.expected_type or "").strip()
        expected_output = (sample.expected_output or "").strip().lower()
        type_ok = found and (not expected_type or predicted_type == expected_type)
        output_ok = found and (
            not expected_output
            or expected_output in predicted_text.lower()
            or predicted_text.lower() in expected_output
            or _normalize(predicted_text) == _normalize(sample.expected_output)
        )
        # Negative/neutral golden rows explicitly assert that no preference is
        # expected; absence is a correct result, not a missed extraction.
        expected_found = getattr(sample, "expected_found", True)
        correct = (not expected_found and not found) or (expected_found and found and type_ok and output_ok)
        return EvalResult(
            sample_id=sample.sample_id,
            predicted=predicted_text,
            expected=sample.expected_output,
            correct=correct,
            latency_ms=round(latency_ms, 3),
        )

    def compute_metrics(self, results: list[EvalResult]) -> dict:
        """
        计算汇总指标：精确匹配（type+output 全对）= 命中。
        """
        n = len(results)
        if n == 0:
            return {
                "accuracy": 0.0, "precision": 0.0, "recall": 0.0,
                "f1": 0.0, "avg_latency_ms": 0.0,
            }
        hits = sum(1 for r in results if r.correct)
        precision = recall = accuracy = hits / n
        f1 = (
            (2 * precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        return {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "avg_latency_ms": round(
                statistics.mean([r.latency_ms for r in results]), 3
            ),
        }


def _normalize(text: str) -> str:
    return "".join(str(text or "").split()).lower()
