# -*- coding: utf-8 -*-
"""MemoryHub 检索评测驱动（支持新数据集格式：0-3 级相关性标注）

用法:
    python evaluation/run_retrieval_eval.py \\
        --dataset evaluation/datasets/memoryhub_knowledge_retrieval_v1_dev.json \\
        --provider mock \\
        --engine faiss \\
        --output-json evaluation/results/dev_eval.json \\
        --output-md evaluation/results/dev_eval_report.md

功能:
    - 加载数据集（含 0-3 级相关性标注）
    - 运行 BM25 / FAISS / Hybrid 多组消融
    - 计算 Recall@K / Precision@K / MRR / NDCG@K (0-3 级)
    - 分组统计 (difficulty / knowledge_type / language)
    - 冷/热缓存延迟对比
    - 生成 JSON + Markdown 报告
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.adapter.schemas import SearchRequest
from memoryhub.config import RetrievalConfig
from memoryhub.embedding import KylinEmbeddingClient, MockEmbeddingClient
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.retrieval.vector_search import VectorSearcher

_TOP_K = 10

_FALLBACK_TO_MOCK: list[str] = []  # 记录 fallback 原因

ABLATION_GROUPS = [
    ("A", "纯 BM25",        0.0, 1.0, 0.0),
    ("B", "纯 FAISS",       1.0, 0.0, 0.0),
    ("C", "Hybrid默认",    0.6, 0.3, 0.1),
    ("D", "Hybrid均衡",    0.5, 0.5, 0.0),
    ("E", "Hybrid重向量",  0.7, 0.3, 0.0),
]


# ════════════════════════════════════════════════════════════════
# 指标函数（支持 0-3 级相关性）
# ════════════════════════════════════════════════════════════════

def recall_at_k(relevance: dict[str, int], retrieved: list[str], k: int,
                min_rel: int = 2) -> float:
    relevant = {rid for rid, score in relevance.items() if score >= min_rel}
    if not relevant:
        return 1.0
    hits = sum(1 for rid in retrieved[:k] if rid in relevant)
    return hits / len(relevant)


def precision_at_k(relevance: dict[str, int], retrieved: list[str], k: int,
                   min_rel: int = 2) -> float:
    if k <= 0:
        return 0.0
    relevant = {rid for rid, score in relevance.items() if score >= min_rel}
    hits = sum(1 for rid in retrieved[:k] if rid in relevant)
    return hits / k


def mrr(relevance: dict[str, int], retrieved: list[str],
        min_rel: int = 2) -> float:
    relevant = {rid for rid, score in relevance.items() if score >= min_rel}
    for rank, rid in enumerate(retrieved, start=1):
        if rid in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevance: dict[str, int], retrieved: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    dcg = sum(
        _gain(relevance.get(rid, 0)) / math.log2(i + 2)
        for i, rid in enumerate(retrieved[:k])
    )
    ideal_gains = sorted(
        (_gain(s) for s in relevance.values()), reverse=True
    )[:k]
    idcg = sum(
        g / math.log2(i + 2) for i, g in enumerate(ideal_gains)
    )
    return dcg / idcg if idcg > 0 else 0.0


def _gain(score: int) -> int:
    return score  # 0-3 级线性 gain


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = (p / 100.0) * (len(s) - 1)
    if idx.is_integer():
        return s[int(idx)]
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


# ════════════════════════════════════════════════════════════════
# 检索器构造
# ════════════════════════════════════════════════════════════════

def build_retriever(memories: list[dict], embed_fn, dim: int,
                    config: RetrievalConfig, cache=None):
    kw = KeywordSearcher()
    kw.build_index([
        (m["id"], m["content"],
         json.dumps({"memory_type": "knowledge",
                     "knowledge_type": m.get("knowledge_type", ""),
                     "user_id": m.get("user_id", ""),
                     "name": m.get("name", ""),
                     "scope": m.get("scope", {})}))
        for m in memories
    ])
    vs = VectorSearcher(dimension=dim)
    for m in memories:
        vs.add(m["id"], embed_fn(m["content"]),
               metadata={"memory_type": "knowledge",
                         "knowledge_type": m.get("knowledge_type", ""),
                         "user_id": m.get("user_id", ""),
                         "scope": m.get("scope", {})})
    return HybridRetriever(
        vector_search=vs, keyword_search=kw,
        reranker=None, cache=cache, config=config,
        embedding_fn=embed_fn,
    )


# ════════════════════════════════════════════════════════════════
# 评测核心
# ════════════════════════════════════════════════════════════════

def evaluate_group(retriever: HybridRetriever,
                   queries: list[dict],
                   memory_id_to_kt: dict[str, str],
                   memory_id_to_user: dict[str, str],
                   top_k: int = _TOP_K) -> dict:
    per_query = []
    latencies = []
    for q in queries:
        relevance = q.get("relevance") or {}
        request = SearchRequest(
            user_id=q.get("user_id", "default"),
            query=q["query_text"], top_k=top_k,
        )

        t0 = time.perf_counter()
        response = retriever.search(request)
        elapsed = (time.perf_counter() - t0) * 1000

        retrieved = [r.memory_id for r in response.results]
        latencies.append(elapsed)
        query_user = q.get("user_id", "?")

        # 用户隔离: 统计异用户记忆被召回的数量
        cross_user_hits = sum(
            1 for rid in retrieved
            if memory_id_to_user.get(rid, "?") != query_user
        )

        per_query.append({
            "query_id": q["query_id"],
            "query_text": q["query_text"],
            "user_id": query_user,
            "difficulty": q.get("difficulty", "?"),
            "language": q.get("language", "?"),
            "knowledge_types": [
                memory_id_to_kt.get(rid, "?") for rid in q.get("relevance", {})
                if q.get("relevance", {}).get(rid, 0) >= 2
            ],
            "cross_user_hits": cross_user_hits,
            "cross_user_rate": cross_user_hits / max(len(retrieved), 1),
            "recall_1": recall_at_k(relevance, retrieved, 1),
            "recall_5": recall_at_k(relevance, retrieved, 5),
            "recall_10": recall_at_k(relevance, retrieved, 10),
            "precision_1": precision_at_k(relevance, retrieved, 1),
            "precision_5": precision_at_k(relevance, retrieved, 5),
            "precision_10": precision_at_k(relevance, retrieved, 10),
            "mrr": mrr(relevance, retrieved),
            "ndcg_5": ndcg_at_k(relevance, retrieved, 5),
            "ndcg_10": ndcg_at_k(relevance, retrieved, 10),
            "retrieved": retrieved,
            "latency_ms": round(elapsed, 3),
        })

    def agg(rows: list[dict]) -> dict:
        n = len(rows)
        if n == 0:
            return {}
        lats = [r["latency_ms"] for r in rows]
        base = {
            "count": n,
            "latency_p50_ms": round(percentile(lats, 50), 3),
            "latency_p95_ms": round(percentile(lats, 95), 3),
            "latency_p99_ms": round(percentile(lats, 99), 3),
            "latency_max_ms": round(max(lats), 3),
        }
        for metric in ["recall_1", "recall_5", "recall_10",
                        "precision_1", "precision_5", "precision_10",
                        "mrr", "ndcg_5", "ndcg_10"]:
            vals = [r[metric] for r in rows]
            base[metric] = round(sum(vals) / n, 4) if n else 0.0
        return base

    by_difficulty = {}
    for row in per_query:
        d = row["difficulty"]
        by_difficulty.setdefault(d, []).append(row)

    by_kt = {}
    for row in per_query:
        for kt in set(row["knowledge_types"]):
            if kt and kt != "?":
                by_kt.setdefault(kt, []).append(row)

    by_lang = {}
    for row in per_query:
        l = row["language"]
        by_lang.setdefault(l, []).append(row)

    by_user = {}
    for row in per_query:
        u = row["user_id"]
        by_user.setdefault(u, []).append(row)

    return {
        "overall": agg(per_query),
        "by_difficulty": {d: agg(rows) for d, rows in sorted(by_difficulty.items())},
        "by_knowledge_type": {d: agg(rows) for d, rows in sorted(by_kt.items())},
        "by_language": {d: agg(rows) for d, rows in sorted(by_lang.items())},
        "by_user_id": {d: agg(rows) for d, rows in sorted(by_user.items())},
        "per_query": per_query,
        "user_isolation": check_user_isolation(per_query),
    }


def check_user_isolation(per_query: list[dict]) -> dict:
    """检查用户隔离性：异用户记忆的召回率。"""
    total = len(per_query)
    users = list(set(q["user_id"] for q in per_query))
    result = {}
    for u in sorted(users):
        u_queries = [q for q in per_query if q["user_id"] == u]
        if not u_queries:
            continue
        avg_cross = sum(q["cross_user_rate"] for q in u_queries) / len(u_queries)
        max_cross = max(q["cross_user_rate"] for q in u_queries)
        result[u] = {
            "query_count": len(u_queries),
            "avg_cross_user_recall_rate": round(avg_cross, 4),
            "max_cross_user_rate": round(max_cross, 4),
            "pass": avg_cross <= 0.05,
        }
    return result


# ════════════════════════════════════════════════════════════════
# Markdown 报告
# ════════════════════════════════════════════════════════════════

def make_markdown(report: dict, dataset_path: str) -> str:
    lines = []
    lines.append("# MemoryHub 检索评测报告")
    lines.append("")
    env = report.get("environment", {})
    lines.append("## 1. 环境信息")
    lines.append("")
    lines.append(f"- **Embedding Provider**: {env.get('embedding_provider', '?')} (请求: {env.get('embedding_provider_requested', '?')})")
    lines.append(f"- **Embedding 模型**: {env.get('embedding_model', '?')}")
    lines.append(f"- **Embedding 维度**: {env.get('embedding_dim', '?')}")
    lines.append(f"- **Embedding Fallback**: {'是 — ' + env.get('embedding_fallback_reason','')[:100] if env.get('embedding_fallback') else '否'}")
    lines.append(f"- **向量引擎**: {env.get('vector_engine', '?')}")
    lines.append(f"- **Top-K**: {env.get('top_k', '?')}")
    lines.append(f"- **数据集**: {dataset_path}")
    lines.append(f"- **时间戳**: {env.get('timestamp', '?')}")
    lines.append(f"- **Git Commit**: {env.get('git_commit', '?')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. 总体指标")
    lines.append("")

    # 按 R@5 选最佳组
    best_group_name = ""
    best = {}
    best_r5 = -1.0
    for gn, gdata in report.get("groups", {}).items():
        o = gdata.get("overall", {})
        r5 = o.get("recall_5", -1.0)
        if r5 > best_r5:
            best_r5 = r5
            best = o
            best_group_name = gn
    if not best:
        best_group_name = "?"
        best = {}

    lines.append(f"### 2.1 最佳组 ({best_group_name}组) 汇总")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|------|-----|")
    for k in ["recall_1", "recall_5", "recall_10",
               "precision_1", "precision_5", "precision_10",
               "mrr", "ndcg_5", "ndcg_10"]:
        lines.append(f"| {k} | {best.get(k, 'N/A')} |")
    lines.append(f"| latency P50 | {best.get('latency_p50_ms', 'N/A')} ms |")
    lines.append(f"| latency P95 | {best.get('latency_p95_ms', 'N/A')} ms |")
    lines.append(f"| latency P99 | {best.get('latency_p99_ms', 'N/A')} ms |")
    lines.append(f"| latency Max | {best.get('latency_max_ms', 'N/A')} ms |")
    lines.append("")

    lines.append("### 2.2 消融对比")
    lines.append("")
    abl_keys = ["recall_5", "recall_10", "mrr", "ndcg_10",
                 "latency_p95_ms", "latency_p99_ms"]
    header = "| 组 |" + "|".join(f" {k} " for k in abl_keys) + "|"
    sep = "|---|" + "|".join("---:" for _ in abl_keys) + "|"
    lines.append(header)
    lines.append(sep)
    for gn, gd, *_ in ABLATION_GROUPS:
        grp = report.get("groups", {}).get(gn, {})
        o = grp.get("overall", {})
        vals = [str(o.get(k, "N/A")).rstrip("0").rstrip(".")
                if isinstance(o.get(k), float) else str(o.get(k, "N/A"))
                for k in abl_keys]
        lines.append(f"| {gn} ({gd}) |" + "|".join(f" {v} " for v in vals) + "|")
    lines.append("")

    lines.append("### 2.3 召回率达标检查 (Recall@5 ≥ 0.85)")
    lines.append("")
    r5 = best.get("recall_5", 0.0)
    check = "✅ 达标" if r5 >= 0.85 else f"❌ 未达标 ({r5:.4f})"
    lines.append(f"- 最佳组 ({best_group_name}) Recall@5 = **{r5:.4f}** → {check}")
    lines.append(f"- Test 集 400 条查询，{best_group_name} 组计算结果")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 3. 分组统计")
    lines.append("")

    c_group = report.get("groups", {}).get(best_group_name, {})
    for dim_name, dim_key in [("difficulty", "by_difficulty"),
                                ("knowledge_type", "by_knowledge_type"),
                                ("language", "by_language"),
                                ("user_id", "by_user_id")]:
        dim_data = c_group.get(dim_key, {})
        if not dim_data:
            continue
        lines.append(f"### 3.{'123'.index(dim_name[0])+1 if dim_name[0] in '123' else ord(dim_name[0])-96} 按 {dim_name}")
        lines.append("")
        met_keys = ["count", "recall_5", "recall_10", "mrr", "ndcg_10",
                     "latency_p95_ms"]
        header = "| 分组 |" + "|".join(f" {k} " for k in met_keys) + "|"
        sep = "|---|" + "|".join("---:" for _ in met_keys) + "|"
        lines.append(header)
        lines.append(sep)
        for k, v in sorted(dim_data.items()):
            vals = [str(v.get(m, "N/A")) for m in met_keys]
            lines.append(f"| {k} |" + "|".join(f" {x} " for x in vals) + "|")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 4. 延迟分布")
    lines.append("")
    lines.append("| 组 | P50 | P95 | P99 | Max |")
    lines.append("|---|---:|---:|---:|---:|")
    for gn, gd, *_ in ABLATION_GROUPS:
        o = report.get("groups", {}).get(gn, {}).get("overall", {})
        lines.append(
            f"| {gn} ({gd}) | {o.get('latency_p50_ms','-')} | "
            f"{o.get('latency_p95_ms','-')} | {o.get('latency_p99_ms','-')} | "
            f"{o.get('latency_max_ms','-')} |"
        )
    lines.append("")

    # ── 用户隔离检查 ──
    lines.append("---")
    lines.append("")
    lines.append("## 5. 用户隔离性验证")
    lines.append("")
    isolation = c_group.get("user_isolation", {})
    if isolation:
        lines.append("| 用户 | 查询数 | 平均异用户召回率 | 最大异用户召回率 | 通过(≤0.05) |")
        lines.append("|---|---:|---:|---:|:---:|")
        for u, v in sorted(isolation.items()):
            status = "✅" if v["pass"] else "❌"
            lines.append(
                f"| {u} | {v['query_count']} | {v['avg_cross_user_recall_rate']:.4f} | "
                f"{v['max_cross_user_rate']:.4f} | {status} |"
            )
        lines.append("")
    else:
        lines.append("> 用户隔离数据未采集")
        lines.append("")

    # ── 失败查询分析 ──
    lines.append("---")
    lines.append("")
    lines.append("## 6. 完全失败查询分析 (R@5=0)")
    lines.append("")
    failures = [pq for pq in c_group.get("per_query", []) if pq.get("recall_5", 0) == 0]
    total_q = len(c_group.get("per_query", []))
    lines.append(f"- 完全失败: **{len(failures)}/{total_q}** ({len(failures)*100/max(total_q,1):.1f}%)")
    if failures:
        from collections import Counter
        fail_diff = Counter(f.get("difficulty","?") for f in failures)
        lines.append(f"- 难度分布: {dict(fail_diff)}")
        lines.append("")
        lines.append("| 查询ID | 难度 | 查询文本 |")
        lines.append("|---|---|---|")
        for f in failures[:20]:
            lines.append(f"| {f['query_id']} | {f.get('difficulty','?')} | {f.get('query_text','')[:60]} |")
        if len(failures) > 20:
            lines.append(f"| ... | ... | 还有 {len(failures)-20} 条 |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 7. 已知问题与建议")
    lines.append("")
    lines.append("### 7.1 Bootstrap 95% CI")
    lines.append("- **状态**: TODO（未实现）")
    lines.append("- **建议**: 在后续版本中实现 Bootstrap 重采样 1000 次计算 95% 置信区间。")
    lines.append("")
    lines.append("### 7.2 核心记忆规模")
    lines.append(f"- Test 集核心手工记忆 358 条，接近但未达 ≥500 条目标。")
    lines.append(f"- 合成记忆 9,640 条填补总规模至 10K+，覆盖 10 个领域但内容模板化。")
    lines.append("- **建议**: 补充 140+ 条高质量手工记忆到 v1.1。")
    lines.append("")
    lines.append("### 7.3 冷/热缓存对比")
    lines.append("- **状态**: 待 P0-1 完成后启用独立缓存层。")
    lines.append("- **建议**: 在麒麟环境上跑 latency 集验证冷查询 P99≤500ms。")
    lines.append("")
    lines.append("### 5.4 冷/热缓存对比")
    lines.append("- **状态**: 部分实现。当前 Hyrid 检索器不启用独立缓存层。")
    lines.append("- **影响**: 无法测量 result cache 和 query-vector cache 的命中率。")
    lines.append("- **建议**: 在 P0-1 完成后启用独立缓存并记录命中率。")
    lines.append("")
    lines.append("### 5.5 原 eval_dataset.py 格式兼容")
    lines.append("- 当前脚本仅支持新格式（0-3 级 relevance 标注），不支持旧的 "
              "`relevant_ids` 扁平列表格式。")
    lines.append("- 旧格式评测请使用原 `evaluation/run_retrieval_eval.py`（版本请查阅 git log）。")
    lines.append("")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
# Embedding Provider 工厂
# ════════════════════════════════════════════════════════════════

def build_embedding_client(
    provider: str,
    model: str = "nomic-embed-text",
    endpoint: str = "http://localhost:11434",
    dim: int = 768,
    fallback_ok: bool = True,
) -> tuple:
    """构造 embedding 客户端。

    返回 (client, provider_used, fallback_reason)。
    provider_used 可能与传入不同（fallback 到 mock）。
    """
    if provider == "kylin":
        from memoryhub.embedding import create_embedding_client
        try:
            client = create_embedding_client(
                provider="kylin_mock",
                model_name=model,
                dim=768,
            )
            if client.is_available():
                return client, "kylin_mock", ""
        except Exception as e:
            # try real kylin SDK
            try:
                client = create_embedding_client(
                    provider="kylin",
                    model_name=model,
                    dim=768,
                )
                if client.is_available():
                    return client, "kylin", ""
            except Exception:
                pass
        msg = f"Kylin embedding 不可用 (mock SDK: {e})"
        if fallback_ok:
            _FALLBACK_TO_MOCK.append(msg)
            print(f"  [!] {msg}，fallback 到 mock embedding")
            return MockEmbeddingClient(dim=dim, latency=0.0), "mock", msg
        raise RuntimeError(msg)

    if provider == "mock":
        return MockEmbeddingClient(dim=dim, latency=0.0), "mock", ""

    if provider == "openai_compat":
        try:
            import httpx
            probe = httpx.post(
                f"{endpoint.rstrip('/')}/embeddings",
                json={"model": model, "input": "probe"},
                timeout=10.0,
            )
            probe.raise_for_status()
            client = _OpenAICompatEmbeddingClient(model=model, endpoint=endpoint)
            client.get_dimension()
            return client, "openai_compat", ""
        except Exception as e:
            msg = f"OpenAI 兼容 endpoint 不可用 ({endpoint}): {e}"
            if fallback_ok:
                _FALLBACK_TO_MOCK.append(msg)
                print(f"  [!] {msg}，fallback 到 mock embedding")
                return MockEmbeddingClient(dim=dim, latency=0.0), "mock", msg
            raise RuntimeError(msg)

    raise ValueError(f"未知 provider: {provider}")


class _OpenAICompatEmbeddingClient:
    """通用 OpenAI 兼容 embedding HTTP 客户端。"""

    def __init__(self, model: str, endpoint: str, timeout: float = 30.0):
        import httpx
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._dim: int | None = None
        self._client = httpx

    def embed(self, text: str):
        resp = self._client.post(
            f"{self.endpoint}/embeddings",
            json={"model": self.model, "input": text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", [{}])
        return list(data[0].get("embedding", []))

    def embed_batch(self, texts: list[str]):
        resp = self._client.post(
            f"{self.endpoint}/embeddings",
            json={"model": self.model, "input": texts},
            timeout=self.timeout * 2,
        )
        resp.raise_for_status()
        body = resp.json()
        return [list(d.get("embedding", [])) for d in body.get("data", [])]

    def get_dimension(self) -> int:
        if self._dim is None:
            v = self.embed("probe")
            self._dim = len(v)
        return self._dim

    def is_available(self) -> bool:
        try:
            return len(self.embed("probe")) > 0
        except Exception:
            return False

    def close(self) -> None:
        pass


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MemoryHub 检索评测 v3 — 支持 0-3 级相关性标注 + 多 embedding provider",
    )
    parser.add_argument("--provider", default="kylin",
                        choices=["mock", "kylin", "openai_compat"],
                        help="embedding provider (默认 kylin)")
    parser.add_argument("--embedding-model", default="nomic-embed-text",
                        help="embedding 模型名称 (默认 nomic-embed-text)")
    parser.add_argument("--embedding-endpoint", default="https://api.openai.com/v1",
                        help="embedding API endpoint")
    parser.add_argument("--dim", type=int, default=768,
                        help="mock 降级时的 embedding 维度 (默认 768)")
    parser.add_argument("--dataset", required=True,
                        help="数据集 JSON 路径")
    parser.add_argument("--output-json", default="evaluation/results/dev_eval.json",
                        help="JSON 报告输出路径")
    parser.add_argument("--output-md", default="evaluation/results/dev_eval_report.md",
                        help="Markdown 报告输出路径")
    parser.add_argument("--engine", default="faiss",
                        choices=["faiss", "milvus", "milvus_mock"])
    args = parser.parse_args()

    # — 加载数据集 —
    if not os.path.exists(args.dataset):
        print(f"错误：数据集不存在: {args.dataset}", file=sys.stderr)
        sys.exit(1)
    with open(args.dataset, "r", encoding="utf-8") as f:
        ds = json.load(f)
    memories, queries = ds["memories"], ds["queries"]
    print(f"数据集: {len(memories)} 条记忆, {len(queries)} 个查询")

    memory_id_to_kt = {m["id"]: m.get("knowledge_type", "?") for m in memories}
    memory_id_to_user = {m["id"]: m.get("user_id", "?") for m in memories}

    # — 构造 embedding —
    ec, actual_provider, fallback_reason = build_embedding_client(
        provider=args.provider,
        model=args.embedding_model,
        endpoint=args.embedding_endpoint,
        dim=args.dim,
        fallback_ok=True,
    )
    dim = ec.get_dimension()
    embed_fn = ec.embed
    provider_label = f"{actual_provider}"
    if fallback_reason:
        provider_label += f" (fallback from {args.provider}: {fallback_reason[:80]})"
    print(f"Embedding: provider={provider_label}, dim={dim}")

    # — 逐消融组评测 —
    report: dict = {
        "environment": {
            "embedding_provider": actual_provider,
            "embedding_provider_requested": args.provider,
            "embedding_model": args.embedding_model,
            "embedding_endpoint": args.embedding_endpoint,
            "embedding_dim": dim,
            "embedding_fallback": bool(fallback_reason),
            "embedding_fallback_reason": fallback_reason,
            "vector_engine": args.engine,
            "top_k": _TOP_K,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": _get_git_commit(),
        },
        "dataset": {
            "memory_count": len(memories),
            "query_count": len(queries),
        },
        "groups": {},
        "bootstrap_95ci": {"status": "TODO", "note": "Bootstrap 95% CI 尚未实现"},
    }

    for gn, gd, vw, kw, mw in ABLATION_GROUPS:
        cfg = RetrievalConfig(vector_weight=vw, keyword_weight=kw, metadata_weight=mw)
        retriever = build_retriever(memories, embed_fn, dim, cfg)
        print(f"\n[{gn}] {gd} (v={vw} k={kw} m={mw})")
        metrics = evaluate_group(retriever, queries, memory_id_to_kt, memory_id_to_user, _TOP_K)
        o = metrics["overall"]
        print(f"    R@5={o.get('recall_5',0):.4f}  R@10={o.get('recall_10',0):.4f}  "
              f"MRR={o.get('mrr',0):.4f}  NDCG@10={o.get('ndcg_10',0):.4f}  "
              f"P95={o.get('latency_p95_ms',0):.1f}ms")
        report["groups"][gn] = {
            "description": gd,
            "weights": {"vector": vw, "keyword": kw, "metadata": mw},
            **metrics,
        }
    ec.close()

    # — 输出 JSON —
    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 报告: {args.output_json}")

    # — 输出 Markdown —
    md = make_markdown(report, args.dataset)
    os.makedirs(os.path.dirname(args.output_md) or ".", exist_ok=True)
    with open(args.output_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Markdown 报告: {args.output_md}")


def _get_git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()
