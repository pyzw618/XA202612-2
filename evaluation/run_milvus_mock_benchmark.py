"""
Milvus mock 环境性能基准驱动脚本（阶段七 TASK-014 验证用）

默认运行完整生产检索链路基准（SQLite + MilvusHybridRetriever），
用于在本地/非麒麟环境验证 run_milvus_kylin_benchmark.py 的代码路径。

如需仅验证引擎层（embed → sparse → hybrid_search），可传 --engine_only。

用法:
    python evaluation/run_milvus_mock_benchmark.py
    python evaluation/run_milvus_mock_benchmark.py \
        --memory_count 500 --query_count 20 --iterations 3
    python evaluation/run_milvus_mock_benchmark.py --engine_only

注意: mock 环境的延迟数值与召回数值不具真实参考意义，仅用于验证脚本路径。
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import uuid

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluation.metrics.full_chain_benchmark import run_full_chain_benchmark
from evaluation.metrics.latency_benchmark import LatencyBenchmark
from memoryhub.embedding import create_embedding_client
from memoryhub.storage.vector_engine import build_sparse_vector, create_vector_engine

MOCK_LIMITATION_NOTICE = """
[!] 注意：mock 环境的延迟数值与 Recall@5/NDCG@10 不具真实参考意义，
    仅用于验证基准脚本路径与指标采集逻辑。
    真实性能数据请以麒麟环境 run_milvus_kylin_benchmark.py 的结果为准。
"""

# 合成数据素材（中英文混合）
_ZH_SUBJECTS = ["用户", "系统", "检索模块", "存储引擎", "会议纪要", "测试报告", "配置文件", "日志"]
_ZH_VERBS = ["记录了", "更新了", "分析了", "同步了", "备份了", "清理了"]
_ZH_OBJECTS = ["偏好设置", "历史对话", "向量索引", "缓存数据", "权限规则", "部署脚本"]
_EN_SNIPPETS = [
    "vector index rebuild",
    "memory retrieval pipeline",
    "hybrid search ranking",
    "embedding model warmup",
    "daily backup task",
    "cache eviction policy",
]


def generate_synthetic_texts(count: int, seed: int, prefix: str) -> list[str]:
    """生成确定性合成文本（中英文混合），prefix 区分记忆/query 语料。"""
    rng = random.Random(seed)
    texts = []
    for i in range(count):
        if rng.random() < 0.5:
            text = (
                f"{rng.choice(_ZH_SUBJECTS)}{rng.choice(_ZH_VERBS)}"
                f"{rng.choice(_ZH_OBJECTS)}，编号 {prefix}-{i}"
            )
        else:
            text = f"{rng.choice(_EN_SNIPPETS)} {prefix}-{i}"
        texts.append(text)
    return texts


def build_embedding_client(provider: str, dimension: int, **kwargs):
    """构造 embedding 客户端。kylin_mock 固定输出 768 维，维度不匹配时直接报错。"""
    if provider == "kylin_mock" and dimension != 768:
        raise ValueError(
            f"kylin_mock 动态库固定输出 768 维，与 --dimension {dimension} 不一致；"
            "请改用 --embedding_provider mock 或将 --dimension 设为 768"
        )
    if provider == "mock":
        # latency=0.0，避免 mock 假延迟污染延迟指标
        return create_embedding_client(provider="mock", dim=dimension, latency=0.0, **kwargs)
    return create_embedding_client(provider=provider, **kwargs)


def run_engine_benchmark(
    engine_provider: str,
    embedding_provider: str,
    memory_count: int,
    query_count: int,
    iterations: int,
    top_k: int,
    dimension: int,
    seed: int,
    engine_kwargs: dict | None = None,
    embedding_kwargs: dict | None = None,
) -> dict:
    """引擎层基准主流程（旧路径，用于快速验证引擎接口）。"""
    collection = f"bench_{uuid.uuid4().hex[:8]}"
    engine = create_vector_engine(
        provider=engine_provider,
        collection=collection,
        dimension=dimension,
        **(engine_kwargs or {}),
    )
    try:
        embed_client = build_embedding_client(
            embedding_provider, dimension, **(embedding_kwargs or {})
        )
        print(f"引擎: provider={engine_provider}, collection={collection}, dimension={dimension}")
        print(f"embedding: provider={embedding_provider}, dim={embed_client.get_dimension()}")

        memories = generate_synthetic_texts(memory_count, seed, "mem")
        queries = generate_synthetic_texts(query_count, seed + 1, "qry")

        vectors = embed_client.embed_batch(memories)

        pairs = list(zip([f"mem_{i:06d}" for i in range(memory_count)], memories, vectors))

        def _insert_one(pair):
            engine.insert(pair[0], pair[1], pair[2])

        insert_benchmark = LatencyBenchmark(insert_fn=_insert_one, warmup=0)
        insert_result = insert_benchmark.benchmark_insert(pairs, iterations=1)
        print(f"\n写入 {memory_count} 条合成记忆完成：")
        print(insert_result)

        def _search_one(query: str) -> None:
            dense = embed_client.embed(query)
            sparse = build_sparse_vector(query)
            engine.hybrid_search(dense, sparse, top_k)

        search_benchmark = LatencyBenchmark(search_fn=_search_one)
        search_result = search_benchmark.benchmark_search(queries, iterations=iterations)
        print(f"检索基准（引擎层 embed → sparse → hybrid_search，top_k={top_k}）：")
        print(search_result)

        return {"insert": insert_result, "search": search_result}
    finally:
        engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Milvus mock 环境性能基准（验证性能测试代码路径）"
    )
    parser.add_argument("--memory_count", type=int, default=1000, help="合成记忆条数")
    parser.add_argument("--query_count", type=int, default=50, help="测试查询条数")
    parser.add_argument("--iterations", type=int, default=100, help="检索循环轮数")
    parser.add_argument("--top_k", type=int, default=5, help="检索返回数量")
    parser.add_argument("--dimension", type=int, default=768, help="稠密向量维度")
    parser.add_argument(
        "--embedding_provider",
        choices=["kylin_mock", "mock"],
        default="kylin_mock",
        help="embedding provider（kylin_mock 固定 768 维）",
    )
    parser.add_argument("--seed", type=int, default=42, help="合成数据随机种子")
    parser.add_argument(
        "--engine_only",
        action="store_true",
        help="仅运行引擎层基准（旧路径），否则默认运行完整生产链路基准",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="将完整链路结构化 JSON 结果写入指定路径",
    )
    args = parser.parse_args()

    try:
        if args.engine_only:
            run_engine_benchmark(
                engine_provider="milvus_mock",
                embedding_provider=args.embedding_provider,
                memory_count=args.memory_count,
                query_count=args.query_count,
                iterations=args.iterations,
                top_k=args.top_k,
                dimension=args.dimension,
                seed=args.seed,
            )
        else:
            result = run_full_chain_benchmark(
                engine_provider="milvus_mock",
                embedding_provider=args.embedding_provider,
                memory_count=args.memory_count,
                query_count=args.query_count,
                iterations=args.iterations,
                top_k=args.top_k,
                dimension=args.dimension,
                seed=args.seed,
                runtime_mode="test",
                allow_fallback=False,
            )
            if args.output:
                import json
                from pathlib import Path

                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
                print(f"\n结构化结果已保存: {output_path}")
    except Exception as exc:
        print(f"\n[失败] mock 基准运行出错: {exc}")
        sys.exit(1)

    print(MOCK_LIMITATION_NOTICE)


if __name__ == "__main__":
    main()
