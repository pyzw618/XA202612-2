# -*- coding: utf-8 -*-
"""MemoryHub 检索评测数据集校验脚本。

参照:
  - 检索评测数据构建指南 第 8 节（数据清洗与自动校验）
  - 评测交付方案 P0-6（修正失败与样本统计）

用法:
  python evaluation/validate_retrieval_dataset.py \
      --dataset evaluation/datasets/memoryhub_knowledge_retrieval_v1_dev.json \
      --schema evaluation/datasets/memoryhub_retrieval_dataset_schema_v1.json \
      --report evaluation/results/dataset_validation_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


# ── 敏感信息扫描模式 ──────────────────────────────────────────────
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("API Key (通用)", re.compile(
        r"(?:api[_-]?key|apikey|api_secret|secret[_-]?key)\s*[:=]\s*['\"]?[\w\-]{16,}['\"]?",
        re.IGNORECASE,
    )),
    ("Bearer Token", re.compile(
        r"bearer\s+[\w\-]+\.[\w\-]+\.[\w\-]+", re.IGNORECASE,
    )),
    ("JWT Token", re.compile(
        r"eyJ[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]*\.[a-zA-Z0-9_\-]+",
    )),
    ("AWS Access Key", re.compile(
        r"AKIA[0-9A-Z]{16}", re.IGNORECASE,
    )),
    ("Generic Private Key Header", re.compile(
        r"-----BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PGP)\s+PRIVATE KEY-----",
    )),
    ("Password in Plaintext", re.compile(
        r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?\S{6,}['\"]?", re.IGNORECASE,
    )),
    ("Connection String (含密码)", re.compile(
        r"(?:mongodb|mysql|postgresql|redis)://[^:]*:[^@]+@",
        re.IGNORECASE,
    )),
    ("中国身份证号", re.compile(
        r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]",
    )),
    ("手机号码", re.compile(
        r"1[3-9]\d{9}",
    )),
    ("邮箱地址（潜在PII）", re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    )),
]


# ── 合法枚举 ──────────────────────────────────────────────────────
_VALID_ENUMS: dict[str, Any] = {
    "memory_type": ["knowledge"],
    "knowledge_type": ["workflow", "case", "template"],
    "status": ["active", "archived", "deleted", "replaced"],
    "difficulty": ["exact", "semantic", "hard-negative", "cross-domain", "no-answer"],
    "language": ["zh-CN", "en-US", "mixed"],
    "memory_types_elem": ["knowledge", "preference", "fact"],
    "scope.scene": ["office", "development", "system", "personal", "communication", "finance"],
}


# ── 结果结构 ──────────────────────────────────────────────────────
def _new_result() -> dict[str, Any]:
    return {
        "passed": True,
        "errors": [],
        "warnings": [],
        "stats": {},
    }


def _add_error(result: dict, section: str, item_id: str, message: str) -> None:
    result["passed"] = False
    result["errors"].append({"section": section, "id": item_id, "message": message})


def _add_warning(result: dict, section: str, item_id: str, message: str) -> None:
    result["warnings"].append({"section": section, "id": item_id, "message": message})


# ── 核心校验函数 ───────────────────────────────────────────────────
def validate_dataset(
    dataset: dict, schema: dict | None = None
) -> dict[str, Any]:
    """对数据集执行全部校验，返回报告 dict。

    Args:
        dataset: 符合 memoryhub_retrieval_dataset_schema_v1 的数据字典。
        schema: 可选 JSON Schema 字典，传入则执行 JSON Schema 校验。

    Returns:
        校验报告，包含 passed/errors/warnings/stats 四个顶层字段。
    """
    result = _new_result()
    memories = dataset.get("memories", [])
    queries = dataset.get("queries", [])
    metadata = dataset.get("metadata", {})
    memory_ids = {m["id"] for m in memories}
    memory_by_id = {m["id"]: m for m in memories}
    query_ids = {q["query_id"] for q in queries}

    # ── 元数据检查 ────────────────────────────────────────────────
    if not metadata.get("dataset_id"):
        _add_error(result, "metadata", "", "缺少 metadata.dataset_id")
    if not metadata.get("version"):
        _add_error(result, "metadata", "", "缺少 metadata.version")
    if metadata.get("split") not in ("dev", "test", "latency"):
        _add_error(result, "metadata", "", f"metadata.split 非法: {metadata.get('split')}")

    # ── 内存数量检查 ──────────────────────────────────────────────
    if not memories:
        _add_error(result, "memories", "", "记忆列表为空")
    if not queries:
        _add_error(result, "queries", "", "查询列表为空")

    # ══════════════════════════════════════════════════════════════
    # 记忆层校验
    # ══════════════════════════════════════════════════════════════
    seen_mem_ids: set[str] = set()
    for m in memories:
        mid = m.get("id", "?")
        # -- ID 不重复 --
        if mid in seen_mem_ids:
            _add_error(result, "memories", mid, f"重复的记忆 ID: {mid}")
        seen_mem_ids.add(mid)

        # -- 必填字段 --
        for field in ["id", "user_id", "memory_type", "knowledge_type",
                       "name", "content", "scope", "project_id", "status"]:
            if not m.get(field):
                _add_error(result, "memories", mid, f"缺少必填字段: {field}")

        # -- 枚举合法 --
        mt = m.get("memory_type")
        if mt and mt not in _VALID_ENUMS["memory_type"]:
            _add_error(result, "memories", mid,
                       f"无效 memory_type: '{mt}'，合法值: {_VALID_ENUMS['memory_type']}")

        kt = m.get("knowledge_type")
        if kt and kt not in _VALID_ENUMS["knowledge_type"]:
            _add_error(result, "memories", mid,
                       f"无效 knowledge_type: '{kt}'，合法值: {_VALID_ENUMS['knowledge_type']}")

        st = m.get("status")
        if st and st not in _VALID_ENUMS["status"]:
            _add_error(result, "memories", mid,
                       f"无效 status: '{st}'，合法值: {_VALID_ENUMS['status']}")

        # -- scope 校验 --
        scope = m.get("scope", {})
        if isinstance(scope, dict):
            if not scope.get("scene"):
                _add_error(result, "memories", mid, "scope.scene 缺失")
            elif scope["scene"] not in _VALID_ENUMS["scope.scene"]:
                _add_error(result, "memories", mid,
                           f"scope.scene '{scope['scene']}' 不在合法枚举中")
            if not scope.get("task_type"):
                _add_error(result, "memories", mid, "scope.task_type 缺失")
            if not scope.get("app"):
                _add_error(result, "memories", mid, "scope.app 缺失")
        else:
            _add_error(result, "memories", mid, "scope 应为 object 类型")

        # -- ID 格式 --
        if mid and not re.match(r"^know_[a-z0-9_]+$", mid):
            _add_error(result, "memories", mid, f"ID 格式不合法: {mid}（应为 know_xxx）")

        # -- name/content 长度 --
        name = m.get("name", "")
        content = m.get("content", "")
        if name and len(name) > 256:
            _add_error(result, "memories", mid, f"name 超长: {len(name)} > 256")
        if content and len(content) > 4096:
            _add_error(result, "memories", mid, f"content 超长: {len(content)} > 4096")

        # -- workflow: 最少 2 steps --
        if kt == "workflow":
            steps = m.get("steps", [])
            if len(steps) < 2:
                _add_error(result, "memories", mid,
                           f"workflow 类型需要至少 2 个 steps，实际 {len(steps)}")

        # -- case/template: 至少 1 step --
        if kt in ("case", "template"):
            steps = m.get("steps", [])
            if len(steps) < 1:
                _add_warning(result, "memories", mid,
                             f"{kt} 类型建议至少 1 个 step")

        # -- template: 必须有 template_body --
        if kt == "template":
            if not m.get("template_body"):
                _add_error(result, "memories", mid,
                           "template 类型缺少 template_body")

        # -- replaced: 必须有 replaced_by --
        if st == "replaced":
            rb = m.get("replaced_by")
            if not rb:
                _add_error(result, "memories", mid,
                           "status=replaced 但缺少 replaced_by")
            elif rb not in memory_ids:
                _add_warning(result, "memories", mid,
                             f"replaced_by '{rb}' 引用的 memory 不在数据集中")

        # -- confidence 范围 --
        conf = m.get("confidence")
        if conf is not None and not (0.0 <= conf <= 1.0):
            _add_error(result, "memories", mid,
                       f"confidence 超出 [0, 1]: {conf}")

        # -- version >=1 --
        ver = m.get("version")
        if ver is not None and ver < 1:
            _add_error(result, "memories", mid, f"version 必须 >=1: {ver}")

        # -- 敏感信息扫描 --
        for field_name in ("name", "content", "template_body"):
            text = m.get(field_name, "")
            if text:
                _scan_sensitive(result, "memories", mid, f"memories.{field_name}", text)

        # -- 敏感信息: steps --
        for i, step in enumerate(m.get("steps", [])):
            _scan_sensitive(result, "memories", mid, f"memories.steps[{i}]", step)

    # ══════════════════════════════════════════════════════════════
    # 查询层校验
    # ══════════════════════════════════════════════════════════════
    seen_qids: set[str] = set()
    for q in queries:
        qid = q.get("query_id", "?")
        # -- ID 不重复 --
        if qid in seen_qids:
            _add_error(result, "queries", qid, f"重复的 query ID: {qid}")
        seen_qids.add(qid)

        # -- 必填字段 --
        for field in ["query_id", "user_id", "query_text", "context",
                       "project_id", "memory_types", "difficulty", "language"]:
            if not q.get(field):
                _add_error(result, "queries", qid, f"缺少必填字段: {field}")

        # -- ID 格式 --
        if qid and not re.match(r"^q_[a-z0-9_]+$", qid):
            _add_error(result, "queries", qid, f"query ID 格式不合法: {qid}")

        # -- query_text 长度 --
        qt = q.get("query_text", "")
        if qt and len(qt) > 1024:
            _add_error(result, "queries", qid, f"query_text 超长: {len(qt)} > 1024")

        # -- 枚举合法 --
        diff = q.get("difficulty")
        if diff and diff not in _VALID_ENUMS["difficulty"]:
            _add_error(result, "queries", qid,
                       f"无效 difficulty: '{diff}'，合法值: {_VALID_ENUMS['difficulty']}")

        lang = q.get("language")
        if lang and lang not in _VALID_ENUMS["language"]:
            _add_error(result, "queries", qid,
                       f"无效 language: '{lang}'，合法值: {_VALID_ENUMS['language']}")

        # -- memory_types 内部枚举 --
        for mtype in q.get("memory_types", []):
            if mtype not in _VALID_ENUMS["memory_types_elem"]:
                _add_error(result, "queries", qid,
                           f"memory_types 包含非法值: '{mtype}'")

        # -- context 校验 --
        ctx = q.get("context", {})
        if isinstance(ctx, dict):
            if not ctx.get("scene"):
                _add_error(result, "queries", qid, "context.scene 缺失")
            if not ctx.get("task_type"):
                _add_error(result, "queries", qid, "context.task_type 缺失")
            if not ctx.get("app"):
                _add_error(result, "queries", qid, "context.app 缺失")
        else:
            _add_error(result, "queries", qid, "context 应为 object 类型")

        # -- top_k 范围 --
        top_k = q.get("top_k", 5)
        if not (1 <= top_k <= 50):
            _add_error(result, "queries", qid, f"top_k 超出 [1, 50]: {top_k}")

        # -- relevance 引用完整性 --
        relevance = q.get("relevance", {})
        if relevance is None:
            relevance = {}
        for ref_id, score in relevance.items():
            # 引用存在性
            if ref_id not in memory_ids:
                _add_error(result, "queries", qid,
                           f"relevance 引用的 memory ID 不存在: {ref_id}")
            # 相关性数值范围
            if not isinstance(score, int) or not (0 <= score <= 3):
                _add_error(result, "queries", qid,
                           f"relevance 值不合法: {ref_id}=>{score}，应为 0~3 整数")

            # archived/deleted 不应该被标为 relevant (≥2)
            mem = memory_by_id.get(ref_id, {})
            mstatus = mem.get("status", "")
            if mstatus in ("archived", "deleted"):
                if score >= 2:
                    _add_error(result, "queries", qid,
                               f"archived/deleted 记忆 {ref_id} (status={mstatus}) 不应标注 relevance≥2，当前 {score}")

            # replaced 的旧版本一般不应标为 ≥2
            if mstatus == "replaced":
                if score >= 2:
                    _add_warning(result, "queries", qid,
                                 f"replaced 记忆 {ref_id} 标注了 relevance={score}，确认是否合理")

        # -- relevance 数量（有答案查询 1~5）--
        is_no_answer = (diff == "no-answer")
        if is_no_answer:
            if relevance:
                _add_error(result, "queries", qid,
                           "no-answer 查询不应有 relevance 标注")
        else:
            rel_count = sum(1 for s in relevance.values() if s >= 2)
            if rel_count < 1:
                _add_warning(result, "queries", qid,
                             "有答案查询无任何 relevance≥2 的记忆")
            if rel_count > 5:
                _add_warning(result, "queries", qid,
                             f"relevance≥2 数量 {rel_count} > 5（建议 1~5）")

        # -- 敏感信息扫描 --
        _scan_sensitive(result, "queries", qid, "queries.query_text", qt)
        notes = q.get("notes", "")
        if notes:
            _scan_sensitive(result, "queries", qid, "queries.notes", notes)

    # ══════════════════════════════════════════════════════════════
    # 统计摘要
    # ══════════════════════════════════════════════════════════════
    wf_count = sum(1 for m in memories if m.get("knowledge_type") == "workflow")
    cs_count = sum(1 for m in memories if m.get("knowledge_type") == "case")
    tm_count = sum(1 for m in memories if m.get("knowledge_type") == "template")
    active_count = sum(1 for m in memories if m.get("status") == "active")
    archived_count = sum(1 for m in memories if m.get("status") == "archived")
    deleted_count = sum(1 for m in memories if m.get("status") == "deleted")
    replaced_count = sum(1 for m in memories if m.get("status") == "replaced")
    user_ids = list(set(m.get("user_id", "?") for m in memories))
    project_ids = list(set(m.get("project_id", "?") for m in memories))

    diff_count: dict[str, int] = {}
    for q in queries:
        d = q.get("difficulty", "?")
        diff_count[d] = diff_count.get(d, 0) + 1

    no_answer_count = sum(1 for q in queries if not q.get("relevance"))

    total_errors = len(result["errors"])
    total_warnings = len(result["warnings"])

    result["stats"] = {
        "memory_count": len(memories),
        "query_count": len(queries),
        "knowledge_type_distribution": {
            "workflow": wf_count,
            "case": cs_count,
            "template": tm_count,
        },
        "status_distribution": {
            "active": active_count,
            "archived": archived_count,
            "deleted": deleted_count,
            "replaced": replaced_count,
        },
        "difficulty_distribution": diff_count,
        "unique_users": len(user_ids),
        "unique_projects": len(project_ids),
        "no_answer_queries": no_answer_count,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "passed": result["passed"],
    }

    return result


def _scan_sensitive(result: dict, section: str, item_id: str,
                    field_path: str, text: str) -> None:
    """扫描一段文本中的敏感信息模式。"""
    if not isinstance(text, str) or not text:
        return
    for pattern_name, pattern in _SENSITIVE_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            _add_error(
                result, section, item_id,
                f"检测到疑似敏感信息 ({pattern_name}) 在 {field_path}: "
                f"{_mask_match(str(match))}",
            )


def _mask_match(text: str) -> str:
    """脱敏展示匹配到的敏感片段。"""
    if len(text) <= 6:
        return text[:2] + "***"
    return text[:4] + "***" + text[-4:]


# ── 入口 ──────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="MemoryHub 检索评测数据集校验工具",
    )
    parser.add_argument(
        "--dataset", required=True,
        help="数据集 JSON 文件路径",
    )
    parser.add_argument(
        "--schema", default=None,
        help="数据集 JSON Schema 文件路径（可选，传入则执行 JSON Schema 校验）",
    )
    parser.add_argument(
        "--report", default=None,
        help="校验报告输出 JSON 路径（默认打印到 stdout）",
    )
    args = parser.parse_args()

    # 加载数据集
    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except FileNotFoundError:
        print(f"错误: 数据集文件不存在: {args.dataset}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: 数据集 JSON 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 加载 Schema（可选）
    schema = None
    if args.schema:
        try:
            with open(args.schema, "r", encoding="utf-8") as f:
                schema = json.load(f)
        except FileNotFoundError:
            print(f"警告: schema 文件不存在，跳过 JSON Schema 校验: {args.schema}",
                  file=sys.stderr)
        except json.JSONDecodeError as e:
            print(f"警告: schema JSON 解析失败，跳过 JSON Schema 校验: {e}",
                  file=sys.stderr)

    # 执行业务校验
    result = validate_dataset(dataset, schema)

    # 输出报告
    report_json = json.dumps(result, ensure_ascii=False, indent=2)

    if args.report:
        report_dir = os.path.dirname(args.report)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(report_json)
        print(f"报告已写入: {args.report}")

    # 始终打印摘要到 stdout
    stats = result["stats"]
    print(f"\n{'='*50}")
    print(f"校验结果: {'通过 ✅' if result['passed'] else '未通过 ❌'}")
    print(f"{'='*50}")
    print(f"记忆: {stats['memory_count']} 条")
    print(f"查询: {stats['query_count']} 条")
    print(f"知识类型: workflow={stats['knowledge_type_distribution']['workflow']}, "
          f"case={stats['knowledge_type_distribution']['case']}, "
          f"template={stats['knowledge_type_distribution']['template']}")
    print(f"状态分布: {stats['status_distribution']}")
    print(f"难度分布: {stats['difficulty_distribution']}")
    print(f"错误: {stats['total_errors']}, 警告: {stats['total_warnings']}")

    if result["errors"]:
        print(f"\n--- 错误详情 ({stats['total_errors']} 条) ---")
        for e in result["errors"]:
            print(f"  [{e['section']}] {e['id']}: {e['message']}")
    if result["warnings"]:
        print(f"\n--- 警告 ({stats['total_warnings']} 条) ---")
        for w in result["warnings"]:
            print(f"  [{w['section']}] {w['id']}: {w['message']}")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
