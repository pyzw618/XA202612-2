"""
Milvus 麒麟真实环境性能基准驱动脚本（方案 §4.9.2，供测试人员使用）

与 run_milvus_mock_benchmark.py 同结构，但走真实链路：
provider="milvus"（麒麟 vector engine capi .so → Milvus 服务）
+ provider="kylin"（麒麟 embedding .so）。

启动前先做环境检查（.so 存在、引擎可连接），失败打印中文排错提示并非零退出。

用法（麒麟环境）:
    python evaluation/run_milvus_kylin_benchmark.py --memory_count 10000
    python evaluation/run_milvus_kylin_benchmark.py \
        --so_path /usr/lib/libkysdk-vector-engine-client-capi.so \
        --embedding_so_path /usr/lib/libkylin-coreai-embedding.so \
        --host 127.0.0.1 --port 19530
"""

from __future__ import annotations

import argparse
import os
import sys

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.embedding import create_embedding_client
from memoryhub.storage.vector_engine import create_vector_engine

from evaluation.run_milvus_mock_benchmark import run_benchmark

DEFAULT_ENGINE_SO = "/usr/lib/libkysdk-vector-engine-client-capi.so"
DEFAULT_EMBEDDING_SO = "/usr/lib/libkylin-coreai-embedding.so"

TROUBLESHOOT_HINT = """
排错提示：
    1. 确认两个 .so 路径正确（--so_path / --embedding_so_path，
       或检查 /usr/lib 下的默认安装路径）；
    2. 确认 Milvus 服务已启动并可连接（--host/--port，默认 127.0.0.1:19530，
       可用 standalone Docker 部署）；
    3. 确认 Embedding 后端服务正常（DBus 服务）；
    4. 详细环境准备步骤见 docs/retrieval/2026-08-02_kylin_environment_handoff_checklist.md；
    5. 可先运行 scripts/verify_kylin_environment.py 逐项定位问题。
"""


def check_environment(args: argparse.Namespace) -> None:
    """启动前环境检查：.so 存在、embedding 可用、引擎可连接。失败退出码 1。"""
    errors = []

    for label, path in [("vector engine capi .so", args.so_path),
                        ("embedding .so", args.embedding_so_path)]:
        if not os.path.exists(path):
            errors.append(f"[FAIL] {label} 不存在: {path}")
        else:
            print(f"[PASS] {label} 存在: {path}")

    if not errors:
        try:
            client = create_embedding_client(provider="kylin", so_path=args.embedding_so_path)
            print(f"[PASS] kylin embedding 可用，dim={client.get_dimension()}")
        except Exception as exc:
            errors.append(f"[FAIL] kylin embedding 初始化失败: {exc}")

        try:
            engine = create_vector_engine(
                provider="milvus",
                so_path=args.so_path,
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
    parser = argparse.ArgumentParser(description="Milvus 麒麟真实环境性能基准")
    parser.add_argument("--memory_count", type=int, default=1000, help="合成记忆条数")
    parser.add_argument("--query_count", type=int, default=50, help="测试查询条数")
    parser.add_argument("--iterations", type=int, default=100, help="检索循环轮数")
    parser.add_argument("--top_k", type=int, default=5, help="检索返回数量")
    parser.add_argument("--dimension", type=int, default=768, help="稠密向量维度")
    parser.add_argument("--seed", type=int, default=42, help="合成数据随机种子")
    parser.add_argument("--so_path", default=DEFAULT_ENGINE_SO,
                        help="vector engine capi 动态库路径")
    parser.add_argument("--embedding_so_path", default=DEFAULT_EMBEDDING_SO,
                        help="kylin embedding 动态库路径")
    parser.add_argument("--host", default="127.0.0.1", help="Milvus 服务地址")
    parser.add_argument("--port", type=int, default=19530, help="Milvus 服务端口")
    args = parser.parse_args()

    check_environment(args)

    run_benchmark(
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
            "host": args.host,
            "port": args.port,
        },
        embedding_kwargs={"so_path": args.embedding_so_path},
    )


if __name__ == "__main__":
    main()
