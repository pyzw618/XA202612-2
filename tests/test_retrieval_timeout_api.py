# -*- coding: utf-8 -*-
"""检索超时/不可用错误的 API 映射测试"""

from __future__ import annotations

from memoryhub.adapter.api import _retrieval_http_error
from memoryhub.embedding import KylinEmbeddingError
from memoryhub.storage.vector_engine import MilvusEngineError


class TestRetrievalHttpError:
    def test_embedding_timeout_maps_to_504(self) -> None:
        exc = KylinEmbeddingError("embedding.timeout: embed 超过 250ms")
        http_exc = _retrieval_http_error(exc)
        assert http_exc.status_code == 504
        assert http_exc.detail == {"code": "embedding.timeout: embed 超过 250ms"}

    def test_milvus_timeout_maps_to_504(self) -> None:
        exc = MilvusEngineError("milvus.timeout: hybrid_search 超过 120ms")
        http_exc = _retrieval_http_error(exc)
        assert http_exc.status_code == 504
        assert http_exc.detail == {"code": "milvus.timeout"}

    def test_embedding_unavailable_maps_to_503(self) -> None:
        exc = KylinEmbeddingError("embedding.unavailable")
        http_exc = _retrieval_http_error(exc)
        assert http_exc.status_code == 503
        assert http_exc.detail == {"code": "embedding.unavailable"}

    def test_milvus_call_failed_maps_to_503(self) -> None:
        exc = MilvusEngineError("milvus.call_failed")
        http_exc = _retrieval_http_error(exc)
        assert http_exc.status_code == 503
        assert http_exc.detail == {"code": "milvus.call_failed"}

    def test_non_retrieval_error_maps_to_500(self) -> None:
        http_exc = _retrieval_http_error(RuntimeError("unexpected"))
        assert http_exc.status_code == 500
        assert http_exc.detail == {"code": "retrieval.error"}
