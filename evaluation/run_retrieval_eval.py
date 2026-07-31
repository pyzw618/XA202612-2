"""
检索评测 v2 驱动脚本

按 docs_group2/评测v2-检索评测方案.md §五 实现：
- 数据加载（缺失时自动生成 tests/eval_dataset.json）
- 逐组构造 HybridRetriever（纯 BM25 / 纯 FAISS / Hybrid 多组权重）
- 指标聚合（总体 + 按难度分层）+ console 表格 + JSON 报告

用法:
    python evaluation/run_retrieval_eval.py
    python evaluation/run_retrieval_eval.py --provider kylin   # 真实语义 embedding（需 kylin 环境）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.adapter.schemas import SearchRequest
from memoryhub.config import RetrievalConfig
from memoryhub.embedding import KylinEmbeddingClient, MockEmbeddingClient
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.retrieval.vector_search import VectorSearcher

from evaluation.metrics.retrieval_eval import RetrievalEvaluator, percentile
from tests.eval_dataset import load_dataset, save_dataset

TOP_K = 10  # 检索截断位置（Recall@10/NDCG@10 的 K）

# 消融实验分组（方案 §5.3）：(组名, 说明, vector, keyword, metadata)
ABLATION_GROUPS = [
    ("A", "纯 BM25", 0.0, 1.0, 0.0),
    ("B", "纯 FAISS", 1.0, 0.0, 0.0),
    ("C", "Hybrid 默认", 0.6, 0.3, 0.1),
    ("D", "Hybrid 均衡", 0.45, 0.45, 0.1),
    ("E", "Hybrid 重向量", 0.8, 0.1, 0.1),
]

DIFFICULTIES = ["exact_match", "semantic", "distractor", "cross_domain"]

MOCK_LIMITATION_NOTICE = """
[!] 已知限制（方案 §5.4）：
    - 当前使用 MockEmbeddingClient（SHA256 哈希伪随机向量，无语义性），
      向量路分数是噪声，B 组（纯 FAISS）指标接近随机水平属预期；
    - Hybrid 组的真实增益主要靠 BM25 路，结论仅对融合机制有效，
      不代表真实 embedding 下的绝对水平；
    - 要测真实语义检索，请配置 kylin embedding 后以 --provider kylin 重跑；
    - 数据集仅 20 条 query，指标波动大，权重微调差异不具统计显著性，
      本报告只给方向性结论。
"""


# ============================================================
# 检索器构造
# ============================================================

def build_embedding_client(provider: str, dim: int):
    """构造 embedding 客户端。mock 必须 latency=0.0，避免 100ms 假延迟污染延迟指标。"""
    if provider == "kylin":
        client = KylinEmbeddingClient(dim=dim)
        if not client.is_available():
            raise RuntimeError(
                "Kylin embedding 不可用（非麒麟环境或缺少 .so），请改用 --provider mock"
            )
        return client
    return MockEmbeddingClient(dim=dim, latency=0.0)


def build_retriever(memories: list[dict], embed_fn, dim: int, config: RetrievalConfig) -> HybridRetriever:
    """
    按方案 §5.2 构造检索器：
    - BM25 索引覆盖全部记忆；
    - FAISS 索引覆盖全部记忆；
    - 元数据从简：统一 memory_type="knowledge"，无 scope/confidence，
      metadata 路对所有候选给统一 0.5 分（常数偏移，不影响排序），
      _filter_by_context 全部放行；
    - 必须 cache=None，避免跨消融组缓存污染；
    - reranker=None，走纯分数排序分支，只测融合本身。
    """
    keyword_search = KeywordSearcher()
    keyword_search.build_index([(m["id"], m["content"], "") for m in memories])

    vector_search = VectorSearcher(dimension=dim)
    for m in memories:
        vector_search.add(m["id"], embed_fn(m["content"]), metadata={"memory_type": "knowledge"})

    return HybridRetriever(
        vector_search=vector_search,
        keyword_search=keyword_search,
        reranker=None,
        cache=None,
        config=config,
        embedding_fn=embed_fn,
    )


# ============================================================
# 评测执行
# ============================================================

def evaluate_group(retriever: HybridRetriever, queries: list[dict]) -> dict:
    """跑一组消融：逐 query 检索并计算指标，返回总体 + 难度分层 + 逐 query 明细。"""
    evaluator = RetrievalEvaluator(retriever, top_k=TOP_K)

    per_query = []
    for item in queries:
        expected_ids = list(item["relevant_ids"])
        response = retriever.search(SearchRequest(query=item["query_text"], top_k=TOP_K))
        retrieved_ids = [r.memory_id for r in response.results]

        per_query.append({
            "query_id": item["query_id"],
            "query_text": item["query_text"],
            "difficulty": item["difficulty"],
            "expected_ids": expected_ids,
            "retrieved_ids": retrieved_ids,
            "hit_ids": [rid for rid in retrieved_ids if rid in expected_ids],
            "recall_at_5": evaluator.recall_at_k(expected_ids, retrieved_ids, 5),
            "recall_at_10": evaluator.recall_at_k(expected_ids, retrieved_ids, 10),
            "precision_at_5": evaluator.precision_at_k(expected_ids, retrieved_ids, 5),
            "mrr": evaluator.mrr(expected_ids, retrieved_ids),
            "ndcg_at_10": evaluator.ndcg(expected_ids, retrieved_ids, 10),
            "latency_ms": response.latency_ms,
        })

    def aggregate(rows: list[dict]) -> dict:
        if not rows:
            return {}
        n = len(rows)
        latencies = [r["latency_ms"] for r in rows]
        return {
            "num_queries": n,
            "recall_at_5": sum(r["recall_at_5"] for r in rows) / n,
            "recall_at_10": sum(r["recall_at_10"] for r in rows) / n,
            "precision_at_5": sum(r["precision_at_5"] for r in rows) / n,
            "mrr": sum(r["mrr"] for r in rows) / n,
            "ndcg_at_10": sum(r["ndcg_at_10"] for r in rows) / n,
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
            "latency_max_ms": max(latencies),
        }

    by_difficulty = {
        d: aggregate([r for r in per_query if r["difficulty"] == d])
        for d in DIFFICULTIES
    }
    return {
        "overall": aggregate(per_query),
        "by_difficulty": by_difficulty,
        "per_query": per_query,
    }


def print_group_table(group_name: str, desc: str, weights: tuple, metrics: dict) -> None:
    """console 表格输出（方案 §5.5）"""
    vw, kw, mw = weights
    print(f"\n=== 组 {group_name}: {desc} ({vw}/{kw}/{mw}) ===")
    header = f"{'指标':<14}{'总体':>8}" + "".join(f"{d:>14}" for d in DIFFICULTIES)
    print(header)
    print("-" * len(header))
    rows = [
        ("Recall@5", "recall_at_5"),
        ("Recall@10", "recall_at_10"),
        ("Precision@5", "precision_at_5"),
        ("MRR", "mrr"),
        ("NDCG@10", "ndcg_at_10"),
    ]
    for label, key in rows:
        line = f"{label:<14}{metrics['overall'][key]:>8.3f}"
        for d in DIFFICULTIES:
            sub = metrics["by_difficulty"].get(d) or {}
            line += f"{sub.get(key, 0.0):>14.3f}" if sub else f"{'-':>14}"
        print(line)
    overall = metrics["overall"]
    print(
        f"{'延迟 P50/P95/max':<14}"
        f"{overall['latency_p50_ms']:.1f} / {overall['latency_p95_ms']:.1f} / {overall['latency_max_ms']:.1f} ms"
    )


def get_git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="检索评测 v2：HybridRetriever 消融实验")
    parser.add_argument("--provider", choices=["mock", "kylin"], default="mock",
                        help="embedding provider；kylin 用于真实语义检索复测")
    parser.add_argument("--dim", type=int, default=64, help="embedding 维度")
    parser.add_argument("--dataset", default=os.path.join("tests", "eval_dataset.json"),
                        help="数据集 JSON 路径（缺失时自动生成）")
    parser.add_argument("--output", default=os.path.join("evaluation", "results", "retrieval_eval_v2.json"),
                        help="JSON 报告输出路径（本地产物，不入库）")
    args = parser.parse_args()

    # 数据集缺失时自动生成（save_dataset() 产物，不入库）
    if not os.path.exists(args.dataset):
        save_dataset(args.dataset)
        print(f"数据集不存在，已自动生成: {args.dataset}")
    dataset = load_dataset(args.dataset)
    memories, queries = dataset["memories"], dataset["queries"]
    print(f"数据集: {len(memories)} 条记忆, {len(queries)} 个 query, "
          f"难度分布: {dataset['metadata']['difficulty_distribution']}")

    embed_client = build_embedding_client(args.provider, args.dim)
    print(f"embedding: provider={args.provider}, dim={embed_client.get_dimension()}")

    report = {
        "environment": {
            "embedding_provider": args.provider,
            "embedding_dim": embed_client.get_dimension(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": get_git_commit(),
            "top_k": TOP_K,
        },
        "dataset_metadata": dataset["metadata"],
        "groups": {},
    }

    for group_name, desc, vw, kw, mw in ABLATION_GROUPS:
        config = RetrievalConfig(vector_weight=vw, keyword_weight=kw, metadata_weight=mw)
        retriever = build_retriever(memories, embed_client.embed, args.dim, config)
        metrics = evaluate_group(retriever, queries)
        print_group_table(group_name, desc, (vw, kw, mw), metrics)
        report["groups"][group_name] = {
            "description": desc,
            "weights": {"vector": vw, "keyword": kw, "metadata": mw},
            **metrics,
        }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 报告已写入: {args.output}")

    # sanity check（验收标准 3）：A 组 exact_match Recall@5 应显著高于 B 组
    a_exact = report["groups"]["A"]["by_difficulty"]["exact_match"]["recall_at_5"]
    b_exact = report["groups"]["B"]["by_difficulty"]["exact_match"]["recall_at_5"]
    ok = a_exact > b_exact
    print(f"sanity check: A 组 exact_match Recall@5={a_exact:.3f} "
          f"{'>' if ok else '<='} B 组 {b_exact:.3f} → {'通过' if ok else '【失败，评测链路可能接错】'}")

    if args.provider == "mock":
        print(MOCK_LIMITATION_NOTICE)


if __name__ == "__main__":
    main()
