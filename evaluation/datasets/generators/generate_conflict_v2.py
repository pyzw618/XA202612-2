"""生成 v2 冲突处理数据集（标签来自决策矩阵规格）。

**标签来源**：``memoryhub/core/preference/updater.py`` 的 ``ConflictResolver.auto_resolve``
决策矩阵——同 scope 且内容相同 ⇒ merge；同 scope、同 target、值不同且新偏好来源为
``explicit_feedback`` ⇒ override；scope 不同且两者都非全局 ⇒ coexist。每条样本的
``decision_basis`` 引用对应条款。

**三个块**：

- ``preference_native``：确定性可驱动（全部由规则抽取器产出 explicit_feedback 偏好）。
- ``coexist``：scope 不同。注意这条**不会产生 ConflictRecord**——``_find_existing``
  在 scope 不重叠时返回 None，新偏好直接以 NEW 落库，两条偏好并存。因此该块断言的是
  "两条偏好同时活跃且无冲突记录"，而不是某个决策值。
- ``llm_required``：需要 LLM 做语义仲裁（``_llm_targets_same_domain``）。当前部署
  未配置 LLM 密钥，该块预期失败，单独报告，不并入 headline。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "evaluation" / "datasets"
GENERATOR_NAME = "generate_conflict_v2"
SPEC_VERSION = "v2.1"
DEFAULT_CREATED_AT = "2026-09-10T00:00:00Z"
LABEL_SOURCE = f"spec:conflict-resolution-{SPEC_VERSION}#decision-matrix"

#: 规则 A 接受的格式词，用于构造必然命中的新旧偏好对。
FORMAT_TOKENS = ("markdown", "html", "json", "xml", "csv")

DOMAINS = (
    ("office", "办公"),
    ("development", "开发"),
    ("operations", "运维"),
    ("project_management", "项目管理"),
    ("personal", "个人偏好"),
    ("security", "安全合规"),
)

_BASIS = {
    "override": (
        "ConflictResolver.auto_resolve：同 scope、同 target、值不同，"
        "且新偏好来源为 explicit_feedback ⇒ OVERRIDE。"
    ),
    "merge": (
        "ConflictResolver.auto_resolve → _is_same_content：同 target 且值相同，"
        "属于支持性证据 ⇒ MERGE。"
    ),
    "coexist": (
        "ConflictResolver.auto_resolve：scope 不同且两者均非全局 ⇒ COEXIST；"
        "此时 _find_existing 不返回旧偏好，故不产生 ConflictRecord。"
    ),
    "pending": (
        "ConflictResolver.auto_resolve：新偏好来源为 implicit_inference 且置信度 < 0.8 "
        "⇒ PENDING（需 LLM 隐式抽取路径，当前部署不可用）。"
    ),
}


def generate(*, created_at: str = DEFAULT_CREATED_AT, seed: int = 42) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    counter = 0

    # ---- 确定性块：override / merge 各 60 条
    for index in range(120):
        scene, label = DOMAINS[index % len(DOMAINS)]
        decision = "override" if index % 2 == 0 else "merge"
        old_format = FORMAT_TOKENS[index % len(FORMAT_TOKENS)]
        if decision == "merge":
            new_format = old_format
            old_text = f"以后{label}场景都用 {old_format} 格式"
            new_text = old_text
        else:
            new_format = FORMAT_TOKENS[(index + 1) % len(FORMAT_TOKENS)]
            if new_format == old_format:
                new_format = FORMAT_TOKENS[(index + 2) % len(FORMAT_TOKENS)]
            old_text = f"以后{label}场景都用 {old_format} 格式"
            new_text = f"以后{label}场景都用 {new_format} 格式"
        counter += 1
        samples.append({
            "case_id": f"conf2_nat_{counter:04d}",
            "block": "preference_native",
            "old_text": old_text,
            "new_text": new_text,
            "old_scene": scene,
            "new_scene": scene,
            "expected_decision": decision,
            "expects_conflict_record": True,
            "expected_conflict": decision != "merge",
            "decision_basis": _BASIS[decision],
            "label_source": LABEL_SOURCE,
        })

    # ---- coexist 块：跨场景，断言"两条并存且无冲突记录"
    for index in range(30):
        old_scene, old_label = DOMAINS[index % len(DOMAINS)]
        new_scene, new_label = DOMAINS[(index + 3) % len(DOMAINS)]
        fmt_a = FORMAT_TOKENS[index % len(FORMAT_TOKENS)]
        fmt_b = FORMAT_TOKENS[(index + 2) % len(FORMAT_TOKENS)]
        counter += 1
        samples.append({
            "case_id": f"conf2_coexist_{counter:04d}",
            "block": "coexist",
            "old_text": f"以后{old_label}场景都用 {fmt_a} 格式",
            "new_text": f"以后{new_label}场景都用 {fmt_b} 格式",
            "old_scene": old_scene,
            "new_scene": new_scene,
            "expected_decision": "coexist",
            "expects_conflict_record": False,
            "expected_conflict": False,
            "decision_basis": _BASIS["coexist"],
            "label_source": LABEL_SOURCE,
        })

    # ---- 需 LLM 块：语义等价但措辞不同的 target 需要 LLM 判定
    for index in range(30):
        scene, label = DOMAINS[index % len(DOMAINS)]
        counter += 1
        samples.append({
            "case_id": f"conf2_llm_{counter:04d}",
            "block": "llm_required",
            "old_text": f"以后{label}场景都用 markdown 格式",
            "new_text": f"以后{label}场景的输出请保持 markdown 排版",
            "old_scene": scene,
            "new_scene": scene,
            "expected_decision": "merge",
            "expects_conflict_record": True,
            "expected_conflict": False,
            "decision_basis": (
                "规格：两条说法语义等价（同一输出格式），应判为支持性证据 ⇒ MERGE；"
                "但新说法不含规则触发词，需 LLM 抽取才能形成可比偏好。"
            ),
            "label_source": LABEL_SOURCE,
        })

    return {
        "metadata": {
            "dataset_id": f"memoryhub-conflict-resolution-{SPEC_VERSION}",
            "version": "2.0.0",
            "created_at": created_at,
            "generator": GENERATOR_NAME,
            "generator_random_seed": seed,
            "spec_version": SPEC_VERSION,
            "label_source": LABEL_SOURCE,
            "sample_count": len(samples),
            "blocks": {
                block: sum(1 for s in samples if s["block"] == block)
                for block in ("preference_native", "coexist", "llm_required")
            },
            "annotation_rules": (
                "决策标签来自 ConflictResolver 决策矩阵规格；coexist 块不产生冲突记录，"
                "断言的是两条偏好并存且无冲突记录。"
            ),
        },
        "samples": samples,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 v2 冲突处理数据集")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    dataset = generate(created_at=args.created_at, seed=args.seed)
    output = args.output or OUTPUT_DIR / f"memoryhub_conflict_resolution_{SPEC_VERSION}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **dataset["metadata"]["blocks"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
