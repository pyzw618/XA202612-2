"""
完整生产检索链路基准测试核心

通过 MilvusHybridRetriever 跑通真实/ mock 生产链路：
  - 构造临时 SQLite 事实源
  - 使用 MemorySyncService 将记忆同步到 Milvus
  - 使用 MilvusHybridRetriever 执行检索
  - 采集完整检索链路延迟、缓存命中率、错误率、待同步积压
  - 计算 Recall@5 / NDCG@10

本模块不依赖 FastAPI / TestClient，便于在真实麒麟环境直接运行。
"""

from __future__ import annotations

import logging
import math
import os
import random
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable

from evaluation.metrics.latency_benchmark import LatencyBenchmark, LatencyResult
from memoryhub.adapter.schemas import (
    PreferenceMemory,
    SceneScope,
    SearchRequest,
)
from memoryhub.config import RetrievalConfig, RuntimeConfig
from memoryhub.embedding import create_embedding_client
from memoryhub.retrieval.cache import SearchCache
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.sync_service import MemorySyncService
from memoryhub.storage.vector_engine import create_vector_engine

logger = logging.getLogger(__name__)

# 合成记忆主题池（按主题分组，便于构造 ground truth）
_MEMORY_THEMES = [
    "项目周报应使用 Markdown 格式，包含本周进展、下周计划和风险",
    "代码评审前需要先跑单元测试，覆盖率要求大于百分之八十",
    "数据库服务器地址是 10.0.2.30，端口 3306，使用 root 账号",
    "公司 Wi-Fi SSID 是 Kylin-Office，连接需要域账号认证",
    "团队站会每周一上午九点半在三楼会议室 A 举行",
    "Git 分支规范使用 feature、bugfix、hotfix 三种前缀",
    "Jenkins 构建失败时先查看控制台日志再定位问题",
    "Redis 支持 String、Hash、List、Set、Sorted Set 五种类型",
    "Kubernetes Pod 是 K8s 最小调度单元，包含一个或多个容器",
    "Transformer 模型核心是自注意力机制，计算 Q K V 矩阵",
]

_QUERY_TEMPLATES = [
    "周报格式",
    "代码评审",
    "数据库服务器",
    "公司 Wi-Fi",
    "团队站会",
    "Git 分支",
    "Jenkins 构建",
    "Redis 类型",
    "K8s Pod",
    "Transformer 注意力",
]


@dataclass
class FullChainBenchmarkResult:
    """完整检索链路基准结果（便于后续阶段直接解析上报）。"""

    total_queries: int = 0
    latency: LatencyResult = field(default_factory=LatencyResult)
    recall_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    result_cache_hit_rate: float = 0.0
    vector_cache_hit_rate: float = 0.0
    embedding_error_rate: float = 0.0
    milvus_error_rate: float = 0.0
    pending_backlog_count: int = 0
    total_indexed: int = 0
    budget_p95_ms: float = 350.0
    budget_p99_ms: float = 500.0
    p95_within_budget: bool = False
    p99_within_budget: bool = False

    def to_dict(self) -> dict:
        """导出为可序列化的结构化字典。"""
        base = asdict(self)
        base["latency"] = self.latency.to_dict()
        return base

    def __str__(self) -> str:
        lines = [
            "=" * 60,
            "完整检索链路基准结果",
            "=" * 60,
            f"测试查询数:           {self.total_queries}",
            f"已同步记忆数:         {self.total_indexed}",
            f"待同步积压数:         {self.pending_backlog_count}",
            "",
            "延迟表现（完整链路）",
            str(self.latency),
            f"Recall@5:             {self.recall_at_5:.4f}",
            f"NDCG@10:              {self.ndcg_at_10:.4f}",
            f"结果缓存命中率:       {self.result_cache_hit_rate:.2%}",
            f"查询向量缓存命中率:   {self.vector_cache_hit_rate:.2%}",
            f"Embedding 错误率:     {self.embedding_error_rate:.2%}",
            f"Milvus 错误率:        {self.milvus_error_rate:.2%}",
            f"P95 预算达标:         {self.p95_within_budget} (≤ {self.budget_p95_ms:.0f}ms)",
            f"P99 预算达标:         {self.p99_within_budget} (≤ {self.budget_p99_ms:.0f}ms)",
            "=" * 60,
        ]
        return "\n".join(lines)


def _generate_synthetic_memories(
    count: int,
    seed: int,
) -> tuple[list[PreferenceMemory], dict[str, list[str]]]:
    """生成合成偏好记忆，并按主题分组返回 ground truth。

    返回:
        (memories, theme_to_memory_ids): 记忆列表与主题到记忆 ID 的映射
    """
    rng = random.Random(seed)
    memories: list[PreferenceMemory] = []
    theme_to_ids: dict[str, list[str]] = {theme: [] for theme in _MEMORY_THEMES}

    for i in range(count):
        theme = _MEMORY_THEMES[i % len(_MEMORY_THEMES)]
        # 在主题基础上加入随机编号，保证记忆 ID 与内容可区分
        text = f"{theme}，编号 mem-{i:06d}"
        memory = PreferenceMemory(
            user_id="benchmark",
            text=text,
            scope=SceneScope(scene="benchmark", task_type="benchmark.retrieval"),
            confidence=0.8 + rng.random() * 0.15,
        )
        memories.append(memory)
        theme_to_ids[theme].append(memory.memory_id)

    return memories, theme_to_ids


def _generate_queries(
    query_count: int,
    theme_to_ids: dict[str, list[str]],
    seed: int,
) -> list[tuple[str, list[str]]]:
    """生成查询及其 ground truth 相关记忆 ID 列表。

    每个查询对应一个主题，相关 ID 为该主题下的所有记忆 ID。
    """
    themes = list(theme_to_ids.keys())
    queries: list[tuple[str, list[str]]] = []

    for i in range(query_count):
        theme = themes[i % len(themes)]
        # 使用主题对应的问题模板作为查询，保证语义相关性
        template = _QUERY_TEMPLATES[i % len(_QUERY_TEMPLATES)]
        query = f"{template} 编号查询 q-{i:04d}"
        queries.append((query, list(theme_to_ids[theme])))

    return queries


def _ndcg_at_k(relevant_ids: list[str], retrieved_ids: list[str], k: int) -> float:
    """二元相关性 NDCG@K。"""
    rel_set = set(relevant_ids)
    dcg = 0.0
    for i, rid in enumerate(retrieved_ids[:k]):
        if rid in rel_set:
            dcg += 1.0 / math.log2(i + 2)
    idcg = 0.0
    for i in range(min(len(rel_set), k)):
        idcg += 1.0 / math.log2(i + 2)
    return dcg / idcg if idcg > 0 else 0.0


def _recall_at_k(relevant_ids: list[str], retrieved_ids: list[str], k: int) -> float:
    """Recall@K。"""
    if not relevant_ids:
        return 1.0
    top_k = set(retrieved_ids[:k])
    hits = sum(1 for rid in relevant_ids if rid in top_k)
    return hits / len(relevant_ids)


def run_full_chain_benchmark(
    engine_provider: str,
    embedding_provider: str,
    memory_count: int = 10000,
    query_count: int = 200,
    iterations: int = 5,
    top_k: int = 5,
    dimension: int = 768,
    seed: int = 42,
    engine_kwargs: dict | None = None,
    embedding_kwargs: dict | None = None,
    runtime_mode: str = "production",
    allow_fallback: bool = False,
    target_p95_ms: int = 350,
    target_p99_ms: int = 500,
    progress_callback: Callable[[str], None] | None = print,
) -> FullChainBenchmarkResult:
    """运行完整生产检索链路基准。

    参数:
        engine_provider: 向量引擎 provider，如 "milvus" / "milvus_mock"
        embedding_provider: embedding provider，如 "kylin" / "kylin_mock" / "mock"
        memory_count: 合成记忆条数
        query_count: 测试查询条数
        iterations: 检索循环轮数（用于统计缓存命中率）
        top_k: 检索返回数量
        dimension: 稠密向量维度
        seed: 随机种子
        engine_kwargs: 透传给 create_vector_engine 的额外参数
        embedding_kwargs: 透传给 create_embedding_client 的额外参数
        runtime_mode: 运行模式（默认 production，确保不静默降级）
        allow_fallback: 是否允许降级
        target_p95_ms / target_p99_ms: 延迟预算
        progress_callback: 进度输出回调

    返回:
        FullChainBenchmarkResult
    """
    engine_kwargs = engine_kwargs or {}
    embedding_kwargs = embedding_kwargs or {}

    # 1. 构造临时 SQLite 事实源
    db_dir = tempfile.mkdtemp(prefix="memoryhub_bench_")
    db_path = os.path.join(db_dir, "memoryhub.db")
    db = Database(db_path=db_path)
    db.init_schema()

    collection = f"bench_{uuid.uuid4().hex[:8]}"

    try:
        # 2. 构造 embedding / 向量引擎
        embed_client = create_embedding_client(
            provider=embedding_provider,
            dim=dimension,
            **embedding_kwargs,
        )
        vector_engine = create_vector_engine(
            provider=engine_provider,
            collection=collection,
            dimension=dimension,
            **engine_kwargs,
        )

        pref_repo = PreferenceRepository(db)
        know_repo = KnowledgeRepository(db)
        cache = SearchCache(max_size=max(1000, query_count * 2), ttl_seconds=3600)

        # 3. 生成合成记忆并写入（通过同步服务写入 SQLite + Milvus）
        memories, theme_to_ids = _generate_synthetic_memories(memory_count, seed)
        queries_with_truth = _generate_queries(query_count, theme_to_ids, seed + 1)

        sync_service = MemorySyncService(
            pref_repo=pref_repo,
            know_repo=know_repo,
            embedding_client=embed_client,
            vector_engine=vector_engine,
            cache=cache,
            retriever=None,
            index_version=1,
        )

        if progress_callback:
            progress_callback(f"开始写入 {memory_count} 条合成记忆到 SQLite + Milvus...")

        insert_start = time.perf_counter()
        for memory in memories:
            sync_service.index_memory(memory)
        insert_ms = (time.perf_counter() - insert_start) * 1000

        if progress_callback:
            progress_callback(f"写入完成，耗时 {insert_ms:.2f} ms")

        # 4. 构建生产检索器
        memory_lookup = {m.memory_id: m for m in memories}
        runtime_config = RuntimeConfig(mode=runtime_mode, allow_fallback=allow_fallback)
        retrieval_config = RetrievalConfig(
            default_top_k=top_k,
            candidate_multiplier=4,
            max_query_chars=512,
            target_p95_ms=target_p95_ms,
            target_p99_ms=target_p99_ms,
            rerank_enabled=False,
            cache_ttl_seconds=3600,
        )

        # 指标收集器：累计 embedding/milvus 错误与缓存命中
        collected_metrics: list[dict] = []

        def metrics_collector(metrics: dict) -> None:
            collected_metrics.append(dict(metrics))

        retriever = MilvusHybridRetriever(
            engine=vector_engine,
            embedding_fn=embed_client.embed,
            config=retrieval_config,
            runtime_config=runtime_config,
            memory_lookup=memory_lookup,
            cache=cache,
            index_version=str(sync_service.index_version),
            query_vector_cache_size=max(1000, query_count * 2),
            metrics_collector=metrics_collector,
        )

        # 5. 执行检索基准（逐条捕获异常，统计错误率）
        queries = [q for q, _ in queries_with_truth]
        embedding_errors = 0
        milvus_errors = 0
        other_errors = 0
        success_latencies_ms: list[float] = []
        total_attempts = query_count * iterations

        def search_one(query: str) -> None:
            nonlocal embedding_errors, milvus_errors, other_errors
            start = time.perf_counter()
            try:
                retriever.search(SearchRequest(user_id="benchmark", query=query, top_k=top_k))
                success_latencies_ms.append((time.perf_counter() - start) * 1000)
            except Exception as exc:
                code = getattr(exc, "code", "")
                if isinstance(code, str):
                    if code.startswith("embedding."):
                        embedding_errors += 1
                    elif code.startswith("milvus."):
                        milvus_errors += 1
                    else:
                        other_errors += 1
                else:
                    other_errors += 1
                logger.warning("benchmark_search_error: query=%s error=%s", query, exc)

        if progress_callback:
            progress_callback(
                f"开始检索基准：{query_count} 条查询 × {iterations} 轮，top_k={top_k}..."
            )

        # warm-up
        for _ in range(1):
            for q in queries:
                search_one(q)

        success_latencies_ms.clear()
        total_start = time.perf_counter()
        for _ in range(iterations):
            for q in queries:
                search_one(q)
        total_seconds = time.perf_counter() - total_start

        if not success_latencies_ms:
            latency_result = LatencyResult(operation="search", count=0)
        else:
            latency_result = LatencyBenchmark._build_result(
                "search", success_latencies_ms, total_seconds
            )

        # 6. 计算 Recall@5 / NDCG@10（取最后一轮结果，避免缓存命中干扰）
        recalls: list[float] = []
        ndcgs: list[float] = []
        for query, relevant_ids in queries_with_truth:
            try:
                response = retriever.search(
                    SearchRequest(user_id="benchmark", query=query, top_k=10)
                )
                retrieved_ids = [r.memory_id for r in response.results]
            except Exception:
                retrieved_ids = []
            recalls.append(_recall_at_k(relevant_ids, retrieved_ids, 5))
            ndcgs.append(_ndcg_at_k(relevant_ids, retrieved_ids, 10))

        # 7. 从 metrics_collector 汇总缓存命中率
        successful_calls = len(collected_metrics)
        result_cache_hits = sum(1 for m in collected_metrics if m.get("cache_hit") == 1.0)
        vector_cache_hits = sum(
            1 for m in collected_metrics if m.get("vector_cache_hit") == 1.0
        )

        # 8. 查询待同步积压数
        pending_backlog = len(pref_repo.list_pending()) + len(know_repo.list_pending())

        result = FullChainBenchmarkResult(
            total_queries=total_attempts,
            latency=latency_result,
            recall_at_5=sum(recalls) / len(recalls) if recalls else 0.0,
            ndcg_at_10=sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
            result_cache_hit_rate=(
                (result_cache_hits / successful_calls) if successful_calls else 0.0
            ),
            vector_cache_hit_rate=(
                (vector_cache_hits / successful_calls) if successful_calls else 0.0
            ),
            embedding_error_rate=(
                (embedding_errors / total_attempts) if total_attempts else 0.0
            ),
            milvus_error_rate=(
                (milvus_errors / total_attempts) if total_attempts else 0.0
            ),
            pending_backlog_count=pending_backlog,
            total_indexed=memory_count - pending_backlog,
            budget_p95_ms=float(target_p95_ms),
            budget_p99_ms=float(target_p99_ms),
            p95_within_budget=latency_result.p95_ms <= target_p95_ms,
            p99_within_budget=latency_result.p99_ms <= target_p99_ms,
        )

        if progress_callback:
            progress_callback(str(result))

        return result

    finally:
        try:
            vector_engine.close()
        except Exception:
            pass
        try:
            embed_client.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
