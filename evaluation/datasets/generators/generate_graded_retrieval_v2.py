"""生成 v2 分级知识检索数据集（规格优先，无标题泄漏，scope 一致）。

与 v1 数据集的三个关键差异——每一个都对应 v1 里已确认的缺陷：

1. **查询不得抄标题**。v1 ``memoryhub_knowledge_retrieval_v1_test.json`` 的查询
   大量直接复制记忆 ``name``（如 ``帮我做代码评审Checklist模板v1``），导致召回
   虚高。本生成器在构建时机械校验：查询不得包含目标记忆的 ``name``，也不得
   包含其长度 ≥ ``--min-leak-run``（默认 6）的连续子串，违反即构建失败。

2. **scope 从目标记忆复制**，不随机。v1 的 214 条 ``task_type`` 与 115 条
   ``project_id`` 失配，使得这些"相关记忆"在严格 scope 门下根本不可达，
   召回上限被压到约 0.65。

3. **越界项单独标注**。``scope_blocked`` 记录"主题相关但确实越界"的记忆：
   它们不进召回分母，若被系统返回则计入 ``isolation_violation_rate``。这样
   "排序没排上"与"隔离正确挡掉"是两个分开的、诚实的数字。

用法::

    .venv/bin/python -m evaluation.datasets.generators.generate_graded_retrieval_v2 \\
        --split dev --memories 600 --queries 120
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from evaluation.datasets.generators.vocab import (
    DOMAINS,
    KNOWLEDGE_TYPES,
    NAME_SUFFIX,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "evaluation" / "datasets"
GENERATOR_NAME = "generate_graded_retrieval_v2"
SPEC_VERSION = "v2.1"

#: 固定的生成时点，保证同一组参数产出逐字节相同的文件。
DEFAULT_CREATED_AT = "2026-09-10T00:00:00Z"

#: 查询难度分档。
DIFFICULTIES = ("exact", "paraphrase", "semantic", "cross_scope", "no_answer")

#: ``label_source`` 前缀，指向定义期望的规格条款而非任何运行结果。
LABEL_SOURCE = f"spec:graded-retrieval-{SPEC_VERSION}#relevance-grading"

#: 填料的"侧面"，与核心记忆同主题、共 scope，作为分级干扰项。
FILLER_ASPECTS = ("注意事项", "常见问题", "工具选型", "时效要求", "口径说明", "失败案例")

#: 每个侧面的正文措辞。
#:
#: **刻意不复述主题词**。早期版本让填料正文重复 "{phrase}"，导致填料与查询的
#: 词面重叠高于正例本身（正例排名一度垫底）。硬性干扰项应当是"主题相关但不
#: 回答该问题"，而不是"比答案更匹配查询"。这里改成只谈侧面，不碰主题名词。
FILLER_BODIES: dict[str, str] = {
    "注意事项": "执行前需要先确认输入范围与责任边界，否则容易在交付阶段返工。",
    "常见问题": "常见疑问集中在权限申请与产出格式上，遇到时优先查阅当期规范。",
    "工具选型": "工具优先选用已授权的组件，避免为单次任务引入新的外部依赖。",
    "时效要求": "时限以当期排期为准；超出窗口的需要重新确认资源与优先级。",
    "口径说明": "统计口径以相关方共同确认的版本为准，口径变更需留痕。",
    "失败案例": "曾因输入未做校验导致结果偏差，事后补充了复核环节。",
}


def name_leak_violations(query_text: str, name: str, min_run: int = 6) -> list[str]:
    """返回查询中泄漏了目标标题的片段；空列表表示无泄漏。

    先查整体包含，再查长度 ≥ ``min_run`` 的连续子串。子串比对是为了拦住
    "标题被拆开嵌进查询"这类变形泄漏。
    """
    if not name or not query_text:
        return []
    if name in query_text:
        return [name]
    violations: set[str] = set()
    n = len(name)
    for length in range(min_run, n + 1):
        for start in range(n - length + 1):
            fragment = name[start : start + length]
            if fragment in query_text:
                violations.add(fragment)
    # 只保留最短的违规片段，避免把同一处泄漏的各级超串全部列出。
    return sorted(sorted(violations, key=len)[:1])


def build_memories(rng: random.Random, filler_per_task: int) -> list[dict[str, Any]]:
    """构建核心记忆、跨项目探针与同主题填料。"""
    memories: list[dict[str, Any]] = []
    for domain in DOMAINS:
        for task in domain["tasks"]:
            base = f"gv2_{domain['key']}_{task['slug']}"
            # 名称只由 phrase + 类型后缀构成，绝不引入 goal/content 的片段——
            # paraphrase/semantic 查询正是用 goal/deliver 表述的，名称一旦含
            # 这些片段就会造成标题泄漏（已由 name_leak_violations 拦下）。
            # phrase 统一为 4 字，短于 min_leak_run，故精确查询仍可命中。
            name_root = task["phrase"]
            for knowledge_type in KNOWLEDGE_TYPES:
                memory_id = f"{base}_{knowledge_type}"
                memories.append(
                    _make_memory(
                        rng,
                        domain=domain,
                        task=task,
                        knowledge_type=knowledge_type,
                        memory_id=memory_id,
                        name=f"{name_root}{NAME_SUFFIX[knowledge_type]}",
                        project_id=domain["project"],
                    )
                )
            # 跨项目探针：内容与核心记忆同主题，但属于另一个项目，
            # 因此必须被严格 scope 门挡掉。
            memories.append(
                _make_memory(
                    rng,
                    domain=domain,
                    task=task,
                    knowledge_type="workflow",
                    memory_id=f"{base}_xproj",
                    name=f"{name_root}{NAME_SUFFIX['workflow']}",
                    project_id=f"{domain['project']}_x",
                )
            )
            # 同主题填料：与核心记忆同 scope、同 phrase，作为分级干扰项。
            # 类型轮转，避免语料被单一类型主导。
            for aspect_index in range(filler_per_task):
                aspect = FILLER_ASPECTS[aspect_index % len(FILLER_ASPECTS)]
                memories.append(
                    _make_memory(
                        rng,
                        domain=domain,
                        task=task,
                        knowledge_type=KNOWLEDGE_TYPES[aspect_index % len(KNOWLEDGE_TYPES)],
                        memory_id=f"{base}_filler{aspect_index + 1}",
                        name=f"{task['phrase']}{aspect}",
                        project_id=domain["project"],
                        filler=True,
                    )
                )
    return memories


def _make_memory(
    rng: random.Random,
    *,
    domain: dict[str, Any],
    task: dict[str, Any],
    knowledge_type: str,
    memory_id: str,
    name: str,
    project_id: str,
    filler: bool = False,
) -> dict[str, Any]:
    tools = list(task["tools"])
    rng.shuffle(tools)
    if filler:
        aspect = name[len(task["phrase"]):]
        content = FILLER_BODIES.get(aspect, FILLER_BODIES["注意事项"])
    else:
        # 正文按记忆类型给出不同侧面，并以 rng 选取表述变体。
        #
        # **刻意不共用固定句式**。早期版本每条 workflow 都带
        # "适用于{label}场景，执行时需遵循{label}相关规范"，600 条记忆因此高度
        # 雷同，embedding 无法区分，向量通道退化为噪声（实测出现"项目周报"的
        # 查询把"报销单""排班表"排到前面）。这里让措辞随记录变化，并保留
        # task 特有的目标与产出词，使语义空间能真正分开。
        if knowledge_type == "workflow":
            variants = (
                f"{task['goal']}；按既定步骤执行，产出{task['deliver']}。",
                f"围绕{task['deliver']}的标准做法：{task['goal']}。",
                f"{task['goal']}。执行时以本流程为准，交付物是{task['deliver']}。",
            )
        elif knowledge_type == "case":
            variants = (
                f"此前的一次实际处理：{task['goal']}，最终交付{task['deliver']}。",
                f"类似情形中采用的方案是{task['goal']}，结果产出{task['deliver']}。",
                f"实践记录：{task['goal']}；过程中保留了{task['deliver']}作为佐证。",
            )
        else:
            variants = (
                f"可复用的产出骨架，用于{task['goal']}，最终给出{task['deliver']}。",
                f"直接套用的格式：服务于{task['goal']}，成品为{task['deliver']}。",
                f"模板：面向{task['deliver']}，覆盖{task['goal']}所需的条目。",
            )
        content = variants[rng.randrange(len(variants))]
    memory: dict[str, Any] = {
        "id": memory_id,
        "user_id": "eval_user",
        "memory_type": "knowledge",
        "knowledge_type": knowledge_type,
        "name": name,
        "content": content,
        "steps": [],
        "tools": tools[:3],
        "template_body": "",
        "scope": {
            "scene": domain["scene"],
            "task_type": f"{domain['key']}.{task['slug']}",
            "app": domain["app"],
        },
        "project_id": project_id,
        "status": "active",
        "version": 1,
        "tags": [task["phrase"], domain["label"], knowledge_type],
        "confidence": round(rng.uniform(0.82, 0.98), 2),
        "spec_origin": f"vocab:{domain['key']}.{task['slug']}",
    }
    if knowledge_type == "workflow":
        memory["steps"] = [
            f"确认{task['phrase']}的输入与范围",
            f"按{domain['label']}规范执行{task['verb']}步骤",
            f"校验结果并产出{task['deliver']}",
            f"归档记录并同步相关方",
        ]
    elif knowledge_type == "template":
        memory["template_body"] = (
            f"# {name}\n\n"
            f"目标：{task['goal']}\n"
            f"产出：{task['deliver']}\n"
            f"适用：{domain['label']} / {task['phrase']}\n"
        )
    return memory


def build_queries(
    rng: random.Random,
    memories: list[dict[str, Any]],
    queries_per_domain: int,
    min_leak_run: int,
) -> list[dict[str, Any]]:
    """按难度分档生成查询，并为每条查询标注分级相关性。"""
    by_id = {memory["id"]: memory for memory in memories}
    # 每个 (domain, task) 的记忆分组，便于计算同主题干扰项。
    groups: dict[str, list[dict[str, Any]]] = {}
    for memory in memories:
        key = memory["id"].rsplit("_", 1)[0]
        groups.setdefault(key, []).append(memory)

    queries: list[dict[str, Any]] = []
    counter = 0
    for domain in DOMAINS:
        tasks = domain["tasks"]
        for index in range(queries_per_domain):
            task = tasks[index % len(tasks)]
            difficulty = DIFFICULTIES[index % len(DIFFICULTIES)]
            counter += 1
            query_id = f"gq2_{domain['key']}_{counter:04d}"
            base_id = f"gv2_{domain['key']}_{task['slug']}"
            target = by_id.get(f"{base_id}_workflow")

            if difficulty == "cross_scope":
                # 用跨项目探针做目标：查询的 scope 指向 _x 项目，核心记忆
                # 因此必须被挡掉，探针必须被返回。
                probe = by_id.get(f"{base_id}_xproj")
                if probe is None:
                    continue
                query = _make_query(
                    rng,
                    query_id=query_id,
                    domain=domain,
                    task=task,
                    difficulty=difficulty,
                    query_text=f"我在{domain['label']}的另一个项目里需要{task['verb']}{task['deliver']}，按哪套做法执行",
                    project_id=probe["project_id"],
                    relevance={probe["id"]: 3},
                    scope_blocked=[target["id"]] if target else [],
                )
            elif difficulty == "no_answer":
                query = _make_query(
                    rng,
                    query_id=query_id,
                    domain=domain,
                    task=task,
                    difficulty=difficulty,
                    query_text=f"{domain['label']}场景下有没有关于异地灾备演练的既定做法",
                    project_id=domain["project"],
                    relevance={},
                    scope_blocked=[],
                )
            else:
                if target is None:
                    continue
                query_text = _difficulty_query(difficulty, task, domain)
                relevance = _relevance_for(target, groups.get(base_id, []))
                query = _make_query(
                    rng,
                    query_id=query_id,
                    domain=domain,
                    task=task,
                    difficulty=difficulty,
                    query_text=query_text,
                    project_id=domain["project"],
                    relevance=relevance,
                    scope_blocked=[
                        memory["id"]
                        for memory in groups.get(base_id, [])
                        if memory["id"].endswith("_xproj")
                    ],
                )

            # 机械校验：查询不得泄漏目标标题。
            leaks: list[str] = []
            for memory_id in query["relevance"]:
                memory = by_id.get(memory_id)
                if memory is None:
                    continue
                leaks.extend(name_leak_violations(query["query_text"], memory["name"], min_leak_run))
            if leaks:
                raise ValueError(
                    f"{query_id} 的查询泄漏了目标标题片段 {leaks}：{query['query_text']!r}。"
                    "请调整查询模板，而不是放宽检查。"
                )
            queries.append(query)
    return queries


def _difficulty_query(difficulty: str, task: dict[str, Any], domain: dict[str, Any]) -> str:
    """按难度选模板。paraphrase/semantic 刻意不使用 ``phrase``。"""
    if difficulty == "exact":
        return f"帮我{task['verb']}{task['phrase']}，走哪套流程"
    if difficulty == "paraphrase":
        return f"{task['goal']}，有没有现成做法可以直接参照"
    if difficulty == "semantic":
        return f"{task['deliver']}要怎么做才能既快又不出错"
    return f"{domain['label']}场景下{task['verb']}的通用方法"


def _relevance_for(target: dict[str, Any], group: list[dict[str, Any]]) -> dict[str, int]:
    """分级标注。

    - 3 = 目标记忆（唯一能完整回答该查询的记忆）
    - 1 = 同主题、同 scope 但只覆盖侧面的记忆

    刻意**不产生等级 2**：语料里不存在"同样完整可替代"的第二条记忆，硬造一个
    会让召回变成"两条都得命中"才算满分，与赛题"召回率"的直观口径不符。
    于是 ``relevant = 等级 ≥ 2`` 恰好等价于 ``{目标记忆}``，召回@K 即为
    "目标记忆是否落在 top-K"，单一且可解释。

    跨项目探针不入分母，由 ``scope_blocked`` 单独承担隔离检查。
    """
    relevance: dict[str, int] = {target["id"]: 3}
    for memory in group:
        if memory["id"] == target["id"] or memory["id"].endswith("_xproj"):
            continue
        relevance[memory["id"]] = 1
    return relevance


def _make_query(
    rng: random.Random,
    *,
    query_id: str,
    domain: dict[str, Any],
    task: dict[str, Any],
    difficulty: str,
    query_text: str,
    project_id: str,
    relevance: dict[str, int],
    scope_blocked: list[str],
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "user_id": "eval_user",
        "query_text": query_text,
        "context": {
            "scene": domain["scene"],
            "task_type": f"{domain['key']}.{task['slug']}",
            "app": domain["app"],
        },
        "project_id": project_id,
        "memory_types": ["knowledge"],
        "top_k": 5,
        "difficulty": difficulty,
        "language": "zh-CN",
        "relevance": relevance,
        "scope_blocked": scope_blocked,
        "label_source": LABEL_SOURCE,
        "spec_rationale": (
            "相关性分级：目标记忆=3（唯一完整答案）；同主题同 scope 的侧面记忆=1；"
            "relevant 集合取等级≥2，即仅目标记忆本身。"
            "scope_blocked 为越界项，不入召回分母，单独计 isolation_violation_rate。"
        ),
        "notes": f"{domain['label']} / {task['phrase']} / {difficulty}",
    }


def generate(
    *,
    seed: int = 42,
    split: str = "dev",
    memories_target: int = 600,
    queries_target: int = 120,
    min_leak_run: int = 6,
    created_at: str = DEFAULT_CREATED_AT,
) -> dict[str, Any]:
    """构建数据集（确定性）。

    ``created_at`` 刻意取固定值而非当前时间：同一组参数必须产出逐字节相同的
    文件，否则 ``SHA256SUMS.txt`` 校验与"跨轮次可复现"都失去意义。需要标记
    生成时点时用 ``--created-at`` 显式覆盖。
    """
    rng = random.Random(seed)
    # 每个 (domain, task) 有 3 类核心记忆 + 1 个跨项目探针 + N 个填料。
    core_per_task = len(KNOWLEDGE_TYPES) + 1
    task_count = sum(len(domain["tasks"]) for domain in DOMAINS)
    filler_per_task = max(0, round(memories_target / task_count) - core_per_task)
    memories = build_memories(rng, filler_per_task)

    queries_per_domain = max(1, queries_target // len(DOMAINS))
    queries = build_queries(rng, memories, queries_per_domain, min_leak_run)

    difficulty_counts: dict[str, int] = {}
    for query in queries:
        difficulty_counts[query["difficulty"]] = difficulty_counts.get(query["difficulty"], 0) + 1

    return {
        "metadata": {
            "dataset_id": f"memoryhub-graded-retrieval-{SPEC_VERSION}",
            "version": "2.0.0",
            "split": split,
            "created_at": created_at,
            "generator": GENERATOR_NAME,
            "generator_random_seed": seed,
            "spec_version": SPEC_VERSION,
            "label_source": LABEL_SOURCE,
            "min_leak_run": min_leak_run,
            "memory_count": len(memories),
            "query_count": len(queries),
            "difficulty_distribution": difficulty_counts,
            "annotation_rules": (
                "标签由规格定义（目标=3 / 同主题同 scope=2 或 1），不含任何服务运行结果；"
                "查询经机械校验不含目标标题或其 ≥min_leak_run 字子串；"
                "scope_blocked 为越界项，单独计 isolation_violation_rate。"
            ),
        },
        "memories": memories,
        "queries": queries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 v2 分级知识检索数据集")
    parser.add_argument("--split", default="dev", choices=["dev", "test"])
    parser.add_argument("--memories", type=int, default=600)
    parser.add_argument("--queries", type=int, default=120)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-leak-run", type=int, default=6)
    parser.add_argument("--created-at", default=DEFAULT_CREATED_AT, help="固定生成时点（保证可复现）")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    dataset = generate(
        seed=args.seed,
        split=args.split,
        memories_target=args.memories,
        queries_target=args.queries,
        min_leak_run=args.min_leak_run,
        created_at=args.created_at,
    )
    output = args.output or OUTPUT_DIR / f"memoryhub_graded_retrieval_{SPEC_VERSION}_{args.split}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata = dataset["metadata"]
    print(json.dumps({
        "output": str(output),
        "memories": metadata["memory_count"],
        "queries": metadata["query_count"],
        "difficulty": metadata["difficulty_distribution"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
