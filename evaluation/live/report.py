"""四项指标报告：组装、渲染、落盘。

报告必须自带三样东西，否则读者无法判断数字是否可信：

1. **环境指纹**——证明跑的是 kylin + Milvus 真机，而不是进程内 mock；
2. **数据集溯源**——路径、SHA256、label_source，证明标签不是抄被测实现的输出；
3. **前置条件告警**——例如未配置 LLM 密钥时，偏好指标会退化为"规则覆盖度"，
   必须显式标注，避免读者把配置缺失误读成算法不行。

阈值判定采用"达标 / 未达标 / 未测量"三态：drive_failure 或无法测量的指标
不应被算作 0 分，也不能算作通过。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "memoryhub/live-four-metrics/v1"
EVIDENCE_LEVEL = "LIVE_HTTP"

PREFERENCE_TARGET = 0.85
RECALL_TARGET = 0.85
LATENCY_TARGET_MS = 500.0
CONFLICT_TARGET = 0.88


def _verdict(value: float | None, threshold: float, *, higher_is_better: bool = True) -> str:
    if value is None:
        return "未测量"
    if higher_is_better:
        return "达标" if value >= threshold else "未达标"
    return "达标" if value <= threshold else "未达标"


def build_metrics(
    *,
    preference: dict[str, Any] | None,
    retrieval: dict[str, Any] | None,
    latency: dict[str, Any] | None,
    conflict: dict[str, Any] | None,
    latency_phase: str = "cold_c1",
) -> list[dict[str, Any]]:
    """把四项结果整理成统一指标条目。"""
    metrics: list[dict[str, Any]] = []

    pref_value = preference.get("accuracy") if preference else None
    metrics.append({
        "name": "偏好提取准确率",
        "value": pref_value,
        "threshold": PREFERENCE_TARGET,
        "unit": "ratio",
        "verdict": _verdict(pref_value, PREFERENCE_TARGET),
        "sample_count": (preference or {}).get("total_cases"),
        "note": "含 LLM 隐式抽取路径；需同时看 by_block 的 llm_required 子项。",
    })

    recall_value = retrieval.get("recall_at_k") if retrieval else None
    metrics.append({
        "name": "知识检索召回率 Recall@K",
        "value": recall_value,
        "threshold": RECALL_TARGET,
        "unit": "ratio",
        "verdict": _verdict(recall_value, RECALL_TARGET),
        "sample_count": (retrieval or {}).get("scored_queries"),
        "note": "relevant 集合为等级≥2；no_answer 查询单独计 no_answer_precision。",
    })

    phase = (latency or {}).get("phases", {}).get(latency_phase, {})
    latency_value = phase.get("p95_ms") if phase else None
    metrics.append({
        "name": "知识检索响应时间 P95",
        "value": latency_value,
        "threshold": LATENCY_TARGET_MS,
        "unit": "ms",
        "verdict": _verdict(latency_value, LATENCY_TARGET_MS, higher_is_better=False),
        "sample_count": phase.get("count"),
        "note": f"取 {latency_phase}（并发 1、冷查询）的客户端端到端耗时，含 embedding 与网络。",
    })

    conflict_value = conflict.get("accuracy") if conflict else None
    metrics.append({
        "name": "知识冲突处理正确率",
        "value": conflict_value,
        "threshold": CONFLICT_TARGET,
        "unit": "ratio",
        "verdict": _verdict(conflict_value, CONFLICT_TARGET),
        "sample_count": (conflict or {}).get("scored_cases"),
        "note": (
            "仅在成功驱动的样本上计算；drive_failure 必须与决策错误分开解读。"
        ),
    })
    return metrics


def build_report(
    *,
    fingerprint: dict[str, Any],
    datasets: dict[str, Any],
    preference: dict[str, Any] | None,
    retrieval: dict[str, Any] | None,
    latency: dict[str, Any] | None,
    conflict: dict[str, Any] | None,
    readiness: dict[str, Any] | None = None,
    retrieval_unscoped: dict[str, Any] | None = None,
    preconditions: list[str] | None = None,
    request_summary: dict[str, Any] | None = None,
    notes: list[str] | None = None,
    latency_phase: str = "cold_c1",
) -> dict[str, Any]:
    metrics = build_metrics(
        preference=preference, retrieval=retrieval, latency=latency,
        conflict=conflict, latency_phase=latency_phase,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": EVIDENCE_LEVEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": fingerprint,
        "datasets": datasets,
        "preconditions": preconditions or [],
        "metrics": metrics,
        "all_thresholds_passed": all(m["verdict"] == "达标" for m in metrics),
        "readiness": readiness,
        "requests": request_summary,
        "details": {
            "preference": preference,
            "retrieval": retrieval,
            "retrieval_unscoped": retrieval_unscoped,
            "latency": latency,
            "conflict": conflict,
        },
        "notes": notes or [],
    }


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}ms" if unit == "ms" else f"{value * 100:.2f}%"


def render_markdown(report: dict[str, Any]) -> str:
    env = report["environment"]
    lines = [
        "# MemoryHub 四项指标真机评测报告",
        "",
        f"> 证据等级：**{report['evidence_level']}**  ",
        f"> 生成时间：{report['generated_at']}",
        "",
        "## 一、结果",
        "",
        "| 指标 | 实测 | 阈值 | 样本数 | 判定 |",
        "|---|---:|---:|---:|---|",
    ]
    for m in report["metrics"]:
        unit = m["unit"]
        threshold = f"≤ {m['threshold']:.0f}ms" if unit == "ms" else f"≥ {m['threshold'] * 100:.0f}%"
        lines.append(
            f"| {m['name']} | {_fmt(m['value'], unit)} | {threshold} | "
            f"{m['sample_count'] if m['sample_count'] is not None else '—'} | {m['verdict']} |"
        )

    lines += [
        "",
        "## 二、运行环境",
        "",
        f"- 服务地址：`{env.get('base_url', '')}`",
        f"- 运行模式：`{env.get('runtime_mode')}`",
        f"- Embedding：`{env.get('embedding', {}).get('provider')}` "
        f"{env.get('embedding', {}).get('dimension')} 维 "
        f"`{env.get('embedding', {}).get('model_name')}`",
        f"- 向量引擎：`{env.get('vector_engine', {}).get('provider')}` "
        f"（connected={env.get('vector_engine', {}).get('connected')}）",
        f"- 检索链路：`{env.get('retrieval', {}).get('type')}`",
    ]
    if report.get("requests"):
        lines.append(
            f"- 请求留痕：{report['requests'].get('total_requests')} 次，"
            f"served 观测值 {report['requests'].get('served_observed')}"
        )

    if report.get("preconditions"):
        lines += ["", "## 三、前置条件告警", ""]
        lines += [f"- ⚠️ {item}" for item in report["preconditions"]]

    if report.get("readiness"):
        r = report["readiness"]
        lines += [
            "", "## 四、语料就绪判定", "",
            f"- outbox 待投影 {r.get('outbox_pending')} / 失败 {r.get('outbox_failed')}",
            f"- canary 召回 {r.get('canary_recall')}（{r.get('canary_hits')}/{r.get('canary_sampled')}），"
            f"零结果 {r.get('canary_zero_results')} 次",
            f"- 结论：`{r.get('verdict')}`",
        ]

    lines += ["", "## 五、数据集溯源", "", "| 数据集 | SHA256 | label_source |", "|---|---|---|"]
    for name, prov in (report.get("datasets") or {}).items():
        lines.append(
            f"| {name} | `{str(prov.get('sha256', ''))[:16]}…` | `{prov.get('label_source', '')}` |"
        )

    if report.get("notes"):
        lines += ["", "## 六、说明", ""]
        lines += [f"- {n}" for n in report["notes"]]

    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], *, json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
