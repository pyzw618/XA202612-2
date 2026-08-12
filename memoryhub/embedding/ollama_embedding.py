"""Ollama HTTP Embedding 客户端。

通过 Ollama HTTP API /api/embeddings 调用本地 embedding 模型。
支持内置 LRU 缓存，同文本复用 embedding 避免重复计算。
"""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from typing import List

import httpx

from .base import BaseEmbeddingClient


class OllamaEmbeddingClient(BaseEmbeddingClient):
    """Ollama 本地 embedding 客户端。

    使用方式:
        client = OllamaEmbeddingClient(model="nomic-embed-text")
        if client.is_available():
            vec = client.embed("测试文本")
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        endpoint: str = "http://localhost:11434",
        timeout: float = 30.0,
        cache_size: int = 4096,
    ):
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._dim: int | None = None
        self._available: bool | None = None
        self._cache = lru_cache(maxsize=cache_size)(self._embed_impl)

    def embed(self, text: str) -> List[float]:
        return list(self._cache(text))

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self.embed(t) for t in texts]

    def get_dimension(self) -> int:
        if self._dim is not None:
            return self._dim
        vec = self.embed("dimension probe")
        self._dim = len(vec)
        return self._dim

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            vec = self.embed("health check")
            if vec and len(vec) > 0:
                self._available = True
                return True
        except Exception:
            pass
        self._available = False
        return False

    def close(self) -> None:
        self._cache.cache_clear()

    def _embed_impl(self, text: str) -> tuple:
        url = f"{self.endpoint}/api/embeddings"
        payload = {"model": self.model, "prompt": text}
        try:
            resp = httpx.post(
                url, json=payload, timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            vec = body.get("embedding", [])
            if not vec:
                raise RuntimeError(f"Ollama 返回空 embedding: model={self.model}")
            return tuple(vec)
        except Exception:
            raise

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
