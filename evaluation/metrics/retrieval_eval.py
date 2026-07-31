"""
知识检索评测模块

评测检索的召回率、MRR、NDCG 等指标。

数据集格式以 tests/eval_dataset.py 的实际格式为准:
    {
        "memories": [{"id", "content", "domain"}, ...],
        "queries": [{"query_id", "query_text", "relevant_ids", "difficulty", "domain"}, ...],
        "metadata": {...}
    }
"""

import json
import math

from memoryhub.adapter.schemas import EvalReport, EvalResult, SearchRequest

DEFAULT_TOP_K = 10


class RetrievalEvaluator:
    """
    知识检索评测器

    使用方式:
        evaluator = RetrievalEvaluator(retriever)
        report = evaluator.run("tests/eval_dataset.json")
    """

    def __init__(self, retriever=None, top_k: int = DEFAULT_TOP_K):
        """
        参数:
            retriever: HybridRetriever 实例
            top_k: 检索截断位置（Recall@K/NDCG@K 的 K 上限）
        """
        self.retriever = retriever
        self.top_k = top_k

    def run(self, dataset_path: str) -> EvalReport:
        """
        运行检索评测

        数据流:
            加载测试数据集 → 逐条检索 → 与标注对比 → 计算指标

        参数:
            dataset_path: 测试数据集路径（eval_dataset.py save_dataset() 产物）

        返回:
            EvalReport（recall_at_k / precision / mrr 均为全体 query 均值，
            recall_at_k/precision 按 K=self.top_k 计算；
            details 为逐 query 明细）
        """
        if self.retriever is None:
            raise ValueError("RetrievalEvaluator 需要 retriever 实例")

        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        queries = dataset["queries"]

        recalls, precisions, mrrs, ndcgs, latencies = [], [], [], [], []
        details: list[EvalResult] = []

        for item in queries:
            # 字段映射：eval_dataset.py 实际格式 query_id/query_text/relevant_ids
            expected_ids = list(item["relevant_ids"])
            response = self.retriever.search(
                SearchRequest(query=item["query_text"], top_k=self.top_k)
            )
            retrieved_ids = [r.memory_id for r in response.results]

            recalls.append(self.recall_at_k(expected_ids, retrieved_ids, self.top_k))
            precisions.append(self.precision_at_k(expected_ids, retrieved_ids, self.top_k))
            mrrs.append(self.mrr(expected_ids, retrieved_ids))
            ndcgs.append(self.ndcg(expected_ids, retrieved_ids, self.top_k))
            latencies.append(response.latency_ms)

            details.append(
                EvalResult(
                    sample_id=item["query_id"],
                    predicted=",".join(retrieved_ids),
                    expected=",".join(expected_ids),
                    correct=self.recall_at_k(expected_ids, retrieved_ids, self.top_k) > 0,
                    latency_ms=response.latency_ms,
                )
            )

        n = len(queries)
        return EvalReport(
            task_name="retrieval",
            total_samples=n,
            recall_at_k=sum(recalls) / n if n else 0.0,
            precision=sum(precisions) / n if n else 0.0,
            mrr=sum(mrrs) / n if n else 0.0,
            accuracy=sum(ndcgs) / n if n else 0.0,  # accuracy 字段复用为 NDCG@K
            avg_latency_ms=sum(latencies) / n if n else 0.0,
            p95_latency_ms=percentile(latencies, 95),
            details=details,
        )

    def recall_at_k(self, expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
        """
        计算 Recall@K

        Recall@K = |relevant ∩ retrieved[:K]| / |relevant|

        参数:
            expected_ids: 期望检索到的记忆 ID 列表
            retrieved_ids: 实际检索到的记忆 ID 列表
            k: 截断位置

        返回:
            Recall@K 值
        """
        if not expected_ids:
            return 1.0
        top_k_ids = set(retrieved_ids[:k])
        hits = sum(1 for rid in expected_ids if rid in top_k_ids)
        return hits / len(expected_ids)

    def precision_at_k(self, expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
        """
        计算 Precision@K

        Precision@K = |relevant ∩ retrieved[:K]| / K
        """
        if k <= 0:
            return 0.0
        rel_set = set(expected_ids)
        hits = sum(1 for rid in retrieved_ids[:k] if rid in rel_set)
        return hits / k

    def mrr(self, expected_ids: list[str], retrieved_ids: list[str]) -> float:
        """
        计算单条 query 的 Reciprocal Rank（首个相关结果的倒数排名，无相关记 0）

        对全部 query 取均值即为 MRR。

        返回:
            RR 值
        """
        rel_set = set(expected_ids)
        for rank, rid in enumerate(retrieved_ids, start=1):
            if rid in rel_set:
                return 1.0 / rank
        return 0.0

    def ndcg(self, expected_ids: list[str], retrieved_ids: list[str], k: int) -> float:
        """
        计算 NDCG@K (Normalized Discounted Cumulative Gain)

        二元相关性，DCG = Σ rel_i / log2(i+1)，除以理想 DCG 归一化。

        返回:
            NDCG@K 值
        """
        rel_set = set(expected_ids)
        dcg = 0.0
        for i, rid in enumerate(retrieved_ids[:k]):
            if rid in rel_set:
                dcg += 1.0 / math.log2(i + 2)  # rank = i+1，log2(rank+1)

        idcg = 0.0
        for i in range(min(len(rel_set), k)):
            idcg += 1.0 / math.log2(i + 2)

        return dcg / idcg if idcg > 0 else 0.0


def percentile(data: list[float], p: float) -> float:
    """线性插值百分位数"""
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
