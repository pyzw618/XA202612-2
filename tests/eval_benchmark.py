"""
评测基准脚本

按文档 §5 评测体系设计实现：
- 指标: Recall@K, Precision@K, MRR, NDCG@K, P95 延迟
- 消融实验: 纯 BM25 / 纯 FAISS / Hybrid(多组权重)
- 难度分层统计
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# 强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.embedding import create_embedding_client
from src.memory_store import MemoryStore
from src.search_engine import MemorySearchEngine

# 导入数据集
from tests.eval_dataset import load_dataset, save_dataset


# ============================================================
# 1. 指标计算
# ============================================================

def recall_at_k(relevant_ids: List[str], retrieved_ids: List[str], k: int) -> float:
    """Recall@K = 相关记录中在 Top-K 被命中的比例"""
    if not relevant_ids:
        return 1.0
    top_k_ids = set(retrieved_ids[:k])
    hits = sum(1 for rid in relevant_ids if rid in top_k_ids)
    return hits / len(relevant_ids)


def precision_at_k(relevant_ids: List[str], retrieved_ids: List[str], k: int) -> float:
    """Precision@K = Top-K 中真正相关的比例"""
    if k == 0:
        return 0.0
    top_k_ids = set(retrieved_ids[:k])
    hits = sum(1 for rid in retrieved_ids[:k] if rid in relevant_ids)
    return hits / k


def mrr(relevant_ids: List[str], retrieved_ids: List[str]) -> float:
    """MRR = 第一个正确结果排名的倒数均值"""
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevant_ids: List[str], retrieved_ids: List[str], k: int) -> float:
    """NDCG@K = 带位置衰减的排序质量"""
    rel_set = set(relevant_ids)

    # DCG
    dcg = 0.0
    for i, rid in enumerate(retrieved_ids[:k]):
        if rid in rel_set:
            dcg += 1.0 / math.log2(i + 2)  # i+2 因为 rank 从 1 开始

    # IDCG (理想排序: 所有相关结果排在最前面)
    idcg = 0.0
    for i in range(min(len(relevant_ids), k)):
        idcg += 1.0 / math.log2(i + 2)

    return dcg / idcg if idcg > 0 else 0.0


def percentile(data: List[float], p: float) -> float:
    """计算百分位数"""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (p / 100.0) * (len(sorted_data) - 1)
    if idx.is_integer():
        return sorted_data[int(idx)]
    lower = int(idx)
    upper = lower + 1
    frac = idx - lower
    return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac


# ============================================================
# 2. 评测器
# ============================================================

class EvalCollector:
    """单次实验的结果收集器"""

    def __init__(self, name: str):
        self.name = name
        self.results: List[dict] = []
        self.latencies_ms: List[float] = []

    def add(self, result: dict):
        self.results.append(result)
        self.latencies_ms.append(result.get("latency_ms", 0))


@dataclass
class EvalReport:
    """评测报告"""
    experiment_name: str = ""
    total_queries: int = 0
    recall_at_3: float = 0.0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    precision_at_5: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    # 分层统计
    by_difficulty: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment": self.experiment_name,
            "total_queries": self.total_queries,
            "recall@3": round(self.recall_at_3, 4),
            "recall@5": round(self.recall_at_5, 4),
            "recall@10": round(self.recall_at_10, 4),
            "precision@5": round(self.precision_at_5, 4),
            "mrr": round(self.mrr, 4),
            "ndcg@5": round(self.ndcg_at_5, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p50_latency_ms": round(self.p50_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "by_difficulty": {
                k: {
                    "recall@5": round(v["recall@5"], 4),
                    "mrr": round(v["mrr"], 4),
                }
                for k, v in self.by_difficulty.items()
            },
        }


def run_experiment(
    engine: MemorySearchEngine,
    embed_client,
    queries: List[dict],
    id_map: Dict[str, str],
    search_mode: str,
    bm25_weight: float = 0.3,
    faiss_weight: float = 0.7,
    top_k_list: tuple = (3, 5, 10),
) -> EvalCollector:
    """
    运行一次评测实验。

    Args:
        engine: 检索引擎
        embed_client: Embedding 客户端
        queries: 标注查询列表
        id_map: dataset_id → real_record_id 的映射
        search_mode: "bm25" | "faiss" | "hybrid"
        bm25_weight: BM25 权重（仅 hybrid 模式）
        faiss_weight: FAISS 权重（仅 hybrid 模式）
        top_k_list: 需要计算的 K 值

    Returns:
        EvalCollector 包含每条 query 的结果
    """
    collector = EvalCollector(
        name=f"{search_mode}"
        if search_mode != "hybrid"
        else f"hybrid({bm25_weight}:{faiss_weight})"
    )

    for query_item in queries:
        query_text = query_item["query_text"]
        # 将 dataset ID 映射为真实的 record ID
        relevant_ids = [id_map.get(rid, rid) for rid in query_item["relevant_ids"]]

        t0 = time.perf_counter()

        # 根据模式执行搜索
        if search_mode == "bm25":
            results = engine.search_bm25(query_text, top_k=max(top_k_list))
        elif search_mode == "faiss":
            query_vec = embed_client.embed(query_text)
            results = engine.search_faiss(query_text, query_vec, top_k=max(top_k_list))
        elif search_mode == "hybrid":
            query_vec = embed_client.embed(query_text)
            results = engine.search_hybrid(
                query_text, query_vec,
                top_k=max(top_k_list),
                bm25_weight=bm25_weight,
                faiss_weight=faiss_weight,
            )
        else:
            raise ValueError(f"未知搜索模式: {search_mode}")

        latency_ms = (time.perf_counter() - t0) * 1000
        retrieved_ids = [r["record_id"] for r in results]

        # 计算各项指标
        metrics = {
            "query_id": query_item["query_id"],
            "query_text": query_text,
            "relevant_ids": list(relevant_ids),
            "retrieved_ids": retrieved_ids,
            "difficulty": query_item["difficulty"],
            "domain": query_item["domain"],
            "latency_ms": latency_ms,
        }
        for k in top_k_list:
            metrics[f"recall@{k}"] = recall_at_k(list(relevant_ids), retrieved_ids, k)
            if k == 5:
                metrics["precision@5"] = precision_at_k(list(relevant_ids), retrieved_ids, k)
                metrics["ndcg@5"] = ndcg_at_k(list(relevant_ids), retrieved_ids, k)
        metrics["mrr"] = mrr(list(relevant_ids), retrieved_ids)

        collector.add(metrics)

    return collector


def aggregate_results(collector: EvalCollector, queries: List[dict]) -> EvalReport:
    """将收集器中的原始结果汇总为评测报告"""
    report = EvalReport()
    report.experiment_name = collector.name
    report.total_queries = len(collector.results)

    if not collector.results:
        return report

    # 全局指标
    recall3_list = [r["recall@3"] for r in collector.results]
    recall5_list = [r["recall@5"] for r in collector.results]
    recall10_list = [r["recall@10"] for r in collector.results]
    precision5_list = [r["precision@5"] for r in collector.results]
    mrr_list = [r["mrr"] for r in collector.results]
    ndcg5_list = [r["ndcg@5"] for r in collector.results]

    report.recall_at_3 = sum(recall3_list) / len(recall3_list)
    report.recall_at_5 = sum(recall5_list) / len(recall5_list)
    report.recall_at_10 = sum(recall10_list) / len(recall10_list)
    report.precision_at_5 = sum(precision5_list) / len(precision5_list)
    report.mrr = sum(mrr_list) / len(mrr_list)
    report.ndcg_at_5 = sum(ndcg5_list) / len(ndcg5_list)

    # 延迟统计
    if collector.latencies_ms:
        report.avg_latency_ms = sum(collector.latencies_ms) / len(collector.latencies_ms)
        report.p50_latency_ms = percentile(collector.latencies_ms, 50)
        report.p95_latency_ms = percentile(collector.latencies_ms, 95)
        report.p99_latency_ms = percentile(collector.latencies_ms, 99)

    # 分层统计
    by_diff: Dict[str, dict] = defaultdict(lambda: {"recall@5": [], "mrr": []})
    for r in collector.results:
        diff = r["difficulty"]
        by_diff[diff]["recall@5"].append(r["recall@5"])
        by_diff[diff]["mrr"].append(r["mrr"])
    for diff, vals in by_diff.items():
        report.by_difficulty[diff] = {
            "recall@5": sum(vals["recall@5"]) / len(vals["recall@5"]),
            "mrr": sum(vals["mrr"]) / len(vals["mrr"]),
            "count": len(vals["recall@5"]),
        }

    return report


# ============================================================
# 3. 主评测入口
# ============================================================

def main():
    print("=" * 70)
    print("  OS Agent Memory Engine — 检索评测基准")
    print("=" * 70)

    # ── 0. 确保数据集存在 ──
    dataset_path = save_dataset()
    dataset = load_dataset(dataset_path)
    memories = dataset["memories"]
    queries = dataset["queries"]
    print(f"\n[数据集] {len(memories)} 条记忆 | {len(queries)} 个标注查询")
    print(f"[难度分布] exact_match:6 | semantic:6 | distractor:5 | cross_domain:3")

    # ── 1. 初始化引擎 ──
    print("\n" + "-" * 70)
    print("[1] 初始化检索引擎...")
    embed_client = create_embedding_client(dim=768, latency=0.0, seed=42)
    print(f"    Embedding: {type(embed_client).__name__} (dim={embed_client.get_dimension()})")

    store = MemoryStore(":memory:")
    print(f"    MemoryStore: 内存模式")

    # 批量生成 Embedding 并写入，同时建立 ID 映射
    print(f"    写入 {len(memories)} 条记忆数据...")
    id_map: Dict[str, str] = {}  # dataset_id → real_record_id
    for i, mem in enumerate(memories):
        vec = embed_client.embed(mem["content"])
        record = store.add(content=mem["content"], embedding=vec, metadata={"domain": mem["domain"]})
        id_map[mem["id"]] = record.id  # 建立映射
    print(f"    完成: {len(store)} 条记录, ID 映射: {len(id_map)} 条")

    engine = MemorySearchEngine(store, embedding_dim=768)
    engine.build_index()
    print(f"    BM25 索引: {'OK' if engine.bm25.is_ready else 'FAIL'}")
    print(f"    FAISS 索引: {'OK' if engine.faiss.is_ready else 'FAIL'}")

    # ── 2. 消融实验 ──
    print("\n" + "=" * 70)
    print("[2] 消融实验")
    print("=" * 70)

    experiments = [
        ("bm25",         "纯 BM25 关键词基线", None, None),
        ("faiss",        "纯 FAISS 向量基线 (Mock)", None, None),
        ("hybrid",       "Hybrid (BM25:FAISS = 0.1:0.9)", 0.1, 0.9),
        ("hybrid",       "Hybrid (BM25:FAISS = 0.3:0.7)", 0.3, 0.7),
        ("hybrid",       "Hybrid (BM25:FAISS = 0.5:0.5)", 0.5, 0.5),
        ("hybrid",       "Hybrid (BM25:FAISS = 0.7:0.3)", 0.7, 0.3),
    ]

    all_reports: List[EvalReport] = []

    for mode, label, bw, fw in experiments:
        print(f"\n{'─' * 70}")
        print(f"  {label}")
        print(f"{'─' * 70}")

        collector = run_experiment(
            engine, embed_client, queries, id_map,
            search_mode=mode,
            bm25_weight=bw if bw else 0.3,
            faiss_weight=fw if fw else 0.7,
        )
        report = aggregate_results(collector, queries)
        all_reports.append(report)

        # 打印报告
        d = report.to_dict()
        print(f"  Recall@3:   {d['recall@3']:.4f}  |  Recall@5:   {d['recall@5']:.4f}  |  Recall@10:  {d['recall@10']:.4f}")
        print(f"  Precision@5:{d['precision@5']:.4f}  |  MRR:        {d['mrr']:.4f}  |  NDCG@5:     {d['ndcg@5']:.4f}")
        print(f"  延迟: avg={d['avg_latency_ms']:.2f}ms  p50={d['p50_latency_ms']:.2f}ms  p95={d['p95_latency_ms']:.2f}ms  p99={d['p99_latency_ms']:.2f}ms")

    # ── 3. 汇总对比表 ──
    print("\n" + "=" * 70)
    print("[3] 消融实验对比汇总")
    print("=" * 70)

    header = f"{'实验':<32} {'R@5':>8} {'P@5':>8} {'MRR':>8} {'NDCG@5':>8} {'P95(ms)':>9}"
    print(header)
    print("-" * 70)

    best_recall = 0.0
    best_config = ""

    for report in all_reports:
        d = report.to_dict()
        line = (
            f"{d['experiment']:<32} "
            f"{d['recall@5']:>8.4f} "
            f"{d['precision@5']:>8.4f} "
            f"{d['mrr']:>8.4f} "
            f"{d['ndcg@5']:>8.4f} "
            f"{d['p95_latency_ms']:>8.2f}"
        )
        print(line)
        if d['recall@5'] > best_recall:
            best_recall = d['recall@5']
            best_config = d['experiment']

    # ── 4. 分层分析 ──
    print("\n" + "=" * 70)
    print("[4] 按难度分层 (基于默认 Hybrid 0.3:0.7)")
    print("=" * 70)

    default_report = all_reports[2]  # hybrid(0.3:0.7)
    for diff, vals in default_report.by_difficulty.items():
        bar = "█" * int(vals["recall@5"] * 40)
        print(f"  {diff:<16}  Recall@5={vals['recall@5']:.4f}  MRR={vals['mrr']:.4f}  n={vals['count']}  {bar}")

    # ── 5. 赛题指标对照 ──
    print("\n" + "=" * 70)
    print("[5] 赛题指标达标情况")
    print("=" * 70)

    print(f"\n  {'指标':<20} {'目标值':<15} {'当前最佳':<15} {'状态':<10}")
    print(f"  {'-'*55}")

    # Recall@5 >= 85%
    status_recall = "✓ 达标" if best_recall >= 0.85 else "✗ 未达标"
    print(f"  {'Recall@5':<20} {'≥ 85%':<15} {best_recall*100:.1f}%{'':>9} {status_recall}")

    # P95 < 100ms
    p95_best = min(r.p95_latency_ms for r in all_reports)
    status_latency = "✓ 达标" if p95_best < 100 else "✗ 未达标"
    print(f"  {'P95 延迟':<20} {'< 100ms':<15} {p95_best:.1f}ms{'':>8} {status_latency}")

    print(f"\n  说明: Mock Embedding 使用确定性随机向量，FAISS 无法提供真实语义检索。")
    print(f"        接入麒麟 SDK 后 FAISS 和 Hybrid 指标预计大幅提升。")
    print(f"        BM25 关键词检索在 Mock 环境下为真实指标，已可验证检索框架正确性。")

    # ── 6. 输出 JSON 报告 ──
    report_path = os.path.join(os.path.dirname(__file__), "eval_report.json")
    report_data = {
        "summary": {
            "best_config": best_config,
            "best_recall_at_5": best_recall,
            "best_p95_latency_ms": p95_best,
            "target_recall": 0.85,
            "target_p95_ms": 100,
        },
        "experiments": [r.to_dict() for r in all_reports],
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\n  评测报告已保存: {report_path}")

    print("\n" + "=" * 70)
    print("  评测完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
