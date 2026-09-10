#!/usr/bin/env python3
"""MemoryHub 延迟测试 — cold / vector_hot / result_hot 三阶段对比。

用法:
    python evaluation/runners/run_latency_eval.py \\
        --memory-dataset evaluation/datasets/memoryhub_knowledge_retrieval_v1_test.json \\
        --latency-dataset evaluation/datasets/memoryhub_retrieval_latency_v1.json \\
        --provider mock \\
        --output-json evaluation/results/latency_report.json \\
        --output-md evaluation/results/latency_report.md
"""

from __future__ import annotations

import argparse, json, math, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from memoryhub.adapter.schemas import SearchRequest
from memoryhub.config import RetrievalConfig
from memoryhub.embedding import MockEmbeddingClient
from memoryhub.retrieval.hybrid import HybridRetriever
from memoryhub.retrieval.keyword_search import KeywordSearcher
from memoryhub.retrieval.vector_search import VectorSearcher
from memoryhub.retrieval.cache import SearchCache


def percentile(data: list[float], p: float) -> float:
    if not data: return 0.0
    s = sorted(data)
    idx = (p / 100.0) * (len(s) - 1)
    if idx.is_integer(): return s[int(idx)]
    lo, hi = int(idx), int(idx) + 1
    return s[lo] * (1 - (idx - lo)) + s[hi] * (idx - lo)


def build_retriever(memories: list[dict], embed_fn, dim: int):
    kw = KeywordSearcher()
    kw.build_index([
        (m["id"], m.get("content", ""),
         json.dumps({"memory_type": "knowledge",
                     "user_id": m.get("user_id", ""),
                     "name": m.get("name", ""),
                     "scope": m.get("scope", {})}))
        for m in memories
    ])
    vs = VectorSearcher(dimension=dim)
    for m in memories:
        vs.add(m["id"], embed_fn(m.get("content", "")),
               metadata={"memory_type": "knowledge",
                         "user_id": m.get("user_id", ""),
                         "scope": m.get("scope", {})})
    return HybridRetriever(
        vector_search=vs, keyword_search=kw,
        config=RetrievalConfig(), embedding_fn=embed_fn,
    )


def main():
    p = argparse.ArgumentParser(description="MemoryHub 检索延迟测试")
    p.add_argument("--memory-dataset", required=True, help="记忆数据集路径 (用于索引)")
    p.add_argument("--latency-dataset", required=True, help="延迟查询集路径")
    p.add_argument("--provider", default="mock", choices=["mock"])
    p.add_argument("--embedding-model", default="mock-embedding")
    p.add_argument("--embedding-endpoint", default="")
    p.add_argument("--output-json", default="evaluation/results/latency_report.json")
    p.add_argument("--output-md", default="evaluation/results/latency_report.md")
    args = p.parse_args()

    # 加载记忆
    with open(args.memory_dataset) as f:
        mem_ds = json.load(f)
    memories = mem_ds["memories"]
    print(f"记忆索引: {len(memories)} 条")

    # 加载延迟查询
    with open(args.latency_dataset) as f:
        lat_ds = json.load(f)
    warmup_qs = lat_ds.get("warmup_queries", [])
    formal_qs = lat_ds.get("formal_queries", [])
    print(f"预热查询: {len(warmup_qs)}  正式查询: {len(formal_qs)}")

    # 构造 embedding client
    ec = MockEmbeddingClient(dim=768, latency=0.0)
    provider_label = "mock"
    dim = ec.get_dimension()
    print(f"Embedding: {provider_label}, dim={dim}")
    print("构建索引中...")
    t0 = time.perf_counter()
    retriever = build_retriever(memories, ec.embed, dim)
    index_time = (time.perf_counter() - t0) * 1000
    print(f"索引构建完成: {index_time:.0f}ms")

    def run_phase(queries, phase_name, cache=None):
        retriever.cache = cache
        latencies = []
        print(f"[{phase_name}] 运行 {len(queries)} 条查询...")
        start = time.perf_counter()
        for i, q in enumerate(queries):
            t0 = time.perf_counter()
            retriever.search(SearchRequest(
                user_id=q.get("user_id", "default"),
                query=q.get("query_text", ""),
                top_k=5,
            ))
            elapsed = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed)
            if (i + 1) % 1000 == 0: print(f"  [{phase_name}] {i+1}/{len(queries)}")
        total = (time.perf_counter() - start)
        lat = sorted(latencies)
        result = {
            "phase": phase_name,
            "count": len(latencies),
            "p50_ms": round(percentile(lat, 50), 2),
            "p95_ms": round(percentile(lat, 95), 2),
            "p99_ms": round(percentile(lat, 99), 2),
            "max_ms": round(max(lat), 2),
            "mean_ms": round(sum(lat) / len(lat), 2),
            "total_s": round(total, 2),
        }
        retriever.cache = None
        print(f"  [{phase_name}] P50={result['p50_ms']}ms P95={result['p95_ms']}ms "
              f"P99={result['p99_ms']}ms max={result['max_ms']}ms")
        return result, latencies

    # 预热
    if warmup_qs:
        print("\n预热中...")
        run_phase(warmup_qs, "warmup")

    # Phase 1: cold (无缓存)
    print("\n=== Phase 1: cold ===")
    cold_result, _ = run_phase(formal_qs, "cold")

    # Phase 2: vector_hot (embedding cache 命中)
    print("\n=== Phase 2: vector_hot (embedding cache warm) ===")
    vector_hot_result, _ = run_phase(formal_qs, "vector_hot")

    # Phase 3: result_hot (结果缓存命中)
    print("\n=== Phase 3: result_hot (result cache warm) ===")
    sc = SearchCache(max_size=len(formal_qs) + 1000)
    result_hot_result, _ = run_phase(formal_qs, "result_hot", cache=sc)

    ec.close()

    # 报告
    report = {
        "environment": {
            "embedding_provider": provider_label, "embedding_dim": dim,
            "index_build_ms": round(index_time, 2),
            "warmup_count": len(warmup_qs),
            "formal_count": len(formal_qs),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "phases": {
            "cold": cold_result,
            "vector_hot": vector_hot_result,
            "result_hot": result_hot_result,
        },
    }

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Markdown
    md = f"""# MemoryHub 检索延迟测试报告

## 环境
- Embedding: {provider_label}
- 记忆索引数: {len(memories)}
- 预热查询: {len(warmup_qs)}
- 正式查询: {len(formal_qs)}

## 三阶段延迟

| 阶段 | 数量 | P50 (ms) | P95 (ms) | P99 (ms) | Max (ms) | 均值 (ms) |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| cold | {cold_result['count']} | {cold_result['p50_ms']} | {cold_result['p95_ms']} | {cold_result['p99_ms']} | {cold_result['max_ms']} | {cold_result['mean_ms']} |
| vector_hot | {vector_hot_result['count']} | {vector_hot_result['p50_ms']} | {vector_hot_result['p95_ms']} | {vector_hot_result['p99_ms']} | {vector_hot_result['max_ms']} | {vector_hot_result['mean_ms']} |
| result_hot | {result_hot_result['count']} | {result_hot_result['p50_ms']} | {result_hot_result['p95_ms']} | {result_hot_result['p99_ms']} | {result_hot_result['max_ms']} | {result_hot_result['mean_ms']} |

## 达标检查 (cold P95≤350ms, cold P99≤500ms)

- cold P95: **{cold_result['p95_ms']}ms** → {'✅ 达标' if cold_result['p95_ms']<=350 else '❌ 未达标'}
- cold P99: **{cold_result['p99_ms']}ms** → {'✅ 达标' if cold_result['p99_ms']<=500 else '❌ 未达标'}

## 缓存收益

- P50 加速: cold {cold_result['p50_ms']}ms → vector_hot {vector_hot_result['p50_ms']}ms ({(1-vector_hot_result['p50_ms']/max(cold_result['p50_ms'],0.01))*100:.0f}%)
- P95 加速: cold {cold_result['p95_ms']}ms → vector_hot {vector_hot_result['p95_ms']}ms
- P95 加速: cold {cold_result['p95_ms']}ms → result_hot {result_hot_result['p95_ms']}ms

> 冷查询阶段包含 embedding API 调用延迟；vector_hot 阶段 embedding 缓存命中；result_hot 阶段结果缓存命中。
"""
    with open(args.output_md, "w") as f:
        f.write(md)
    print(f"\n报告: {args.output_json}, {args.output_md}")


if __name__ == "__main__":
    main()
