"""
麒麟环境自检脚本（方案 §4.8.3）

逐项检查麒麟真实环境是否就绪，打印 PASS/FAIL 汇总：
    1. 平台信息（是否 Linux）
    2. embedding .so 存在且 ctypes 可加载
    3. vector engine capi .so 存在且可加载
    4. create_embedding_client(provider="kylin") 能 embed 出 768 维向量
    5. create_vector_engine(provider="milvus", app_id=...) 能连接到 Milvus

退出码：全部 PASS → 0；有任一项 FAIL → 1。
在非麒麟环境上运行时应优雅报告各项 FAIL，不崩溃。

用法:
    python scripts/verify_kylin_environment.py
    python scripts/verify_kylin_environment.py \
        --embedding_so_path /usr/lib/libkylin-coreai-embedding.so \
        --engine_so_path /usr/lib/libkysdk-vector-engine-client-capi.so \
        --host 127.0.0.1 --port 19530
"""

from __future__ import annotations

import argparse
import ctypes
import os
import platform
import sys

# 强制 UTF-8 输出（Windows 控制台）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_EMBEDDING_SO = "/usr/lib/libkylin-coreai-embedding.so"
DEFAULT_ENGINE_SO = "/usr/lib/libkysdk-vector-engine-client-capi.so"
EXPECTED_DIM = 768

results: list[tuple[str, bool, str]] = []


def check(name: str):
    """检查项装饰器：捕获异常记为 FAIL，返回 (是否通过, 详情)。"""
    def decorator(fn):
        def wrapper(*a, **kw):
            try:
                ok, detail = fn(*a, **kw)
            except Exception as exc:
                ok, detail = False, f"异常: {exc}"
            results.append((name, ok, detail))
            print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
            return ok
        return wrapper
    return decorator


@check("平台信息")
def check_platform():
    system = platform.system()
    ok = system == "Linux"
    detail = f"{system} {platform.release()}"
    if not ok:
        detail += "（麒麟 SDK 仅支持 Linux，当前平台预期 FAIL）"
    return ok, detail


def _check_so_loadable(path: str):
    if not os.path.exists(path):
        return False, f"文件不存在: {path}"
    try:
        ctypes.CDLL(path)
    except OSError as exc:
        return False, f"ctypes 加载失败: {exc}"
    return True, f"存在且可加载: {path}"


@check("embedding .so 可加载")
def check_embedding_so(so_path: str):
    return _check_so_loadable(so_path)


@check("vector engine capi .so 可加载")
def check_engine_so(so_path: str):
    return _check_so_loadable(so_path)


@check("kylin embedding 可 embed 768 维向量")
def check_embedding_client(so_path: str):
    from memoryhub.embedding import create_embedding_client

    client = create_embedding_client(provider="kylin", so_path=so_path)
    vector = client.embed("麒麟环境自检测试")
    if len(vector) != EXPECTED_DIM:
        return False, f"维度不符: 期望 {EXPECTED_DIM}, 实际 {len(vector)}"
    return True, f"embed 成功，dim={len(vector)}"


@check("Milvus 可连接")
def check_vector_engine(so_path: str, app_id: str, host: str, port: int):
    from memoryhub.storage.vector_engine import create_vector_engine

    collection = "verify_env_check"
    engine = create_vector_engine(
        provider="milvus",
        so_path=so_path,
        app_id=app_id,
        host=host,
        port=port,
        collection=collection,
        dimension=EXPECTED_DIM,
    )
    try:
        pass  # 构造时已完成 connect + create/load collection
    finally:
        # 尽力清理自检创建的 collection，避免污染环境
        try:
            engine._api.drop_collection(engine._handle, collection)
        except Exception:
            pass
        engine.close()
    return True, f"connect + create/load collection 成功: {host}:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description="麒麟环境自检（embedding / vector engine / Milvus）")
    parser.add_argument("--embedding_so_path", default=DEFAULT_EMBEDDING_SO,
                        help="kylin embedding 动态库路径")
    parser.add_argument("--engine_so_path", default=DEFAULT_ENGINE_SO,
                        help="vector engine capi 动态库路径")
    parser.add_argument("--app_id", default=os.environ.get("MEMORYHUB_VECTOR_ENGINE_APP_ID", ""),
                        help="非空 SDK app_id（默认读取 MEMORYHUB_VECTOR_ENGINE_APP_ID）")
    parser.add_argument("--host", default="127.0.0.1", help="Milvus 服务地址")
    parser.add_argument("--port", type=int, default=19530, help="Milvus 服务端口")
    args = parser.parse_args()

    print("=== 麒麟环境自检 ===\n")
    check_platform()
    check_embedding_so(args.embedding_so_path)
    check_engine_so(args.engine_so_path)
    check_embedding_client(args.embedding_so_path)
    check_vector_engine(args.engine_so_path, args.app_id, args.host, args.port)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n=== 汇总: {passed} PASS / {failed} FAIL ===")
    if failed:
        print("存在未通过项，请按 docs/retrieval/2026-08-02_kylin_environment_handoff_checklist.md 排查。")
        sys.exit(1)
    print("环境就绪。")
    sys.exit(0)


if __name__ == "__main__":
    main()
