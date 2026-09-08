"""One HTTP client for every Agent-facing MemoryHub integration.

The client deliberately contains no business logic.  It only maps the
stable REST contract to Python methods and turns transport/API failures into a
small, safe error object that both CLI and MCP can expose consistently.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx

from .config import current_user_id


class MemoryHubError(RuntimeError):
    """A stable error returned by the REST transport or MemoryHub API."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        *,
        outcome_status: str | None = None,
        safety_action: str | None = None,
        audit_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.outcome_status = outcome_status
        self.safety_action = safety_action
        self.audit_id = audit_id

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.status_code is not None:
            result["status_code"] = self.status_code
        for key, value in (
            ("status", self.outcome_status),
            ("safety_action", self.safety_action),
            ("audit_id", self.audit_id),
        ):
            if value:
                result[key] = value
        return result


class MemoryHubClient:
    """Call the MemoryHub REST API using a reusable ``httpx.Client``."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8099",
        timeout: float = 30.0,
        user_id: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.user_id = (user_id or current_user_id()).strip() or current_user_id()
        self._owns_client = client is None
        self.client = client or httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "MemoryHubClient":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Low-level request handling
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        path = path if path.startswith("/") else f"/{path}"
        return self._request_url(f"/api/memory{path}", method, path, json_body=json_body, query=query, headers=headers)

    def _root_request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """Call an API route mounted below ``/api`` rather than ``/api/memory``.

        A small number of compatibility routes (for example the fact proposal
        decision endpoint) live on the agent adapter router.  Keeping this
        explicit avoids fragile ``..`` path tricks in callers.
        """
        path = path if path.startswith("/") else f"/{path}"
        return self._request_url(f"/api{path}", method, path, json_body=json_body, query=query, headers=headers)

    def _request_url(
        self,
        url_path: str,
        method: str,
        error_path: str,
        *,
        json_body: Any = None,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        try:
            request_headers = dict(headers) if headers else {}
            response = self.client.request(method, url_path, json=json_body, params=query, headers=request_headers)
        except httpx.TimeoutException as exc:
            raise MemoryHubError("memoryhub.client.timeout", "MemoryHub request timed out") from exc
        except httpx.ConnectError as exc:
            raise MemoryHubError(
                "memoryhub.client.unreachable",
                f"cannot reach MemoryHub at {self.base_url}",
            ) from exc
        except httpx.HTTPError as exc:
            raise MemoryHubError("memoryhub.client.error", "MemoryHub HTTP request failed") from exc

        if response.status_code >= 400:
            raise self._api_error(error_path, response)
        if not response.content:
            return None
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return response.text

    @staticmethod
    def _api_error(path: str, response: httpx.Response) -> MemoryHubError:
        detail: Any = None
        try:
            body = response.json()
            detail = body.get("detail") if isinstance(body, dict) else None
        except (ValueError, json.JSONDecodeError):
            pass

        code = "memoryhub.api.error"
        message = f"MemoryHub {path} failed with HTTP {response.status_code}"
        outcome_status = safety_action = audit_id = None
        if isinstance(detail, Mapping):
            if isinstance(detail.get("code"), str):
                code = detail["code"]
            if isinstance(detail.get("message"), str):
                message = detail["message"]
            elif code != "memoryhub.api.error":
                message = f"MemoryHub rejected {path}: {code}"
            outcome_status = detail.get("status") if isinstance(detail.get("status"), str) else None
            safety_action = detail.get("safety_action") if isinstance(detail.get("safety_action"), str) else None
            audit_id = detail.get("audit_id") if isinstance(detail.get("audit_id"), str) else None
        elif isinstance(detail, str) and detail:
            message = detail
        return MemoryHubError(
            code,
            message,
            response.status_code,
            outcome_status=outcome_status,
            safety_action=safety_action,
            audit_id=audit_id,
        )

    # ------------------------------------------------------------------
    # Core read/write contract
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            payload = self._request("GET", "/health") or {}
            return {
                "reachable": True,
                "api_url": self.base_url,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "service": payload,
            }
        except MemoryHubError as exc:
            return {
                "reachable": False,
                "api_url": self.base_url,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "error": exc.message,
                "error_code": exc.code,
            }

    def system_status(self) -> dict[str, Any]:
        return self._request("GET", "/system/status") or {}

    @staticmethod
    def build_search_payload(
        *,
        user_id: str,
        query: str,
        top_k: int = 5,
        memory_types: list[str] | None = None,
        min_confidence: float = 0.0,
        scene: str = "",
        task_type: str = "",
        app: str = "",
        project_id: str = "",
        level: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "query": query,
            "context": {"scene": scene, "task_type": task_type, "app": app},
            "project_id": project_id,
            "top_k": top_k,
            "memory_types": memory_types or [],
            "min_confidence": min_confidence,
            "level": level,
            "session_id": session_id,
        }

    def search(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        body = dict(payload or kwargs)
        return self._request("POST", "/search", json_body=body) or {}

    def get_context(self, payload: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        body = dict(payload or kwargs)
        return self._request("POST", "/context", json_body=body) or {}

    def vnext_search(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Call the unified vNext /search endpoint.

        This is the preferred read path for S3 convergence; it returns the
        full MemoryRetrievalResponse with trace_id and selected memories.
        """
        user_id = user_id or self.user_id
        body = dict(payload)
        body.setdefault("api_version", "vnext/v1")
        return self._request(
            "POST",
            "/vnext/search",
            json_body=body,
            headers={"X-MemoryHub-Tenant": tenant_id, "X-MemoryHub-User": user_id},
        ) or {}

    def vnext_context(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Call the unified vNext /context endpoint."""
        user_id = user_id or self.user_id
        body = dict(payload)
        body.setdefault("api_version", "vnext/v1")
        return self._request(
            "POST",
            "/vnext/context",
            json_body=body,
            headers={"X-MemoryHub-Tenant": tenant_id, "X-MemoryHub-User": user_id},
        ) or {}

    def vnext_feedback(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit attributed vNext feedback with the caller's identity."""
        user_id = user_id or self.user_id
        body = dict(payload)
        body.setdefault("tenant_id", tenant_id)
        body.setdefault("user_id", user_id)
        return self._request(
            "POST",
            "/vnext/feedback",
            json_body=body,
            headers={"X-MemoryHub-Tenant": tenant_id, "X-MemoryHub-User": user_id},
        ) or {}

    def write_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/events", json_body={"events": events}) or {}

    def write_canonical_events(
        self,
        events: list[dict[str, Any]],
        *,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Send events through the vNext canonical write endpoint.

        This is the single production write path; it routes through the
        CanonicalWriteService and returns durable event/working/episode IDs.
        """
        user_id = user_id or self.user_id
        body: dict[str, Any] = {
            "api_version": "vnext/v1",
            "request_id": request_id or f"req_{self._nonce()}",
            "idempotency_key": idempotency_key or f"idem_{self._nonce()}",
            "events": events,
        }
        return self._request(
            "POST",
            "/vnext/events",
            json_body=body,
            headers={"X-MemoryHub-Tenant": tenant_id, "X-MemoryHub-User": user_id},
        ) or {}

    @staticmethod
    def _nonce() -> str:
        import secrets
        import time

        return f"{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    def resume_task(
        self,
        task_id: str,
        *,
        resume_token: str = "",
        expected_snapshot_version: int | None = None,
        tenant_id: str = "default",
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Resume a task by task_id using the vNext resume endpoint."""
        user_id = user_id or self.user_id
        headers: dict[str, str] = {
            "X-MemoryHub-Tenant": tenant_id,
            "X-MemoryHub-User": user_id,
        }
        if resume_token:
            headers["X-MemoryHub-Resume-Token"] = resume_token
        if expected_snapshot_version is not None:
            headers["X-MemoryHub-Expected-Version"] = str(expected_snapshot_version)
        return self._request(
            "GET",
            f"/tasks/{task_id}/resume",
            query={"request_id": request_id or f"req_{self._nonce()}"},
            headers=headers,
        ) or {}

    def write_preference(self, memory: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/memories/preference", json_body=memory) or {}

    def write_knowledge(self, memory: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/memories/knowledge", json_body=memory) or {}

    def remember(
        self,
        text: str,
        *,
        memory_type: str = "preference",
        user_id: str | None = None,
        scene: str = "",
        task_type: str = "",
        project_id: str = "",
        confidence: float = 0.5,
        name: str = "",
        steps: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        user_id = user_id or self.user_id
        if memory_type == "preference":
            return self.write_preference(
                {
                    "user_id": user_id,
                    "preference_type": "output_style",
                    "text": text,
                    "payload": {"project_id": project_id} if project_id else {},
                    "scope": {"scene": scene, "task_type": task_type, "app": "memoryhub-cli"},
                    "confidence": confidence,
                    "extract_source": "explicit_feedback",
                }
            )
        if memory_type == "knowledge":
            # 裸 knowledge 无子类型信息：按 fact 处理（客观知识默认沉淀为事实）
            memory_type = "fact"
        elif memory_type.startswith("knowledge:"):
            memory_type = memory_type.split(":", 1)[1]
        if memory_type not in {"workflow", "case", "template", "fact"}:
            raise MemoryHubError(
                "memoryhub.client.invalid_type",
                f"unsupported memory type: {memory_type!r}; "
                "use one of: preference, workflow, case, template, fact, "
                "knowledge (treated as fact), knowledge:<subtype>",
            )
        return self.write_knowledge(
            {
                "user_id": user_id,
                "knowledge_type": memory_type,
                "name": name or text[:120],
                "content": text,
                "steps": steps or [],
                "tools": tools or [],
                "scope": {"scene": scene, "task_type": task_type, "app": "memoryhub-cli"},
                "confidence": confidence,
                "subject": text if memory_type == "fact" else "",
            }
        )

    def update_memory(self, memory_type: str, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/{memory_type}/{memory_id}", json_body=payload) or {}

    def feedback(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/feedback", json_body=payload) or {}

    def forget(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/forget", json_body=payload) or {}

    def forget_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/forget/preview", json_body=payload) or {}

    # ------------------------------------------------------------------
    # Listing, provenance and compatibility endpoints
    # ------------------------------------------------------------------

    def list_preferences(self, user_id: str | None = None, scene: str = "", status: str = "active") -> list[Any]:
        return self._request("GET", "/preferences", query={"user_id": user_id or self.user_id, "scene": scene, "status": status}) or []

    def list_knowledge(self, user_id: str | None = None, scene: str = "", knowledge_type: str = "", status: str = "active") -> list[Any]:
        return self._request("GET", "/knowledge", query={"user_id": user_id or self.user_id, "scene": scene, "knowledge_type": knowledge_type, "status": status}) or []

    def list_facts(self, user_id: str | None = None, status: str = "active", limit: int = 100) -> list[Any]:
        return self._request("GET", "/facts", query={"user_id": user_id or self.user_id, "status": status, "limit": limit}) or []

    def list_memories(self, *, user_id: str | None = None, memory_type: str = "all", scene: str = "", status: str = "active") -> dict[str, list[Any]]:
        user_id = user_id or self.user_id
        result: dict[str, list[Any]] = {}
        if memory_type in {"all", "preference"}:
            result["preferences"] = self.list_preferences(user_id, scene, status)
        if memory_type in {"all", "knowledge"}:
            result["knowledge"] = self.list_knowledge(user_id, scene, status=status)
        if memory_type in {"all", "fact"}:
            result["facts"] = self.list_facts(user_id, status)
        return result

    def get_preference(self, memory_id: str, user_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/preferences/{memory_id}", query={"user_id": user_id or self.user_id}) or {}

    def get_knowledge(self, memory_id: str, user_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/knowledge/{memory_id}", query={"user_id": user_id or self.user_id}) or {}

    def get_fact(self, memory_id: str, user_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", f"/facts/{memory_id}", query={"user_id": user_id or self.user_id}) or {}

    def get_memory(self, memory_id: str, *, memory_type: str = "", user_id: str | None = None) -> dict[str, Any]:
        kind = memory_type or ("preference" if memory_id.startswith("pref_") else "knowledge")
        if kind == "fact" or memory_id.startswith("fact"):
            return self.get_fact(memory_id, user_id)
        if kind == "preference":
            return self.get_preference(memory_id, user_id)
        return self.get_knowledge(memory_id, user_id)

    def provenance(self, memory_id: str, kind: str = "lineage", user_id: str | None = None) -> dict[str, Any]:
        if kind not in {"lineage", "evidence", "audit"}:
            raise MemoryHubError("memoryhub.client.invalid_provenance", f"unsupported provenance kind: {kind}")
        return self._request("GET", f"/v2/memories/{memory_id}/{kind}", query={"user_id": user_id or self.user_id}) or {}

    def list_projections(self, *, status: str = "pending", user_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return self._request("GET", "/v2/projections", query={"user_id": user_id or self.user_id, "status": status, "limit": limit}) or {}

    def replay_projections(self, *, outbox_ids: list[str] | None = None, user_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v2/projections/replay", json_body={"user_id": user_id or self.user_id, "outbox_ids": outbox_ids}) or {}

    def list_conflicts(self, user_id: str | None = None, status: str = "pending") -> list[Any]:
        return self._request("GET", "/conflicts", query={"user_id": user_id or self.user_id, "status": status}) or []

    def resolve_conflict(self, conflict_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/conflicts/{conflict_id}/resolve", json_body=payload) or {}

    def propose_knowledge_fact(self, triples: list[dict[str, Any]], *, source_id: str = "", scope_hint: str = "global", project_id: str | None = None) -> Any:
        return self._request("POST", "/facts/propose", json_body={"source_id": source_id, "scope_hint": scope_hint, "project_id": project_id, "triples": triples})

    def list_fact_proposals(self, user_id: str | None = None, limit: int = 100) -> list[Any]:
        return self._request("GET", "/facts/proposals", query={"user_id": user_id or self.user_id, "limit": limit}) or []

    def decide_fact(self, memory_id: str, *, action: str, user_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("POST", "/facts/decide", json_body={"memory_id": memory_id, "action": action, "user_id": user_id or self.user_id, **(payload or {})}) or {}

    def decide_knowledge_fact(self, proposal_id: str, *, commit: bool, user_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        action = "fact_commit" if commit else "fact_reject"
        return self._root_request("POST", f"/agent/actions/{proposal_id}/decision", json_body={"action_type": action, "decision": "commit" if commit else "reject", "payload": {"user_id": user_id or self.user_id, **(payload or {})}}) or {}

    def session_events(self, session_id: str) -> list[Any]:
        return self._request("GET", f"/events/session/{session_id}") or []

    def export_memories(self, *, user_id: str | None = None, status: str = "active") -> dict[str, Any]:
        return {"schema_version": "memoryhub-export/1.0", "user_id": user_id or self.user_id, "memories": self.list_memories(user_id=user_id, status=status)}

    def import_memories(self, payload: Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            memories = payload.get("memories", payload)
            return {"dry_run": True, "counts": {key: len(value) for key, value in memories.items() if isinstance(value, list)}}
        memories = payload.get("memories", payload)
        results: list[Any] = []
        for memory in memories.get("preferences", []):
            results.append(self.write_preference(dict(memory)))
        for memory in memories.get("knowledge", []):
            results.append(self.write_knowledge(dict(memory)))
        return {"dry_run": False, "imported": len(results), "results": results}
