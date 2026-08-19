# -*- coding: utf-8 -*-
"""I-10 评测闭环测试（REFACTOR_PLAN_V2 §4.7 / PHASE_F）。

覆盖：
- PreferenceEvaluator.compute_metrics 已知结果；
- ConflictEvaluator 确定性决策场景；
- golden 数据集 run 返回 EvalReport；
- /evaluate/preference|conflict API 接入。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import EvalResult
from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig


@pytest.fixture()
def client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "eval.db"),
            vector_index_path=str(tmp_path / "v"),
            evidence_path=str(tmp_path / "e"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    with TestClient(create_app(config)) as c:
        yield c


def test_preference_compute_metrics_known():
    from evaluation.metrics.preference_eval import PreferenceEvaluator

    results = [
        EvalResult(sample_id="1", predicted="a", expected="a", correct=True),
        EvalResult(sample_id="2", predicted="b", expected="c", correct=False),
        EvalResult(sample_id="3", predicted="a", expected="a", correct=True),
        EvalResult(sample_id="4", predicted="a", expected="a", correct=True),
    ]
    metrics = PreferenceEvaluator().compute_metrics(results)
    assert metrics["accuracy"] == 0.75
    assert metrics["precision"] == 0.75
    assert metrics["recall"] == 0.75
    assert metrics["f1"] == 0.75


def test_conflict_resolution_deterministic():
    from memoryhub.core.preference.updater import (
        ConflictDetector,
        ConflictResolver,
    )
    from evaluation.metrics.conflict_eval import _pref

    detector = ConflictDetector(llm_client=None)
    resolver = ConflictResolver()

    # 相同偏好 → merge
    same = resolver.auto_resolve(
        _pref("周报使用 Markdown", 0, "office"),
        _pref("周报使用 Markdown", 1, "office"),
        detector,
    )
    assert same[0].value == "merge"

    # 显式反馈格式冲突 → override（与评测器 run() 一致：new 视为显式反馈）
    new_conflict = _pref("周报使用 Word", 1, "office")
    new_conflict.extract_source = "explicit_feedback"
    conflict = resolver.auto_resolve(
        _pref("周报使用 Markdown", 0, "office"),
        new_conflict,
        detector,
    )
    assert conflict[0].value == "override"


def test_preference_golden_run_returns_report(tmp_path):
    from evaluation.metrics.preference_eval import PreferenceEvaluator

    # 写入内联数据集（含 metadata + samples 两种形态）
    ds = tmp_path / "pref.json"
    ds.write_text(
        '{"metadata": {"dataset_id": "t"}, "samples": ['
        '{"sample_id": "p1", "input_text": "以后都用 Markdown 写周报", '
        '"expected_output": "偏好使用 MARKDOWN 格式进行数据输出。", '
        '"expected_type": "format_preference", "scene": "office"}]}',
        encoding="utf-8",
    )
    report = PreferenceEvaluator().run(str(ds))
    assert report.task_name == "preference_extraction"
    assert report.total_samples == 1
    assert report.accuracy == 1.0


def test_api_evaluate_preference_and_conflict(client: TestClient) -> None:
    """/evaluate/preference|conflict 接入 golden 数据集返回 EvalReport。"""
    pref_path = "evaluation/datasets/preference_golden_v1.json"
    conflict_path = "evaluation/datasets/conflict_golden_v1.json"

    r = client.post("/api/memory/evaluate/preference", params={"dataset_path": pref_path})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_name"] == "preference_extraction"
    assert body["total_samples"] >= 5
    assert body["accuracy"] >= 0.85

    r = client.post("/api/memory/evaluate/conflict", params={"dataset_path": conflict_path})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_name"] == "conflict"
    assert body["total_samples"] >= 5
    assert body["accuracy"] >= 0.88
