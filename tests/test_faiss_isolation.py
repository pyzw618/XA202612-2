# -*- coding: utf-8 -*-
"""FAISS 降级路径隔离回归测试。

验证 FAISS 相关模块在生产模式下会输出明确的结构化警告，
且生产配置门禁已拒绝 faiss provider。
"""

from __future__ import annotations

import pytest


class TestFAISSVectorEngineIsolation:
    def test_faiss_engine_warns_in_production_mode(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")

        from memoryhub.storage.vector_engine.faiss_engine import FAISSVectorEngine

        with caplog.at_level("WARNING", logger="memoryhub.storage.vector_engine.faiss_engine"):
            engine = FAISSVectorEngine(
                index_path=str(tmp_path / "vector_index"), dimension=768
            )
            engine.close()

        assert any(
            "faiss_vector_engine_initialized_in_production" in record.message
            for record in caplog.records
        )

    def test_faiss_engine_no_warning_in_development_mode(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "development")

        from memoryhub.storage.vector_engine.faiss_engine import FAISSVectorEngine

        with caplog.at_level("WARNING", logger="memoryhub.storage.vector_engine.faiss_engine"):
            engine = FAISSVectorEngine(
                index_path=str(tmp_path / "vector_index"), dimension=768
            )
            engine.close()

        assert not any(
            "faiss_vector_engine_initialized_in_production" in record.message
            for record in caplog.records
        )


class TestVectorStoreIsolation:
    def test_vector_store_warns_in_production_mode(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")

        from memoryhub.storage.vector_store import VectorStore

        with caplog.at_level("WARNING", logger="memoryhub.storage.vector_store"):
            store = VectorStore(index_path=str(tmp_path / "vector_index"), dimension=768)
            store.init_index()

        assert any(
            "faiss_vector_store_initialized_in_production" in record.message
            for record in caplog.records
        )


class TestCreateVectorEngineIsolation:
    def test_create_faiss_warns_in_production_mode(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")

        from memoryhub.storage.vector_engine import create_vector_engine

        with caplog.at_level("WARNING", logger="memoryhub.storage.vector_engine"):
            engine = create_vector_engine(
                provider="faiss",
                index_path=str(tmp_path / "vector_index"),
                dimension=768,
            )
            engine.close()

        assert any(
            "faiss_engine_created_in_production_mode" in record.message
            for record in caplog.records
        )
