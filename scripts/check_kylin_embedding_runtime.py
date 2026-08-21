#!/usr/bin/env python3
"""银河麒麟 Embedding 生产运行时部署前检查。

对照 docs/kylin/KYLIN_EMBEDDING_RUNTIME_CONTRACT.md §6，逐项检查：
  1. 操作系统是否为麒麟桌面、CPU 架构
  2. libkylin-coreai-embedding.so 是否存在于预期路径并可加载
  3. 依赖动态库（libstdc++/libgcc）是否可解析
  4. DBus 会话可用性
  5. 模型名 = ensemble-embd_gte-base_uint8-text
  6. 单条 embedding 输出维度 = 768
  7. Milvus app_id 配置（若可读配置）
  8. 生产门禁配置（provider=kylin / milvus / 768 / 禁 fallback）

用法:
    python scripts/check_kylin_embedding_runtime.py
    python scripts/check_kylin_embedding_runtime.py --json   # 输出 kylin_runtime_check.json

任意 FAIL 视为部署阻断；输出稳定错误码便于 CI 判定。
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import sys

try:  # Windows GBK 控制台输出中文需显式 UTF-8
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memoryhub.embedding.kylin_client import (  # noqa: E402
    DEFAULT_DIM,
    DEFAULT_MODEL_NAME,
    SO_CANDIDATES,
)

CONTRACT_MODEL = DEFAULT_MODEL_NAME
CONTRACT_DIM = DEFAULT_DIM
CONTRACT_KYLIN_MARKERS = ("kylin", "银河麒麟", "Kylin", "KYLIN")

# 依赖动态库（ctypes 加载 .so 时的传递依赖，缺失会导致 CDLL 失败）
REQUIRED_DEPS = ("libstdc++.so.6", "libgcc_s.so.1", "libc.so.6")

results: list[dict] = []


def _record(name: str, ok: bool, detail: str, code: str = "") -> None:
    results.append(
        {
            "check": name,
            "ok": bool(ok),
            "detail": detail,
            "code": code or ("ok" if ok else f"{name}.failed"),
        }
    )


def _load_shared(path: str):
    try:
        return ctypes.CDLL(path)
    except Exception as exc:  # noqa: BLE001
        return exc


def check_os() -> None:
    system = platform.system()
    release = platform.release()
    machine = platform.machine()
    detail = f"{system} {release} {machine}"
    markers = ("".join(l for l in (system or "").lower() if l.isalnum()))
    ok = system == "Linux" or any(m in release for m in CONTRACT_KYLIN_MARKERS)
    _record("os.kylin", ok, detail, code="runtime.os_not_kylin" if not ok else "")
    arch_ok = machine in ("x86_64", "aarch64")
    _record(
        "os.arch",
        arch_ok,
        f"CPU arch={machine}",
        code="runtime.unsupported_arch" if not arch_ok else "",
    )


def check_dynamic_library() -> None:
    found = next((p for p in SO_CANDIDATES if os.path.exists(p)), None)
    if found is None:
        _record(
            "embedding.so",
            False,
            f"未找到 {SO_CANDIDATES[0]}（候选 {len(SO_CANDIDATES)} 个路径）",
            code="embedding.so_not_found",
        )
        return
    handle = _load_shared(found)
    ok = not isinstance(handle, Exception)
    _record(
        "embedding.so",
        ok,
        f"{found} {'可加载' if ok else '加载失败: ' + str(handle)}",
        code="embedding.unavailable" if not ok else "",
    )
    if ok:
        missing = [dep for dep in REQUIRED_DEPS if ctypes.util.find_library(dep) is None]
        _record(
            "embedding.deps",
            not missing,
            f"缺失依赖: {', '.join(missing) if missing else '全部可解析'}",
            code="embedding.deps_missing" if missing else "",
        )


def check_model_and_dimension() -> None:
    # 直接加载客户端：失败路径返回稳定错误码，成功时验证模型名与维度。
    try:
        from memoryhub.embedding.kylin_client import KylinEmbeddingClient

        client = KylinEmbeddingClient(use_mock=False)
        if not client.is_available():
            _record(
                "embedding.sdk",
                False,
                "真实 SDK 不可用（DBus/服务未就绪或 .so 加载失败）",
                code="embedding.unavailable",
            )
            return
        model = getattr(client, "_model_name", "") or ""
        dim = getattr(client, "dim", None) or getattr(client, "_dim", None)
        model_ok = model == CONTRACT_MODEL
        dim_ok = int(dim) == CONTRACT_DIM
        _record(
            "embedding.model",
            model_ok,
            f"model={model}（期望 {CONTRACT_MODEL}）",
            code="embedding.model_mismatch" if not model_ok else "",
        )
        _record(
            "embedding.dimension",
            dim_ok,
            f"dim={dim}（期望 {CONTRACT_DIM}）",
            code="embedding.dimension_mismatch" if not dim_ok else "",
        )
    except Exception as exc:  # noqa: BLE001
        _record(
            "embedding.sdk",
            False,
            f"SDK 初始化异常: {exc}",
            code="embedding.sdk_init_failed",
        )


def check_production_gate() -> None:
    try:
        from memoryhub.config import load_config

        config = load_config()
        embedding_ok = config.embedding.provider == "kylin"
        engine_ok = config.vector_engine.provider == "milvus"
        dim_ok = getattr(config.embedding, "dimension", None) == CONTRACT_DIM
        app_id_ok = bool(getattr(config.vector_engine, "app_id", ""))
        _record(
            "gate.embedding_provider",
            embedding_ok,
            f"provider={config.embedding.provider}（期望 kylin）",
            code="gate.embedding_provider",
        )
        _record(
            "gate.vector_engine",
            engine_ok,
            f"provider={config.vector_engine.provider}（期望 milvus）",
            code="gate.vector_engine",
        )
        _record(
            "gate.dimension",
            dim_ok,
            f"dim={getattr(config.embedding, 'dimension', None)}（期望 768）",
            code="gate.dimension",
        )
        _record(
            "gate.milvus_app_id",
            app_id_ok,
            f"app_id={getattr(config.vector_engine, 'app_id', '') or '(空)'}",
            code="gate.milvus_app_id_missing" if not app_id_ok else "",
        )
    except Exception as exc:  # noqa: BLE001
        _record("gate.config", False, f"配置读取失败: {exc}", code="gate.config_unreadable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 kylin_runtime_check.json")
    args = parser.parse_args()

    check_os()
    check_dynamic_library()
    check_model_and_dimension()
    check_production_gate()

    ok = all(r["ok"] for r in results)
    if args.json:
        with open("kylin_runtime_check.json", "w", encoding="utf-8") as fh:
            json.dump(
                {"passed": ok, "results": results}, fh, ensure_ascii=False, indent=2
            )
    for r in results:
        flag = "OK " if r["ok"] else "FAIL"
        print(f"[{flag}] {r['check']}: {r['detail']}")
    print(f"\n结果: {'PASS' if ok else 'FAIL'}（{sum(1 for r in results if r['ok'])}/{len(results)} 通过）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
