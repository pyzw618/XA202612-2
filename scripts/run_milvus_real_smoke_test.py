"""
Milvus 真实环境端到端冒烟测试（方案 §4.8.3）

在麒麟环境跑一次完整写入 + 检索：
    connect → 新建临时 collection（名字带时间戳） → insert 10 条中英文记忆
    → 每条用原文做 hybrid_search，断言自己能被召回（top-1）
    → drop collection → 打印结果汇总

失败以非零码退出。--mock 可切换到项目内 mock 动态库，
用于在非麒麟环境验证脚本逻辑本身。

用法:
    python scripts/run_milvus_real_smoke_test.py            # 麒麟真实环境
    python scripts/run_milvus_real_smoke_test.py --mock     # 本机 mock 链路
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.embedding import create_embedding_client
from memoryhub.storage.vector_engine import build_sparse_vector, create_vector_engine

DEFAULT_ENGINE_SO = "/usr/lib/libkysdk-vector-engine-client-capi.so"
DEFAULT_EMBEDDING_SO = "/usr/lib/libkylin-coreai-embedding.so"

# 10 条中英文混合记忆（内容各异，保证 top-1 自召回不受重复干扰）
SMOKE_MEMORIES = [
    "用户喜欢在早上喝一杯黑咖啡",
    "项目会议定于每周三下午三点召开",
    "The vector index was rebuilt last night",
    "检索模块默认使用 hybrid search 融合策略",
    "用户的家乡在杭州，喜欢西湖边的晨跑",
    "Daily backup task runs at 2 AM",
    "配置文件中的超时时间设置为 30 秒",
    "Embedding model warmup takes about 5 seconds",
    "系统日志每周末自动归档到冷存储",
    "Cache eviction policy is LRU by default",
]


def drop_collection_quietly(engine, collection: str) -> None:
    """尽力 drop collection（BaseVectorEngine 未暴露 drop，走底层 capi）。"""
    try:
        engine._api.drop_collection(engine._handle, collection)
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Milvus 端到端冒烟测试（写入 + top-1 自召回）")
    parser.add_argument("--mock", action="store_true",
                        help="使用项目内 mock 动态库（非麒麟环境验证脚本逻辑）")
    parser.add_argument("--so_path", default=DEFAULT_ENGINE_SO,
                        help="vector engine capi 动态库路径（--mock 时忽略）")
    parser.add_argument("--embedding_so_path", default=DEFAULT_EMBEDDING_SO,
                        help="kylin embedding 动态库路径（--mock 时忽略）")
    parser.add_argument("--app_id", default=os.environ.get("MEMORYHUB_VECTOR_ENGINE_APP_ID", ""),
                        help="非空 SDK app_id（默认读取 MEMORYHUB_VECTOR_ENGINE_APP_ID）")
    parser.add_argument("--host", default="127.0.0.1", help="Milvus 服务地址")
    parser.add_argument("--port", type=int, default=19530, help="Milvus 服务端口")
    parser.add_argument("--dimension", type=int, default=768, help="稠密向量维度")
    args = parser.parse_args()

    engine_provider = "milvus_mock" if args.mock else "milvus"
    embedding_provider = "kylin_mock" if args.mock else "kylin"
    collection = f"smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"=== Milvus 冒烟测试（{'mock' if args.mock else '麒麟真实'}链路）===")
    print(f"collection: {collection}, dimension: {args.dimension}\n")

    engine = None
    try:
        # 1. connect（构造时完成 connect + create/load collection）
        engine_kwargs = {"app_id": "test-app-id"} if args.mock else {
            "app_id": args.app_id,
            "so_path": args.so_path, "host": args.host, "port": args.port,
        }
        engine = create_vector_engine(
            provider=engine_provider,
            collection=collection,
            dimension=args.dimension,
            **engine_kwargs,
        )
        print(f"[PASS] connect: {engine_provider} ({'项目内 mock 库' if args.mock else f'{args.host}:{args.port}'})")

        embedding_kwargs = {} if args.mock else {"so_path": args.embedding_so_path}
        embed_client = create_embedding_client(provider=embedding_provider, **embedding_kwargs)
        print(f"[PASS] embedding: provider={embedding_provider}, dim={embed_client.get_dimension()}")

        # 2. insert 10 条中英文记忆
        for i, text in enumerate(SMOKE_MEMORIES):
            engine.insert(f"smoke_{i:02d}", text, embed_client.embed(text))
        print(f"[PASS] insert: {len(SMOKE_MEMORIES)} 条记忆写入完成")

        # 3. 每条用原文做 hybrid_search，断言 top-1 是自己
        failures = []
        for i, text in enumerate(SMOKE_MEMORIES):
            memory_id = f"smoke_{i:02d}"
            results = engine.hybrid_search(
                embed_client.embed(text), build_sparse_vector(text), top_k=1
            )
            hit = bool(results) and results[0].memory_id == memory_id
            status = "PASS" if hit else "FAIL"
            top = results[0].memory_id if results else "<空结果>"
            print(f"[{status}] recall: {memory_id} → top-1={top} | {text[:30]}")
            if not hit:
                failures.append(memory_id)

        # 4. 汇总
        passed = len(SMOKE_MEMORIES) - len(failures)
        print(f"\n=== 汇总: {passed}/{len(SMOKE_MEMORIES)} 条 top-1 自召回成功 ===")
        if failures:
            print(f"失败项: {', '.join(failures)}")
            sys.exit(1)
        print("冒烟测试通过。")
        sys.exit(0)

    except SystemExit:
        raise
    except Exception as exc:
        print(f"\n[FAIL] 冒烟测试中断: {exc}")
        if not args.mock:
            print("排错提示：确认 .so 路径、Milvus 服务、Embedding 后端；"
                  "可先运行 scripts/verify_kylin_environment.py 逐项定位。")
        sys.exit(1)
    finally:
        # 5. drop 临时 collection 并释放资源（不掩盖测试结果）
        if engine is not None:
            drop_collection_quietly(engine, collection)
            engine.close()


if __name__ == "__main__":
    main()
