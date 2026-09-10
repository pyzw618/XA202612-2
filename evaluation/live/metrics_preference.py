"""偏好提取准确率（真机 LLM 路径）。

**为什么不走内置评测端点**

``POST /evaluate/preference`` 构造的是 ``PreferenceExtractor(llm_client=None)``
（``memoryhub/adapter/api.py``），即**只测规则路径**。真机上 LLM 是启用的，
跳过它测出来的数字不反映系统实际能力。本模块走真实写入链路
``POST /api/agent/step`` → 事件抽取 → 回读偏好，因此测的是线上真实行为。

**为什么比较是结构化的**

旧 showcase 数据集把 ``expected_output`` 写成抽取器的固定输出字符串，再用
子串匹配判分——同义改写会被判错，而抄来的标签必然判对。本模块按**规格**比较：

1. ``preference_type`` 必须落在允许集合；
2. ``payload.target`` 经同义词表归一化后相等；
3. ``payload.value`` 经归一化后相等；
4. ``is_global`` 仅在三态为 True/False 时断言。

文本相似度只作**诊断字段**记录，不参与判分——避免让模糊字符串比较左右得分。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Iterable

from evaluation.live.client import LiveClient, LiveClientError
from evaluation.live.seeding import EvalUser
from evaluation.live.stats import latency_summary, mean

#: 派生样本身份时的分隔符，与 ``evaluation.live.seeding.SEPARATOR`` 保持同风格。
SEPARATOR_CASE = "::"

#: payload.target 的同义词归一化表（规格级约定，不是实现细节）。
TARGET_SYNONYMS: dict[str, str] = {
    "output_format": "output_format", "format": "output_format",
    "data_format": "output_format", "输出格式": "output_format",
    "sensitive_data": "sensitive_data", "sensitive": "sensitive_data",
    "privacy": "sensitive_data", "敏感数据": "sensitive_data",
    "use_tool": "use_tool", "tool": "use_tool", "工具": "use_tool",
}

#: payload.value 的归一化表。
VALUE_SYNONYMS: dict[str, str] = {
    "markdown": "MARKDOWN", "md": "MARKDOWN",
    "html": "HTML", "json": "JSON", "xml": "XML", "csv": "CSV",
    "forbidden": "FORBIDDEN", "restricted": "FORBIDDEN", "deny": "FORBIDDEN",
}


def canonical_target(value: str) -> str:
    text = str(value or "").strip()
    return TARGET_SYNONYMS.get(text.lower(), text.lower())


def canonical_value(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return VALUE_SYNONYMS.get(text.lower(), text.upper() if text.lower() in VALUE_SYNONYMS else text.lower())


def _token_overlap(left: str, right: str) -> float:
    """字符级 Jaccard，仅作诊断。"""
    a, b = set(str(left or "")), set(str(right or ""))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_event(
    case_id: str, text: str, user: EvalUser, *, scene: str = "office"
) -> dict[str, Any]:
    """构造 ``/api/agent/step`` 所需的事件体。

    ``source_hash`` 必须每条唯一，否则写入路径会按 source_hash 去重而静默丢弃。
    """
    digest = hashlib.sha256(f"{user.run_tag}:{case_id}".encode("utf-8")).hexdigest()
    return {
        "event_id": f"ev_{digest[:16]}",
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": user.user_id,
        "session_id": f"s_{user.run_tag}_{case_id}",
        "turn_id": "t1",
        "scene": scene,
        "task_type": "eval.preference",
        "occurred_at": "2026-09-10T00:00:00Z",
        "text": text,
        "payload": {"action": "message"},
        "source_hash": digest,
        "quality": {
            "score": 1.0, "status": "accepted", "completeness": 1.0,
            "validity": 1.0, "consistency": 1.0, "freshness": 1.0, "issues": [],
        },
    }


def case_user(user: EvalUser, case_id: str) -> EvalUser:
    """为单条样本派生独立身份。

    **必须逐条隔离**：同一个用户下，后续偏好写会命中冲突/合并机制——它们的
    scope（scene + task_type）与 target 相同、只是 value 不同，于是被判定为
    MERGE/OVERRIDE，``preferences_written`` 返回空，样本被误判成"未抽取"。
    实测同一用户连写 4 条规则命中样本只有第 1 条上报，换成独立身份后 4 条全部
    正常。派生身份仍挂在运行前缀下，便于统一清理。
    """
    return EvalUser(
        user_id=f"{user.user_id}{SEPARATOR_CASE}{case_id}",
        run_tag=f"{user.run_tag}{SEPARATOR_CASE}{case_id}",
    )


def build_step_body(
    case_id: str, text: str, user: EvalUser, *, scene: str = "office"
) -> dict[str, Any]:
    """构造 ``/api/agent/step`` 请求体。

    **必须显式传 ``task_id``**：不传时它退化为 ``session_id``，而实测同一用户
    的第二个事件会返回非 ``COMMITTED``（事件落库了但 ``processing`` 为空，即
    完全不触发抽取）。显式给出互不相同的 ``task_id`` 后连续事件才能正常提交。
    这是驱动冲突评测的前提——冲突本来就需要对同一用户连续写入两次。
    """
    event = build_event(case_id, text, user, scene=scene)
    return {
        "session_id": event["session_id"],
        "turn_id": "t1",
        "task_id": f"task_{case_id}",
        "user_message": text,
        "scene": scene,
        "task_type": "eval.preference",
        "events": [event],
    }


def extract_preferences(
    client: LiveClient, case: dict[str, Any], user: EvalUser
) -> tuple[list[dict[str, Any]], str, float]:
    """驱动一次抽取，返回 ``(水合后的偏好列表, 错误, 端到端耗时ms)``。

    刻意**不**在事件里放 ``payload.preferences``：结构化载荷会被写入路径直接
    短路进存储、完全绕过抽取，从而得到一个"必对但无意义"的满分。
    """
    case_id = str(case.get("case_id", ""))
    user = case_user(user, case_id)
    payload = build_step_body(case_id, str(case.get("input_text", "")), user,
                              scene=str(case.get("scene") or "office"))
    event = payload["events"][0]
    try:
        started = time.perf_counter()
        response = client.agent_step(payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
    except LiveClientError as exc:
        return [], str(exc)[:200], 0.0

    written = list((response.get("processing") or {}).get("preferences_written") or [])
    hydrated: list[dict[str, Any]] = []
    for memory_id in written:
        try:
            hydrated.append(client.get_preference(memory_id, user_id=user.user_id))
        except LiveClientError:
            continue
    return hydrated, "", elapsed_ms


def compare_case(case: dict[str, Any], observed: list[dict[str, Any]]) -> dict[str, Any]:
    """按规格比较单条样本，返回判定详情。"""
    expected_found = bool(case.get("expected_found", True))
    found = bool(observed)

    result: dict[str, Any] = {
        "case_id": str(case.get("case_id", "")),
        "block": str(case.get("block", "")),
        "expected_found": expected_found,
        "found": found,
        "correct": False,
        "observed_count": len(observed),
        "matched_memory_id": "",
        "extract_sources": sorted({str(o.get("extract_source", "")) for o in observed}),
        "diagnostic_text_similarity": 0.0,
        "reason": "",
    }

    if not expected_found:
        result["correct"] = not found
        result["reason"] = "no_preference_expected" if not found else "over_extraction"
        return result

    if not found:
        result["reason"] = "nothing_extracted"
        return result

    allowed_types = set(case.get("expected_type_any_of") or [])
    expected_target = canonical_target(case.get("expected_target", ""))
    expected_value = canonical_value(case.get("expected_value", "")) if case.get("expected_value") else ""
    expected_global = case.get("expected_global")

    best_similarity = 0.0
    for preference in observed:
        pref_type = str(preference.get("preference_type", ""))
        payload = preference.get("payload") or {}
        similarity = _token_overlap(str(preference.get("text", "")), case.get("input_text", ""))
        best_similarity = max(best_similarity, similarity)

        if allowed_types and pref_type not in allowed_types:
            continue
        if expected_target and canonical_target(payload.get("target", "")) != expected_target:
            continue
        if expected_value and canonical_value(payload.get("value", "")) != expected_value:
            continue
        if expected_global is not None and bool(preference.get("is_global")) != bool(expected_global):
            continue
        result["correct"] = True
        result["matched_memory_id"] = str(preference.get("memory_id", ""))
        result["reason"] = "matched"
        break

    if not result["correct"]:
        result["reason"] = "fields_mismatch"
    result["diagnostic_text_similarity"] = round(best_similarity, 4)
    return result


def evaluate_preference(
    client: LiveClient,
    dataset: dict[str, Any],
    user: EvalUser,
    *,
    limit_per_block: int | None = None,
    blocks: Iterable[str] | None = None,
) -> dict[str, Any]:
    """对整份偏好数据集评分。"""
    wanted = set(blocks) if blocks else None
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in dataset.get("samples", []):
        block = str(case.get("block", "unknown"))
        if wanted and block not in wanted:
            continue
        grouped.setdefault(block, []).append(case)

    results: list[dict[str, Any]] = []
    latencies: list[float] = []
    errors: list[dict[str, Any]] = []
    for block, cases in sorted(grouped.items()):
        selected = cases[:limit_per_block] if limit_per_block else cases
        for case in selected:
            observed, error, elapsed_ms = extract_preferences(client, case, user)
            if error:
                errors.append({"case_id": case.get("case_id"), "error": error})
                continue
            latencies.append(elapsed_ms)
            results.append(compare_case(case, observed))

    by_block: dict[str, dict[str, Any]] = {}
    for block in sorted({r["block"] for r in results}):
        group = [r for r in results if r["block"] == block]
        by_block[block] = {
            "count": len(group),
            "accuracy": round(mean([1.0 if r["correct"] else 0.0 for r in group]), 4),
            "correct": sum(1 for r in group if r["correct"]),
        }

    by_type: dict[str, dict[str, Any]] = {}
    for result in results:
        case = next(
            (c for c in dataset.get("samples", []) if c.get("case_id") == result["case_id"]), {}
        )
        for pref_type in (case.get("expected_type_any_of") or ["(negative)"]):
            bucket = by_type.setdefault(pref_type, {"count": 0, "correct": 0})
            bucket["count"] += 1
            bucket["correct"] += 1 if result["correct"] else 0

    overall = round(mean([1.0 if r["correct"] else 0.0 for r in results]), 4) if results else 0.0
    return {
        "total_cases": len(results),
        "accuracy": overall,
        "by_block": by_block,
        "by_expected_type": {
            key: {**value, "accuracy": round(value["correct"] / value["count"], 4)}
            for key, value in sorted(by_type.items())
        },
        "over_extraction_count": sum(
            1 for r in results if r["reason"] == "over_extraction"
        ),
        "nothing_extracted_count": sum(
            1 for r in results if r["reason"] == "nothing_extracted"
        ),
        "field_mismatch_count": sum(
            1 for r in results if r["reason"] == "fields_mismatch"
        ),
        "errors": errors[:10],
        "latency": latency_summary(latencies),
        "sample_results": results[:60],
        "notes": (
            "accuracy 为四字段（type/target/value/global）全对的比例；"
            "diagnostic_text_similarity 仅供参考，不参与判分；"
            "by_block 中 llm_required 才是 LLM 路径的真实能力。"
        ),
    }
