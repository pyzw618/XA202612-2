"""
麒麟 / Milvus 真实环境完整检索链路基准脚本（阶段七 TASK-014）

用途:
    在真实麒麟设备上跑通生产检索全链路：
      kylin embedding .so → 768 维稠密向量
      → sparse 向量构造
      → milvus vector engine capi .so → Milvus HybridSearch(RRF)
      → SQLite 回表 → 元数据过滤 → Top-K

    输出后续性能验收所需的全部指标：
      - 完整链路 P50/P95/P99 延迟
      - Recall@5 / NDCG@10
      - 结果缓存命中率 / 查询向量缓存命中率
      - Embedding / Milvus 错误率
      - 待同步积压数（pending_index）

运行环境:
    - Kylin OS（真实麒麟环境）
    - libkylin-coreai-embedding.so 已安装且 DBus 后端服务正常
    - libkysdk-vector-engine-client-capi.so 已安装
    - Milvus standalone 服务已启动（默认 127.0.0.1:19530）

用法:
    # 默认 10K 记忆、Top-K=5 的完整链路基准（推荐）
    python evaluation/run_milvus_kylin_benchmark.py

    # 小数据量快速验证脚本路径
    python evaluation/run_milvus_kylin_benchmark.py --memory_count 100 --query_count 20

    # 显式指定 .so 路径与服务地址
    export MEMORYHUB_VECTOR_ENGINE_APP_ID="<provided-by-deployment-platform>"
    python evaluation/run_milvus_kylin_benchmark.py \
        --so_path /usr/lib/libkysdk-vector-engine-client-capi.so \
        --embedding_so_path /usr/lib/libkylin-coreai-embedding.so \
        --app_id "$MEMORYHUB_VECTOR_ENGINE_APP_ID" \
        --host 127.0.0.1 --port 19530

    # 输出 JSON 结果到文件，便于 CI/评测系统解析
    python evaluation/run_milvus_kylin_benchmark.py --output results/kylin_bench.json

退出码:
    0: 基准成功完成
    1: 环境检查未通过或运行时出错

输出文件:
    默认不写入文件；指定 --output 时，会将结构化 JSON 结果写入该路径。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 强制 UTF-8 输出（Windows 控制台/麒麟终端）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evaluation.metrics.full_chain_benchmark import run_full_chain_benchmark
from memoryhub.embedding import create_embedding_client
from memoryhub.storage.vector_engine import create_vector_engine

DEFAULT_ENGINE_SO = "/usr/lib/libkysdk-vector-engine-client-capi.so"
DEFAULT_EMBEDDING_SO = "/usr/lib/libkylin-coreai-embedding.so"

TROUBLESHOOT_HINT = """
排错提示：
    1. 确认两个 .so 路径正确（--so_path / --embedding_so_path，
       或检查 /usr/lib 下的默认安装路径）；
    2. 确认 Milvus 服务已启动并可连接（--host/--port，默认 127.0.0.1:19530，
       可用 standalone Docker 部署）；
    3. 确认 Embedding 后端服务正常（DBus 服务）；
    4. 确认当前系统为 Kylin OS，且架构与 .so 一致（arm64/x86_64）；
    5. 详细环境准备步骤见 docs/reference/kylin/kylin-environment-handoff-checklist.md；
    6. 可先运行 scripts/verify_kylin_environment.py 逐项定位问题。
"""

RESULT_INTERPRETATION = """
结果解读：
    - P95/P99 延迟：生产目标为 P95 ≤ 350ms、P99 ≤ 500ms。
      若未达标，请结合 milvus_hybrid_search_timings 日志分析各阶段耗时。
    - Recall@5 / NDCG@10：反映检索质量；本脚本使用合成数据与主题分组 ground truth，
      真实业务场景建议替换为真实评测数据集（tests/eval_dataset.json）。
    - 缓存命中率：结果缓存与查询向量缓存越高，重复查询延迟越低。
    - Embedding/Milvus 错误率：生产环境应接近 0%；非零时请检查 .so 与后端服务稳定性。
    - 待同步积压数：写入时 Milvus 失败的记忆数量；正常应为 0，非零时请关注补偿任务日志。
"""


def check_environment(args: argparse.Namespace) -> None:
    """启动前环境检查：.so 存在、embedding 可用、引擎可连接。失败退出码 1。"""
    errors = []

    for label, path in [
        ("vector engine capi .so", args.so_path),
        ("embedding .so", args.embedding_so_path),
    ]:
        if not os.path.exists(path):
            errors.append(f"[FAIL] {label} 不存在: {path}")
        else:
            print(f"[PASS] {label} 存在: {path}")

    if not errors:
        try:
            client = create_embedding_client(
                provider="kylin", so_path=args.embedding_so_path
            )
            print(f"[PASS] kylin embedding 可用，dim={client.get_dimension()}")
            client.close()
        except Exception as exc:
            errors.append(f"[FAIL] kylin embedding 初始化失败: {exc}")

        try:
            engine = create_vector_engine(
                provider="milvus",
                so_path=args.so_path,
                app_id=args.app_id,
                host=args.host,
                port=args.port,
                collection="bench_env_check",
                dimension=args.dimension,
            )
            engine.close()
            print(f"[PASS] Milvus 可连接: {args.host}:{args.port}")
        except Exception as exc:
            errors.append(f"[FAIL] Milvus 连接失败: {exc}")

    if errors:
        print("\n环境检查未通过：")
        for e in errors:
            print(f"  {e}")
        print(TROUBLESHOOT_HINT)
        sys.exit(1)
    print("环境检查通过，开始基准测试。\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="麒麟 / Milvus 真实环境完整检索链路基准",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=RESULT_INTERPRETATION,
    )
    parser.add_argument(
        "--memory_count",
        type=int,
        default=10000,
        help="合成记忆条数（默认 10000，阶段验收要求）",
    )
    parser.add_argument(
        "--query_count", type=int, default=200, help="测试查询条数（默认 200）"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="检索循环轮数（默认 5；用于统计缓存命中率）",
    )
    parser.add_argument(
        "--top_k", type=int, default=5, help="检索返回数量（默认 5）"
    )
    parser.add_argument(
        "--dimension",
        type=int,
        default=768,
        help="稠密向量维度（生产固定 768）",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="合成数据随机种子"
    )
    parser.add_argument(
        "--so_path",
        default=DEFAULT_ENGINE_SO,
        help="vector engine capi 动态库路径",
    )
    parser.add_argument(
        "--embedding_so_path",
        default=DEFAULT_EMBEDDING_SO,
        help="kylin embedding 动态库路径",
    )
    parser.add_argument(
        "--app_id", default=os.environ.get("MEMORYHUB_VECTOR_ENGINE_APP_ID", ""),
        help="非空 SDK app_id（默认读取 MEMORYHUB_VECTOR_ENGINE_APP_ID）",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Milvus 服务地址"
    )
    parser.add_argument(
        "--port", type=int, default=19530, help="Milvus 服务端口"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="将结构化 JSON 结果写入指定路径",
    )
    parser.add_argument(
        "--target_p95_ms",
        type=int,
        default=350,
        help="P95 延迟预算（默认 350ms）",
    )
    parser.add_argument(
        "--target_p99_ms",
        type=int,
        default=500,
        help="P99 延迟预算（默认 500ms）",
    )
    args = parser.parse_args()

    check_environment(args)

    try:
        result = run_full_chain_benchmark(
            engine_provider="milvus",
            embedding_provider="kylin",
            memory_count=args.memory_count,
            query_count=args.query_count,
            iterations=args.iterations,
            top_k=args.top_k,
            dimension=args.dimension,
            seed=args.seed,
            engine_kwargs={
                "so_path": args.so_path,
                "app_id": args.app_id,
                "host": args.host,
                "port": args.port,
            },
            embedding_kwargs={"so_path": args.embedding_so_path},
            runtime_mode="production",
            allow_fallback=False,
            target_p95_ms=args.target_p95_ms,
            target_p99_ms=args.target_p99_ms,
        )
    except Exception as exc:
        print(f"\n[失败] 基准运行出错: {exc}")
        print(TROUBLESHOOT_HINT)
        sys.exit(1)

    print(RESULT_INTERPRETATION)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"\n结构化结果已保存: {output_path}")


if __name__ == "__main__":
    main()
