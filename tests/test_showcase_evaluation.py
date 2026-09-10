from __future__ import annotations

import json
from pathlib import Path

from evaluation.showcase.run import build_report, render_markdown


def test_showcase_report_contains_all_four_metrics() -> None:
    report = build_report(config_path=Path("config.yaml"), repeats=1)

    assert report["evidence_level"] == "DEMONSTRATION_ONLY"
    assert len(report["metrics"]) == 4
    assert {item["name"] for item in report["metrics"]} == {
        "偏好提取准确率",
        "知识检索召回率 Recall@K",
        "知识检索响应时间 P95",
        "知识冲突处理正确率",
    }
    assert report["details"]["latency"]["sample_count"] == report["details"]["retrieval"]["total_queries"]
    assert "DEMONSTRATION_ONLY" in render_markdown(report)
    json.dumps(report, ensure_ascii=False)
