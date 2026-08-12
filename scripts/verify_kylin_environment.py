#!/usr/bin/env python3
"""麒麟环境 / Mock SDK 环境自检脚本

检查项:
  1. 平台信息 (OS / CPU / Memory)
  2. Embedding mock SDK 存在并可加载
  3. Vector Engine mock SDK 存在并可加载
  4. KylinEmbeddingClient(use_mock=True) embed 768 维可用
  5. Python 和关键依赖版本

输出 retrieval_environment_manifest.json

用法:
    python scripts/verify_kylin_environment.py
    python scripts/verify_kylin_environment.py --mock  # mock SDK 模式
"""

from __future__ import annotations

import argparse, ctypes, json, os, platform, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MOCK_BUILD_DIR = os.path.join("third_party", "kylin-mock", "build")
EMBEDDING_LIB = os.path.join(MOCK_BUILD_DIR, "libkylin-coreai-embedding-mock.so")
VECTOR_LIB = os.path.join(MOCK_BUILD_DIR, "libkysdk-vector-engine-client-capi-mock.so")
EXPECTED_DIM = 768

results: list[dict] = []


def add(name, ok, detail=""):
    results.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))


def check_so(name, path):
    if not os.path.exists(path):
        add(name, False, f"文件不存在: {path}")
        return
    try:
        ctypes.CDLL(path)
        add(name, True, f"存在且可加载: {path}")
    except OSError as e:
        add(name, False, f"ctypes 加载失败: {e}")


def main():
    p = argparse.ArgumentParser(description="环境自检")
    p.add_argument("--mock", action="store_true", default=True, help="mock SDK 模式 (默认)")
    p.add_argument("--output", default="evaluation/results/retrieval_environment_manifest.json")
    args = p.parse_args()

    print("=== MemoryHub 环境自检 ===\n")

    # Platform
    add("平台: Linux", platform.system() == "Linux", f"{platform.system()} {platform.release()}")
    uname = platform.uname()
    add("CPU 架构", True, f"{uname.machine} ({uname.processor or 'unknown'})")

    # Memory
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemTotal" in line:
                    kb = int(line.split()[1])
                    add("系统内存", True, f"{kb//1024} MB")
                    break
    except Exception:
        add("系统内存", False, "无法读取 /proc/meminfo")

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    add("Python 版本", True, py_ver)

    # Mock SDK
    if args.mock:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        check_so("Embedding mock SDK (.so)", os.path.join(root, EMBEDDING_LIB))
        check_so("Vector Engine mock SDK (.so)", os.path.join(root, VECTOR_LIB))

        try:
            from memoryhub.embedding import KylinEmbeddingClient
            client = KylinEmbeddingClient(use_mock=True)
            vec = client.embed("环境自检测试文本")
            dim = len(vec)
            ok = dim == EXPECTED_DIM
            add(f"KylinEmbeddingClient(use_mock=True) embed {EXPECTED_DIM}维",
                ok, f"dim={dim}")
            client.close()
        except Exception as e:
            add("KylinEmbeddingClient(use_mock=True) embed", False, str(e)[:120])

    # Dependencies
    for mod in ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "faiss", "numpy", "jieba"]:
        try:
            __import__(mod)
            add(f"依赖: {mod}", True)
        except ImportError:
            add(f"依赖: {mod}", False)

    # Summary
    passed = sum(1 for r in results if r["pass"])
    failed = len(results) - passed
    print(f"\n=== 汇总: {passed} PASS / {failed} FAIL ===")

    # Manifest
    manifest = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": {
            "os": f"{platform.system()} {platform.release()}",
            "cpu": f"{uname.machine} ({uname.processor or 'unknown'})",
            "python": py_ver,
        },
        "sdk_mode": "mock" if args.mock else "kylin",
        "embedding_dim": EXPECTED_DIM,
        "checks": results,
        "overall_pass": failed == 0,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"环境清单: {args.output}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
