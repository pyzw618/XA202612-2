"""真机 MemoryHub 服务的 HTTP 客户端。

设计要点：

1. **``served`` 断言**：``POST /api/memory/search`` 的响应带 ``served`` 字段，
   指明请求由哪条链路服务（``vnext`` 或 ``legacy``）。四项指标必须来自 vNext
   ``RetrievalService``——内置的 ``POST /evaluate/{retrieval,latency}`` 走的是
   legacy ``app.state.retriever``，不能用于正式数字。因此本客户端默认在每次
   检索后校验 ``served``，不符即抛错中止。

2. **请求留痕**：每次请求都记入 :attr:`LiveClient.records`，报告可直接引用，
   用于证明"数字确实来自真机服务"。

3. **重试**：仅对连接类错误与 5xx 重试；4xx 视为确定性错误立即返回，避免把
   参数错误重试成超时。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8099"
DEFAULT_TIMEOUT_S = 30.0
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

# 检索请求允许被服务的链路；legacy 结果不作为验收证据。
EXPECTED_SERVED = "vnext"


class LiveClientError(RuntimeError):
    """真机客户端的基础错误。"""


class ServiceUnavailable(LiveClientError):
    """服务不可达或持续 5xx，对应 runner 退出码 3。"""


class ServedMismatch(LiveClientError):
    """检索响应未经 vNext 链路服务。"""


@dataclass
class RequestRecord:
    """单次 HTTP 请求的留痕。"""

    method: str
    path: str
    status: int
    elapsed_ms: float
    served: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "served": self.served,
            "error": self.error,
        }


@dataclass
class LiveClient:
    """已部署 MemoryHub 服务的同步 HTTP 客户端。

    用法::

        client = LiveClient("http://127.0.0.1:8099")
        status = client.get_system_status()
        resp = client.search(user_id="u1", query="周报格式", top_k=5)
    """

    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_retries: int = 2
    assert_served: bool = True
    records: list[RequestRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout_s)

    # ------------------------------------------------------------------ 基础

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LiveClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_retry: bool = True,
    ) -> tuple[int, Any]:
        """发送一次请求，返回 ``(status_code, parsed_body)``。

        连接错误与 5xx 会重试 ``max_retries`` 次；重试耗尽后连接类错误抛
        :class:`ServiceUnavailable`，5xx 则原样返回状态码供调用方判断。
        """
        attempts = self.max_retries + 1 if allow_retry else 1
        last_error: str = ""
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                resp = self._client.request(method, path, json=json_body, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.records.append(
                    RequestRecord(method, path, -1, (time.perf_counter() - started) * 1000,
                                  error=last_error)
                )
                if attempt + 1 >= attempts:
                    raise ServiceUnavailable(
                        f"{method} {path} 连接失败（重试 {attempt} 次）：{last_error}"
                    ) from exc
                time.sleep(0.5 * (attempt + 1))
                continue

            elapsed_ms = (time.perf_counter() - started) * 1000
            body: Any
            try:
                body = resp.json()
            except ValueError:
                body = resp.text

            self.records.append(
                RequestRecord(method, path, resp.status_code, elapsed_ms)
            )

            if resp.status_code in RETRYABLE_STATUS and attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
                continue
            return resp.status_code, body

        # 理论上不可达：循环内要么 return 要么 raise。
        raise ServiceUnavailable(f"{method} {path} 重试耗尽：{last_error}")

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        status, body = self.request(method, path, **kwargs)
        if status >= 400:
            raise LiveClientError(f"{method} {path} -> HTTP {status}: {str(body)[:300]}")
        return body

    # ------------------------------------------------------------- 系统信息

    def get_system_status(self) -> dict[str, Any]:
        """``GET /api/memory/system/status`` — 环境指纹的唯一来源。"""
        return self._json("GET", "/api/memory/system/status")

    def get_system_config(self) -> dict[str, Any]:
        """``GET /api/memory/system/config`` — 非密钥配置。"""
        return self._json("GET", "/api/memory/system/config")

    def health(self) -> bool:
        try:
            status, _ = self.request("GET", "/api/health", allow_retry=False)
        except ServiceUnavailable:
            return False
        return status == 200

    # --------------------------------------------------------------- 检索

    def search(
        self,
        *,
        user_id: str,
        query: str,
        top_k: int = 5,
        context: dict[str, Any] | None = None,
        project_id: str = "",
        memory_types: Iterable[str] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """``POST /api/memory/search``，并校验 ``served``。

        返回完整响应体；``results[].memory_id`` 即召回的有序 id 列表。
        """
        payload: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "top_k": top_k,
            "memory_types": list(memory_types) if memory_types is not None else [],
        }
        if context:
            payload["context"] = context
        if project_id:
            payload["project_id"] = project_id
        if session_id:
            payload["session_id"] = session_id

        body = self._json("POST", "/api/memory/search", json_body=payload)
        served = str(body.get("served", ""))
        if self.assert_served and served != EXPECTED_SERVED:
            raise ServedMismatch(
                f"检索未经 vNext 链路服务（served={served!r}，期望 {EXPECTED_SERVED!r}）："
                "该结果不得作为验收证据"
            )
        if self.records:
            self.records[-1].served = served
        return body

    def search_capture_latency(
        self, **kwargs: Any
    ) -> tuple[dict[str, Any], float]:
        """与 :meth:`search` 相同，额外返回客户端 wall-clock 毫秒数。

        客户端端到端耗时包含网络与 JSON 序列化，是用户在桌面端实际感受到的
        延迟，因此 ≤500ms 的结论以此为准；服务端 ``latency_ms`` 作为支撑数字
        并列记录。
        """
        started = time.perf_counter()
        body = self.search(**kwargs)
        return body, (time.perf_counter() - started) * 1000

    # ------------------------------------------------------------- 写入/播种

    def write_knowledge(self, memory: dict[str, Any]) -> dict[str, Any]:
        """``POST /api/memory/memories/knowledge`` — 播种知识记忆。

        请求体字段必须与数据集中的记忆一致（尤其 ``scope`` 与 ``project_id``），
        否则会被检索的 scope 门挡掉。
        """
        return self._json("POST", "/api/memory/memories/knowledge", json_body=memory)

    def write_preference(self, memory: dict[str, Any]) -> dict[str, Any]:
        """``POST /api/memory/memories/preference`` — 播种偏好记忆。

        注意：该路径**不会**产生冲突记录；冲突评测必须走
        :meth:`agent_step` 的事件链。
        """
        return self._json("POST", "/api/memory/memories/preference", json_body=memory)

    def agent_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        """``POST /api/agent/step`` — 写入事件、跑抽取、返回候选记忆。"""
        return self._json("POST", "/api/agent/step", json_body=payload)

    # ------------------------------------------------------------ 偏好读取

    def get_preference(self, memory_id: str, *, user_id: str) -> dict[str, Any]:
        return self._json(
            "GET", f"/api/memory/preferences/{memory_id}", params={"user_id": user_id}
        )

    def list_preferences(
        self, *, user_id: str, status: str = "active"
    ) -> list[dict[str, Any]]:
        body = self._json(
            "GET", "/api/memory/preferences", params={"user_id": user_id, "status": status}
        )
        return body if isinstance(body, list) else body.get("items", [])

    # ------------------------------------------------------------ 冲突读取

    def list_conflicts(
        self,
        *,
        user_id: str,
        status: str | None = None,
        memory_type: str | None = None,
        size: int = 200,
    ) -> list[dict[str, Any]]:
        """列出冲突记录。

        **不传 ``status`` 时必须同时取 ``resolved`` 与 ``pending``**：该端点的
        ``status`` 默认值是 ``pending``，只查默认值会漏掉所有已决策的冲突
        （表现为"冲突表里明明有记录，接口却返回空"）。
        """
        statuses = [status] if status else ["resolved", "pending"]
        collected: dict[str, dict[str, Any]] = {}
        for value in statuses:
            params: dict[str, Any] = {"user_id": user_id, "size": size, "status": value}
            if memory_type:
                params["memory_type"] = memory_type
            body = self._json("GET", "/api/memory/conflicts", params=params)
            items = body if isinstance(body, list) else body.get("items", [])
            for item in items:
                collected[str(item.get("conflict_id", ""))] = item
        return list(collected.values())

    # ------------------------------------------------------------ 清理/隔离

    def delete_demo_data(self, *, user_id: str) -> dict[str, Any]:
        """``DELETE /api/agent/demo-data`` — 清空该用户的全部数据与索引。"""
        return self._json("DELETE", "/api/agent/demo-data", params={"user_id": user_id})

    def delete_preferences(self, *, user_id: str) -> dict[str, Any]:
        return self._json("DELETE", "/api/agent/preferences", params={"user_id": user_id})

    def reconcile(self) -> dict[str, Any]:
        """``POST /api/memory/admin/reconcile`` — 修复投影漂移。"""
        return self._json("POST", "/api/memory/admin/reconcile")

    # ---------------------------------------------------------------- 报告

    def request_summary(self) -> dict[str, Any]:
        """请求留痕汇总，供报告引用。"""
        by_status: dict[str, int] = {}
        for record in self.records:
            key = str(record.status)
            by_status[key] = by_status.get(key, 0) + 1
        served_values = sorted({r.served for r in self.records if r.served})
        return {
            "total_requests": len(self.records),
            "by_status": by_status,
            "served_observed": served_values,
        }
