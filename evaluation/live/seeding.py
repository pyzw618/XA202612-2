"""把评测语料播种到真机服务，并保证与真实用户数据完全隔离。

**为什么不用 ``DELETE /api/agent/demo-data`` 做"清场"**

该端点虽然按 ``user_id`` 删 SQLite 行，但末尾的清理是**全局**的：

- ``memory_lookup.clear()`` 与 ``keyword_search`` 重建会影响所有用户，包括
  真实用户的检索，直到索引重建完成；
- 它清的是 ``app.state.vector_store``（FAISS 路径），**不是**生产用的
  ``vector_engine``（Milvus），所以被删记忆的向量仍留在 Milvus 且仍可被
  ``_metadata_store`` 过滤命中，反而制造"幽灵结果"。

因此本模块**不做任何破坏性调用**，改为：

1. 每次运行生成唯一 ``run_tag``；
2. ``user_id`` 加前缀 —— 引擎的标量过滤只认 ``user_id``/``status``，唯一
   用户名天然杜绝跨运行与真实数据串扰；
3. ``memory_id`` 与 ``project_id`` 一并加前缀，避免与真实记忆主键冲突。

代价是评测数据会留在服务里；它们对真实用户不可见（user_id 过滤），可由
运维另行清理。破坏性清场只在显式传 ``--teardown`` 时执行。
"""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from evaluation.live.client import LiveClient, LiveClientError

SEPARATOR = "__"


@dataclass(frozen=True)
class EvalUser:
    """一次评测运行的隔离身份。"""

    user_id: str
    run_tag: str

    @staticmethod
    def new(prefix: str = "evalrun") -> "EvalUser":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_tag = f"{prefix}_{stamp}_{uuid.uuid4().hex[:4]}"
        return EvalUser(user_id=run_tag, run_tag=run_tag)

    def namespace(self, value: str) -> str:
        if not value:
            return value
        return f"{self.run_tag}{SEPARATOR}{value}"

    def memory_id(self, original: str) -> str:
        return self.namespace(original)

    def map_memory(self, memory: dict[str, Any]) -> dict[str, Any]:
        """把数据集记忆改写为本次运行的隔离副本。"""
        mapped = dict(memory)
        mapped["memory_id"] = self.memory_id(str(memory.get("id") or memory.get("memory_id")))
        mapped.pop("id", None)
        mapped["user_id"] = self.user_id
        mapped["project_id"] = self.namespace(str(memory.get("project_id", ""))) if memory.get("project_id") else ""
        return mapped

    def map_query(self, query: dict[str, Any]) -> dict[str, Any]:
        """按与 :meth:`map_memory` 相同的规则改写查询，保持 scope 一致。"""
        mapped = dict(query)
        mapped["user_id"] = self.user_id
        if query.get("project_id"):
            mapped["project_id"] = self.namespace(str(query["project_id"]))
        mapped["relevance"] = {
            self.memory_id(memory_id): grade
            for memory_id, grade in (query.get("relevance") or {}).items()
        }
        mapped["scope_blocked"] = [
            self.memory_id(memory_id) for memory_id in (query.get("scope_blocked") or [])
        ]
        return mapped


@dataclass
class SeedResult:
    """播种结果。"""

    requested: int = 0
    succeeded: int = 0
    skipped_resumed: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    elapsed_s: float = 0.0
    items_per_second: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "succeeded": self.succeeded,
            "skipped_resumed": self.skipped_resumed,
            "failure_count": len(self.failures),
            "failures": self.failures[:20],
            "elapsed_s": round(self.elapsed_s, 2),
            "items_per_second": round(self.items_per_second, 3),
        }


def load_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


#: 安全门在扫描出错时会回退到 review（``safety.policy.on_scan_error: review``），
#: 因此 ``review_required`` 可能是瞬时抖动而非内容问题。已实测同一份内容重投
#: 即通过，故对这类错误重试。
RETRYABLE_SEED_ERRORS = ("review_required", "timeout", "temporarily")
SEED_RETRY_ATTEMPTS = 3
SEED_RETRY_BACKOFF_S = 1.5


def seed_corpus(
    client: LiveClient,
    memories: Iterable[dict[str, Any]],
    user: EvalUser,
    *,
    concurrency: int = 8,
    manifest_path: Path | None = None,
    checkpoint_every: int = 50,
) -> SeedResult:
    """把数据集记忆逐条写入服务，支持断点续播。

    服务端 embedding 是单 worker 串行的，提高 ``concurrency`` 只能重叠 HTTP
    与 SQLite 的等待，不会让 embedding 变快；但也不应因此降到 1。
    """
    manifest = load_manifest(manifest_path) if manifest_path else {}
    result = SeedResult()
    pending: list[dict[str, Any]] = []
    for memory in memories:
        mapped = user.map_memory(memory)
        original_id = str(memory.get("id") or memory.get("memory_id"))
        if manifest.get(original_id) == "ok":
            result.skipped_resumed += 1
            continue
        pending.append({"_original_id": original_id, "_payload": mapped})

    result.requested = len(pending) + result.skipped_resumed
    started = time.perf_counter()
    written = 0

    def _write(entry: dict[str, Any]) -> tuple[str, bool, str]:
        last_error = ""
        for attempt in range(SEED_RETRY_ATTEMPTS):
            try:
                client.write_knowledge(entry["_payload"])
                return entry["_original_id"], True, ""
            except LiveClientError as exc:
                last_error = str(exc)[:200]
                if not any(token in last_error for token in RETRYABLE_SEED_ERRORS):
                    break
                if attempt + 1 < SEED_RETRY_ATTEMPTS:
                    time.sleep(SEED_RETRY_BACKOFF_S * (attempt + 1))
        return entry["_original_id"], False, last_error

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_write, entry): entry for entry in pending}
        for future in as_completed(futures):
            original_id, ok, error = future.result()
            if ok:
                result.succeeded += 1
                manifest[original_id] = "ok"
            else:
                manifest[original_id] = "failed"
                result.failures.append({"memory_id": original_id, "error": error})
            written += 1
            if manifest_path and written % checkpoint_every == 0:
                _flush_manifest(manifest_path, manifest)

    result.elapsed_s = time.perf_counter() - started
    if result.elapsed_s > 0:
        result.items_per_second = result.succeeded / result.elapsed_s
    if manifest_path:
        _flush_manifest(manifest_path, manifest)
    return result


def _flush_manifest(path: Path, manifest: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def teardown_user(client: LiveClient, user: EvalUser) -> dict[str, Any]:
    """清理评测用户数据。

    只在显式要求时调用：``/api/agent/demo-data`` 会顺带清空全局的
    ``memory_lookup`` 与关键词索引，影响真实用户，属于破坏性操作。
    """
    outcome: dict[str, Any] = {}
    for label, call in (
        ("demo_data", lambda: client.delete_demo_data(user_id=user.user_id)),
        ("preferences", lambda: client.delete_preferences(user_id=user.user_id)),
    ):
        try:
            outcome[label] = call()
        except LiveClientError as exc:
            outcome[label] = {"error": str(exc)[:200]}
    return outcome


def estimate_seed_seconds(count: int, items_per_second: float = 3.3) -> float:
    """按经验吞吐估算播种耗时，供 ``--dry-run`` 提示。

    ``3.3`` 条/秒来自生产投影上限（outbox worker 每 30 秒最多处理 100 条）。
    """
    return count / items_per_second if items_per_second > 0 else 0.0
