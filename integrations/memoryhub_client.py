"""HTTP client used by Agents to call the local MemoryHub service."""

from __future__ import annotations

from typing import Any

import httpx


class MemoryHubClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    def health(self) -> dict[str, Any]:
        response = self.client.get("/api/memory/health")
        response.raise_for_status()
        return response.json()

    def get_context(
        self,
        *,
        user_id: str,
        query: str,
        scene: str,
        task_type: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/memory/context",
            json={
                "user_id": user_id,
                "query": query,
                "context": {
                    "scene": scene,
                    "task_type": task_type,
                    "app": "qwen_langgraph_agent",
                },
                "top_k": top_k,
                "memory_types": ["preference", "knowledge"],
                "min_confidence": 0.5,
            },
        )
        response.raise_for_status()
        return response.json()

    def write_events(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.client.post("/api/memory/events", json={"events": events})
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "MemoryHubClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
