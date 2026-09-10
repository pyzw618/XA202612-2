"""v2 分级检索数据集的构建不变量。

这些不变量存在的理由，逐条对应 v1 数据集已确认的缺陷：

- 查询抄标题 → 召回虚高
- scope 随机 → 相关记忆被隔离门挡掉，召回上限被压到 ~0.65
- 越界项混在分母里 → "排序没排上"与"隔离生效"分不开
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.datasets.generators.generate_graded_retrieval_v2 import (
    generate,
    name_leak_violations,
)
from evaluation.live.datasets import load_dataset

DATASET_PATH = Path("evaluation/datasets/memoryhub_graded_retrieval_v2.1_dev.json")


@pytest.fixture(scope="module")
def dataset() -> dict:
    return generate(seed=7, split="dev", memories_target=120, queries_target=30)


# --------------------------------------------------------------- 泄漏检查


def test_full_title_in_query_is_a_violation() -> None:
    assert name_leak_violations("请按项目周报标准操作流程执行", "项目周报标准操作流程")


def test_long_fragment_leak_is_a_violation() -> None:
    # 标题被拆开嵌入查询，也应被拦截。
    assert name_leak_violations("关于标准操作流程的说明", "项目周报标准操作流程")


def test_short_topic_word_is_not_a_violation() -> None:
    # phrase 是 4 字，短于 min_leak_run，精确查询必须能通过。
    assert name_leak_violations("帮我生成项目周报", "项目周报标准操作流程", min_run=6) == []


def test_min_run_threshold_is_honoured() -> None:
    assert name_leak_violations("生成项目周报", "项目周报标准操作流程", min_run=4) != []


# --------------------------------------------------------------- 构建结果


def test_no_query_leaks_its_target_title(dataset: dict) -> None:
    memories = {memory["id"]: memory for memory in dataset["memories"]}
    for query in dataset["queries"]:
        for memory_id, grade in query["relevance"].items():
            if grade < 2:
                continue
            leaks = name_leak_violations(query["query_text"], memories[memory_id]["name"])
            assert not leaks, f"{query['query_id']} 泄漏标题：{leaks}"


def test_target_scope_matches_query_scope(dataset: dict) -> None:
    """相关记忆的 scope 必须与查询一致，否则它根本不可达。"""
    memories = {memory["id"]: memory for memory in dataset["memories"]}
    for query in dataset["queries"]:
        for memory_id, grade in query["relevance"].items():
            if grade < 2:
                continue
            memory = memories[memory_id]
            assert memory["scope"] == query["context"], query["query_id"]
            assert memory["project_id"] == query["project_id"], query["query_id"]


def test_scope_blocked_items_are_genuinely_out_of_scope(dataset: dict) -> None:
    memories = {memory["id"]: memory for memory in dataset["memories"]}
    for query in dataset["queries"]:
        for memory_id in query.get("scope_blocked", []):
            assert memories[memory_id]["project_id"] != query["project_id"], query["query_id"]


def test_exactly_one_relevant_memory_per_answered_query(dataset: dict) -> None:
    """分数 ≥2 的记忆恰好一条，使 recall@K 等价于"目标是否落在 top-K"。"""
    for query in dataset["queries"]:
        relevant = [m for m, grade in query["relevance"].items() if grade >= 2]
        if query["difficulty"] == "no_answer":
            assert relevant == [], query["query_id"]
        else:
            assert len(relevant) == 1, query["query_id"]


def test_no_answer_queries_have_empty_relevance(dataset: dict) -> None:
    for query in dataset["queries"]:
        if query["difficulty"] == "no_answer":
            assert query["relevance"] == {}


def test_every_query_carries_spec_provenance(dataset: dict) -> None:
    for query in dataset["queries"]:
        assert query["label_source"].startswith("spec:")
        assert query["spec_rationale"]


# --------------------------------------------------------------- 确定性


def test_generation_is_deterministic() -> None:
    first = generate(seed=11, split="dev", memories_target=60, queries_target=15)
    second = generate(seed=11, split="dev", memories_target=60, queries_target=15)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)


def test_generation_ignores_wall_clock() -> None:
    """created_at 必须固定，否则 SHA256 校验与跨轮次可比性都失效。"""
    dataset = generate(seed=11, split="dev", memories_target=60, queries_target=15)
    assert dataset["metadata"]["created_at"] == "2026-09-10T00:00:00Z"


def test_generator_cli_reproduces_committed_dev_dataset(tmp_path: Path) -> None:
    """CLI 是数据集的唯一来源；手工改动应当被发现。"""
    if not DATASET_PATH.exists():
        pytest.skip("v2 dev 数据集尚未生成")
    output = tmp_path / "regen.json"
    subprocess.run(
        [sys.executable, "-m",
         "evaluation.datasets.generators.generate_graded_retrieval_v2",
         "--split", "dev", "--memories", "600", "--queries", "120",
         "--output", str(output)],
        check=True, capture_output=True,
    )
    assert output.read_bytes() == DATASET_PATH.read_bytes()


def test_committed_dataset_loads_and_has_no_derived_labels() -> None:
    if not DATASET_PATH.exists():
        pytest.skip("v2 dev 数据集尚未生成")
    dataset, provenance = load_dataset(DATASET_PATH)
    assert provenance["hash_verified"] is True
    assert dataset["metadata"]["label_source"].startswith("spec:")
