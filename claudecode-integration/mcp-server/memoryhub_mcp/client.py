"""Thin HTTP client for the MemoryHub REST API.

Endpoint contract follows ``memoryhub/adapter/api.py`` (the authoritative
source; ``docs/INTERFACE.md`` is stale). Every method returns parsed JSON.
Errors are translated into stable :class:`MemoryHubError` with a code, the
HTTP status, and a short message — never raw exception internals.
"""

from __future__ import annotations

import json
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - keep import graph explicit
    httpx = None


class MemoryHubError(RuntimeError):
    """A failed or unexpected MemoryHub REST call."""

    def __init__(self, code: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class MemoryHubClient:
    """Talk to a running MemoryHub FastAPI instance over HTTP."""

    def __init__(self, base_url: str, timeout: float = 30.0, user_id: str = "default") -> None:
        if httpx is None:
            raise MemoryHubError(
                "memoryhub.client.dependency_missing",
                "httpx is required; install it via mcp-server/requirements.txt",
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_id = user_id

    # ---- low level ----

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/memory{path}"

    def _request(self, method: str, path: str, *, json_body: Any = None, query: dict | None = None) -> Any:
        try:
            response = httpx.request(
                method,
                self._url(path),
                params=query,
                json=json_body,
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise MemoryHubError(
                "memoryhub.client.unreachable",
                f"cannot reach MemoryHub at {self.base_url} — start it with "
                f"scripts/start_memoryhub_server.py",
                None,
            ) from exc
        except httpx.TimeoutException as exc:
            raise MemoryHubError("memoryhub.client.timeout", "MemoryHub request timed out", None) from exc
        except httpx.HTTPError as exc:
            raise MemoryHubError("memoryhub.client.error", f"HTTP error: {exc}", None) from exc

        if response.status_code >= 400:
            detail = response.json().get("detail") if response.content else None
            code = "memoryhub.api.error"
            message = f"MemoryHub {path} failed with HTTP {response.status_code}"
            if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                code = detail["code"]
                message = f"MemoryHub rejected {path}: {detail['code']}"
            raise MemoryHubError(code, message, response.status_code)

        if not response.content:
            return None
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text

    # ---- read path ----

    def search(self, payload: dict) -> dict:
        return self._request("POST", "/search", json_body=payload)

    def get_context(self, payload: dict) -> dict:
        return self._request("POST", "/context", json_body=payload)

    def list_preferences(self, user_id: str, scene: str = "", status: str = "active") -> list:
        return self._request("GET", "/preferences", query={"user_id": user_id, "scene": scene, "status": status})

    def list_knowledge(self, user_id: str, scene: str = "", knowledge_type: str = "") -> list:
        return self._request("GET", "/knowledge", query={"user_id": user_id, "scene": scene, "knowledge_type": knowledge_type})

    def list_facts(self, user_id: str, status: str = "active", limit: int = 100) -> list:
        return self._request("GET", "/facts", query={"user_id": user_id, "status": status, "limit": limit})

    def get_preference(self, memory_id: str, user_id: str) -> dict:
        return self._request("GET", f"/preferences/{memory_id}", query={"user_id": user_id})

    def get_knowledge(self, memory_id: str, user_id: str) -> dict:
        return self._request("GET", f"/knowledge/{memory_id}", query={"user_id": user_id})

    def get_fact(self, fact_id: str, user_id: str) -> dict:
        return self._request("GET", f"/facts/{fact_id}", query={"user_id": user_id})

    def list_conflicts(self, user_id: str, status: str = "pending") -> list:
        return self._request("GET", "/conflicts", query={"user_id": user_id, "status": status})

    # ---- write path ----

    def write_events(self, events: list[dict]) -> dict:
        return self._request("POST", "/events", json_body={"events": events})

    def write_preference(self, memory: dict) -> dict:
        return self._request("POST", "/memories/preference", json_body=memory)

    def write_knowledge(self, memory: dict) -> dict:
        return self._request("POST", "/memories/knowledge", json_body=memory)

    def forget(self, payload: dict) -> dict:
        return self._request("POST", "/forget", json_body=payload)

    def feedback(self, payload: dict) -> dict:
        return self._request("POST", "/feedback", json_body=payload)

    def resolve_conflict(self, conflict_id: str, payload: dict) -> dict:
        return self._request("POST", f"/conflicts/{conflict_id}/resolve", json_body=payload)

    def health(self) -> dict:
        """Cheap connectivity check against a read-only endpoint."""
        import time

        started = time.perf_counter()
        try:
            self._request("GET", "/preferences", query={"user_id": self.user_id, "status": "active"})
            reachable = True
            error = ""
        except MemoryHubError as exc:
            reachable = False
            error = exc.message
        return {
            "reachable": reachable,
            "api_url": self.base_url,
            "error": error,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
