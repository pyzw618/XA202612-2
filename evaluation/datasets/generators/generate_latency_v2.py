"""生成 v2 延迟查询集。

延迟测量对数据集的唯一硬要求是**查询文本互不相同**：``cold`` 阶段必须在
查询向量缓存与结果缓存上同时落空，重复文本会命中缓存，把延迟测成"缓存命中
时间"（v1 的 ``latency_report.json`` 正是三个阶段混在一起报的，导致
result_hot 的 27ms 被拿来当证据）。

因此这里用"任务词 × 前缀 × 后缀"的组合保证文本唯一，并让查询的 scope 与
目标记忆一致，使其能真正走到完整检索链路。

注意：延迟集**不需要相关性标注**——它只测量耗时，不测量排序质量。
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from evaluation.datasets.generators.vocab import DOMAINS

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "evaluation" / "datasets"
GENERATOR_NAME = "generate_latency_v2"
SPEC_VERSION = "v2.1"
DEFAULT_CREATED_AT = "2026-09-10T00:00:00Z"
LABEL_SOURCE = f"spec:latency-{SPEC_VERSION}#unique-query-only"

#: 前缀 × 后缀的组合用于制造互不相同的查询文本。
PREFIXES = ("帮我", "请", "我想", "需要", "能不能", "如何", "怎么", "有没有办法", "求", "想要")
SUFFIXES = (
    "，说下步骤",
    "，给个做法",
    "，有模板吗",
    "，注意事项是什么",
    "，怎么做最快",
    "，标准做法是什么",
)


def generate(
    *,
    seed: int = 42,
    split: str = "dev",
    queries_target: int = 2000,
    warmup: int = 100,
    created_at: str = DEFAULT_CREATED_AT,
) -> dict[str, Any]:
    rng = random.Random(seed)
    tasks: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (domain, task) for domain in DOMAINS for task in domain["tasks"]
    ]

    formal: list[dict[str, Any]] = []
    seen: set[str] = set()
    index = 0
    # 组合空间 = 任务 × 前缀 × 后缀，远大于目标条数，不会提前耗尽。
    while len(formal) < queries_target and index < queries_target * 4:
        domain, task = tasks[index % len(tasks)]
        prefix = PREFIXES[(index // len(tasks)) % len(PREFIXES)]
        suffix = SUFFIXES[(index // (len(tasks) * len(PREFIXES))) % len(SUFFIXES)]
        text = f"{prefix}{task['verb']}{task['phrase']}{suffix}"
        index += 1
        if text in seen:
            continue
        seen.add(text)
        formal.append(
            {
                "query_id": f"lat2_{domain['key']}_{len(formal):05d}",
                "user_id": "eval_user",
                "query_text": text,
                "context": {
                    "scene": domain["scene"],
                    "task_type": f"{domain['key']}.{task['slug']}",
                    "app": domain["app"],
                },
                "project_id": domain["project"],
                "memory_types": ["knowledge"],
                "top_k": 5,
                "phase": "formal",
                "label_source": LABEL_SOURCE,
                "spec_rationale": "延迟集仅要求查询文本唯一，不参与相关性评分。",
            }
        )

    warmup_queries: list[dict[str, Any]] = []
    for offset in range(warmup):
        domain, task = tasks[offset % len(tasks)]
        warmup_queries.append(
            {
                "query_id": f"lat2_warmup_{offset:04d}",
                "user_id": "eval_user",
                "query_text": f"预热查询 {offset}：{task['phrase']}相关说明",
                "context": {
                    "scene": domain["scene"],
                    "task_type": f"{domain['key']}.{task['slug']}",
                    "app": domain["app"],
                },
                "project_id": domain["project"],
                "memory_types": ["knowledge"],
                "top_k": 5,
                "phase": "warmup",
                "label_source": LABEL_SOURCE,
                "spec_rationale": "预热查询，不计入任何统计。",
            }
        )

    rng.shuffle(warmup_queries)
    return {
        "metadata": {
            "dataset_id": f"memoryhub-latency-{SPEC_VERSION}",
            "version": "2.0.0",
            "split": split,
            "created_at": created_at,
            "generator": GENERATOR_NAME,
            "generator_random_seed": seed,
            "spec_version": SPEC_VERSION,
            "label_source": LABEL_SOURCE,
            "warmup_count": len(warmup_queries),
            "formal_count": len(formal),
            "annotation_rules": (
                "查询文本全局唯一，用于保证 cold 阶段同时绕过向量缓存与结果缓存；"
                "本集不提供相关性标注。"
            ),
        },
        "warmup_queries": warmup_queries,
        "formal_queries": formal,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 v2 延迟查询集")
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--queries", type=int, default=2000)
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    dataset = generate(
        seed=args.seed, split=args.split, queries_target=args.queries,
        warmup=args.warmup, created_at=args.created_at,
    )
    output = args.output or OUTPUT_DIR / f"memoryhub_retrieval_latency_{SPEC_VERSION}_{args.split}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    texts = [q["query_text"] for q in dataset["warmup_queries"] + dataset["formal_queries"]]
    print(json.dumps({
        "output": str(output),
        "warmup": len(dataset["warmup_queries"]),
        "formal": len(dataset["formal_queries"]),
        "unique_texts": len(set(texts)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
