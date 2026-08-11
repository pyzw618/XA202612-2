# -*- coding: utf-8 -*-
"""运行时模式与生产环境启动门禁测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    ProductionGateError,
    RuntimeConfig,
    VectorEngineConfig,
    is_production_mode,
    load_config,
    validate_production_gate,
    validate_production_runtime,
)


class FakeEmbeddingClient:
    def __init__(self, available: bool = True, dimension: int = 768):
        self._available = available
        self._dimension = dimension

    def is_available(self) -> bool:
        return self._available

    def get_dimension(self) -> int:
        return self._dimension


class FakeVectorEngine:
    def __init__(self, connected: bool = True, closed: bool = False):
        self._connected = connected
        self._closed = closed


class TestRuntimeConfig:
    def test_default_is_development_with_fallback(self) -> None:
        cfg = RuntimeConfig()
        assert cfg.mode == "development"
        assert cfg.allow_fallback is True
        assert not cfg.is_production

    def test_production_mode(self) -> None:
        cfg = RuntimeConfig(mode="production", allow_fallback=False)
        assert cfg.is_production
        assert not cfg.allow_fallback

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="runtime.mode must be one of"):
            RuntimeConfig(mode="staging")

    def test_allow_fallback_must_be_boolean(self) -> None:
        with pytest.raises(ValueError, match="allow_fallback must be a boolean"):
            RuntimeConfig(allow_fallback="yes")


class TestIsProductionMode:
    def test_returns_true_when_env_is_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")
        assert is_production_mode() is True

    def test_returns_false_when_env_is_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "development")
        assert is_production_mode() is False

    def test_returns_false_when_env_is_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MEMORYHUB_RUNTIME_MODE", raising=False)
        assert is_production_mode() is False


class TestValidateProductionGate:
    def _production_config(
        self,
        *,
        embedding_provider: str = "kylin",
        vector_engine_provider: str = "milvus",
        embedding_dimension: int = 768,
        vector_engine_dimension: int = 768,
        allow_fallback: bool = False,
    ) -> AppConfig:
        return AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=allow_fallback),
            embedding=EmbeddingConfig(
                provider=embedding_provider, dimension=embedding_dimension
            ),
            vector_engine=VectorEngineConfig(
                provider=vector_engine_provider,
                app_id="test-app-id", dimension=vector_engine_dimension
            ),
        )

    def test_passes_with_kylin_milvus_768(self) -> None:
        cfg = self._production_config()
        validate_production_gate(cfg)  # should not raise

    def test_rejects_mock_embedding(self) -> None:
        cfg = self._production_config(embedding_provider="mock")
        with pytest.raises(ProductionGateError, match="embedding.provider"):
            validate_production_gate(cfg)

    def test_rejects_kylin_mock_embedding(self) -> None:
        cfg = self._production_config(embedding_provider="kylin_mock")
        with pytest.raises(ProductionGateError, match="not allowed in production"):
            validate_production_gate(cfg)

    def test_rejects_faiss_vector_engine(self) -> None:
        cfg = self._production_config(vector_engine_provider="faiss")
        with pytest.raises(ProductionGateError, match="vector_engine.provider"):
            validate_production_gate(cfg)

    def test_rejects_milvus_mock_vector_engine(self) -> None:
        cfg = self._production_config(vector_engine_provider="milvus_mock")
        with pytest.raises(ProductionGateError, match="not allowed in production"):
            validate_production_gate(cfg)

    def test_rejects_wrong_embedding_dimension(self) -> None:
        cfg = self._production_config(embedding_dimension=1024)
        with pytest.raises(ProductionGateError, match="embedding.dimension"):
            validate_production_gate(cfg)

    def test_rejects_wrong_vector_engine_dimension(self) -> None:
        cfg = self._production_config(vector_engine_dimension=512)
        with pytest.raises(ProductionGateError, match="vector_engine.dimension"):
            validate_production_gate(cfg)

    def test_rejects_allow_fallback_in_production(self) -> None:
        cfg = self._production_config(allow_fallback=True)
        with pytest.raises(ProductionGateError, match="allow_fallback must be false"):
            validate_production_gate(cfg)

    def test_development_mode_skips_gate(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="development"),
            embedding=EmbeddingConfig(provider="mock", dimension=1024),
            vector_engine=VectorEngineConfig(provider="faiss", dimension=512),
        )
        validate_production_gate(cfg)  # should not raise


class TestValidateProductionRuntime:
    def test_passes_with_available_clients(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=False),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            vector_engine=VectorEngineConfig(
                provider="milvus", app_id="test-app-id", dimension=768
            ),
        )
        validate_production_runtime(
            cfg, FakeEmbeddingClient(), FakeVectorEngine(connected=True)
        )

    def test_rejects_unavailable_embedding(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=False),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            vector_engine=VectorEngineConfig(
                provider="milvus", app_id="test-app-id", dimension=768
            ),
        )
        with pytest.raises(ProductionGateError, match="embedding client is not available"):
            validate_production_runtime(
                cfg, FakeEmbeddingClient(available=False), FakeVectorEngine()
            )

    def test_rejects_wrong_embedding_dimension(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=False),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            vector_engine=VectorEngineConfig(
                provider="milvus", app_id="test-app-id", dimension=768
            ),
        )
        with pytest.raises(ProductionGateError, match="embedding actual dimension"):
            validate_production_runtime(
                cfg, FakeEmbeddingClient(dimension=1024), FakeVectorEngine()
            )

    def test_rejects_unconnected_vector_engine(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=False),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            vector_engine=VectorEngineConfig(
                provider="milvus", app_id="test-app-id", dimension=768
            ),
        )
        with pytest.raises(ProductionGateError, match="vector engine is not connected"):
            validate_production_runtime(
                cfg, FakeEmbeddingClient(), FakeVectorEngine(connected=False)
            )

    def test_rejects_closed_vector_engine(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="production", allow_fallback=False),
            embedding=EmbeddingConfig(provider="kylin", dimension=768),
            vector_engine=VectorEngineConfig(
                provider="milvus", app_id="test-app-id", dimension=768
            ),
        )
        with pytest.raises(ProductionGateError, match="vector engine is closed"):
            validate_production_runtime(
                cfg, FakeEmbeddingClient(), FakeVectorEngine(closed=True)
            )

    def test_development_mode_skips_runtime_gate(self) -> None:
        cfg = AppConfig(
            runtime=RuntimeConfig(mode="development"),
            embedding=EmbeddingConfig(provider="mock"),
            vector_engine=VectorEngineConfig(provider="faiss"),
        )
        validate_production_runtime(
            cfg, FakeEmbeddingClient(available=False), FakeVectorEngine(connected=False)
        )


class TestLoadConfig:
    def test_loads_safety_key_store_section(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "safety:\n"
            "  key_store:\n"
            "    path: private/safety-keys.json\n"
            "    auto_generate: true\n"
            "    persist_external: false\n"
            "  user_rules:\n"
            "    enabled: false\n",
            encoding="utf-8",
        )

        cfg = load_config(str(config_path))

        assert cfg.safety.key_store.path == "private/safety-keys.json"
        assert cfg.safety.key_store.auto_generate is True
        assert cfg.safety.key_store.persist_external is False
        assert cfg.safety.user_rules.enabled is False

    def test_loads_runtime_section(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "runtime:\n  mode: production\n  allow_fallback: false\n"
            "embedding:\n  provider: kylin\n  dimension: 768\n"
            "vector_engine:\n  provider: milvus\n  app_id: test-app-id\n  dimension: 768\n",
            encoding="utf-8",
        )
        cfg = load_config(str(config_path))
        assert cfg.runtime.mode == "production"
        assert cfg.runtime.allow_fallback is False
        assert cfg.embedding.provider == "kylin"
        assert cfg.embedding.dimension == 768
        assert cfg.vector_engine.provider == "milvus"
        assert cfg.vector_engine.dimension == 768

    def test_environment_variable_overrides(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "runtime:\n  mode: development\n  allow_fallback: true\n"
            "embedding:\n  provider: mock\n"
            "vector_engine:\n  provider: faiss\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "test")
        monkeypatch.setenv("MEMORYHUB_RUNTIME_ALLOW_FALLBACK", "0")
        monkeypatch.setenv("MEMORYHUB_EMBEDDING_PROVIDER", "kylin")
        monkeypatch.setenv("MEMORYHUB_VECTOR_ENGINE_PROVIDER", "milvus")
        monkeypatch.setenv("MEMORYHUB_VECTOR_ENGINE_APP_ID", "test-app-id")

        cfg = load_config(str(config_path))
        assert cfg.runtime.mode == "test"
        assert cfg.runtime.allow_fallback is False
        assert cfg.embedding.provider == "kylin"
        assert cfg.vector_engine.provider == "milvus"

    def test_invalid_runtime_mode_from_env_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("runtime:\n  mode: development\n", encoding="utf-8")
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "invalid_mode")
        with pytest.raises(ValueError, match="runtime.mode must be one of"):
            load_config(str(config_path))

    def test_production_gate_runs_after_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("runtime:\n  mode: development\n", encoding="utf-8")
        monkeypatch.setenv("MEMORYHUB_RUNTIME_MODE", "production")
        monkeypatch.setenv("MEMORYHUB_EMBEDDING_PROVIDER", "mock")
        monkeypatch.setenv("MEMORYHUB_VECTOR_ENGINE_PROVIDER", "faiss")
        with pytest.raises(ProductionGateError):
            load_config(str(config_path))

    def test_default_config_is_development_safe(self) -> None:
        cfg = load_config()
        assert cfg.runtime.mode == "development"
        assert cfg.runtime.allow_fallback is True
        assert cfg.embedding.provider == "mock"
        assert cfg.vector_engine.provider == "faiss"
