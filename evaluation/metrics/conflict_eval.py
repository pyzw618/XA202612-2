"""
冲突处理评测模块

评测冲突检测和解决的正确率。
REFACTOR_PLAN_V2 §4.7.3（Phase F / I-10）：基于 PreferenceUpdater 的
ConflictDetector + ConflictResolver.auto_resolve，填实空壳评测器。
"""

from __future__ import annotations

import json
import re
import statistics
import time

from memoryhub.adapter.schemas import (
    ConflictDecision,
    EvalReport,
    EvalResult,
    MemoryStatus,
    PreferenceMemory,
    PreferenceType,
    SceneScope,
)


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _pref(text: str, idx: int, scene: str) -> PreferenceMemory:
    """把评测样本的偏好文本构造成 PreferenceMemory。

    从文本中抽取格式关键词（markdown/html/json/xml/csv/word…）作为
    payload value，使"周报用 Markdown" vs "周报用 Word" 等形成真实可检测
    的语义冲突；无格式关键词时退回整句文本归一化。
    """
    m = re.search(
        r"(markdown|html|json|xml|csv|word|txt|纯文本)",
        text or "",
        re.IGNORECASE,
    )
    value = m.group(1).lower() if m else (text or "").strip().lower()
    return PreferenceMemory(
        memory_id=f"eval_pref_{idx}",
        user_id="eval_user",
        preference_type=PreferenceType.OUTPUT_STYLE,
        text=text or "",
        payload={"target": "output_format", "value": value},
        scope=SceneScope(scene=scene, task_type="eval.task"),
        is_global=False,
        status=MemoryStatus.ACTIVE,
    )


class ConflictEvaluator:
    """
    冲突处理评测器

    使用方式:
        evaluator = ConflictEvaluator(detector, resolver)
        report = evaluator.run("evaluation/showcase/datasets/conflict_golden_v1.json")
    """

    def __init__(self, conflict_detector=None, conflict_resolver=None):
        # 默认使用生产偏好冲突链路（REFACTOR_PLAN_V2 §4.7.3）
        self.detector = conflict_detector
        self.resolver = conflict_resolver

    def _ensure_components(self):
        if self.resolver is None or self.detector is None:
            from memoryhub.core.preference.updater import (
                ConflictDetector,
                ConflictResolver,
            )

            if self.detector is None:
                self.detector = ConflictDetector(llm_client=None)
            if self.resolver is None:
                self.resolver = ConflictResolver()
        return self.detector, self.resolver

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行冲突处理评测

        测试数据集格式:
            [
                {
                    "sample_id": "s001",
                    "old_preference": "项目周报默认使用 Markdown",
                    "new_preference": "以后周报改成 Word",
                    "expected_decision": "override",
                    "scene": "office",
                    "expected_conflict": true
                },
                ...
            ]
        """
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        samples = data["samples"] if isinstance(data, dict) and "samples" in data else data

        results: list[EvalResult] = []
        for idx, sample in enumerate(samples):
            scene = sample.get("scene", "office")
            old_pref = _pref(sample.get("old_preference", ""), idx, scene)
            new_pref = _pref(sample.get("new_preference", ""), idx + 1000, scene)
            new_pref.extract_source = "explicit_feedback"  # 冲突样本视为显式反馈
            started = time.perf_counter()
            decision, _reason = self._ensure_components()[1].auto_resolve(
                old_pref, new_pref, self._ensure_components()[0]
            )
            latency_ms = (time.perf_counter() - started) * 1000
            expected = str(sample.get("expected_decision", "")).strip()
            decision_value = getattr(decision, "value", str(decision))
            results.append(
                EvalResult(
                    sample_id=str(sample.get("sample_id", idx)),
                    predicted=decision_value,
                    expected=expected,
                    correct=bool(expected) and decision_value == expected,
                    latency_ms=round(latency_ms, 3),
                )
            )

        resolution_metrics = self._compute_resolution(results)
        return EvalReport(
            task_name="conflict",
            total_samples=len(results),
            accuracy=resolution_metrics["resolution_accuracy"],
            avg_latency_ms=resolution_metrics["avg_latency_ms"],
            p95_latency_ms=_percentile([r.latency_ms for r in results], 95),
            details=results,
        )

    def evaluate_detection(self, dataset_path: str) -> dict:
        """
        评测冲突检测准确率（样本可选带 expected_conflict 布尔标注）。
        """
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        samples = data["samples"] if isinstance(data, dict) and "samples" in data else data
        tp = tn = fp = fn = 0
        for idx, sample in enumerate(samples):
            if "expected_conflict" not in sample:
                continue
            scene = sample.get("scene", "office")
            old_pref = _pref(sample.get("old_preference", ""), idx, scene)
            new_pref = _pref(sample.get("new_preference", ""), idx + 1000, scene)
            detected = bool(
                self._ensure_components()[0].check_preference(old_pref, new_pref)
            )
            expected = bool(sample["expected_conflict"])
            if detected and expected:
                tp += 1
            elif detected and not expected:
                fp += 1
            elif not detected and expected:
                fn += 1
            else:
                tn += 1
        total = tp + tn + fp + fn
        return {
            "detection_accuracy": round((tp + tn) / total, 4) if total else 0.0,
            "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        }

    def evaluate_resolution(self, dataset_path: str) -> dict:
        """评测冲突解决正确率。"""
        report = self.run(dataset_path)
        return {"resolution_accuracy": round(report.accuracy, 4)}

    @staticmethod
    def _compute_resolution(results: list[EvalResult]) -> dict:
        if not results:
            return {"resolution_accuracy": 0.0, "avg_latency_ms": 0.0}
        correct = sum(1 for r in results if r.correct)
        return {
            "resolution_accuracy": round(correct / len(results), 4),
            "avg_latency_ms": round(
                statistics.mean([r.latency_ms for r in results]), 3
            ),
        }
