# -*- coding: utf-8 -*-
"""应用层生产环境 Retriever 装配测试"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memoryhub.app import create_app
from memoryhub.config import AppConfig, EmbeddingConfig, RuntimeConfig, VectorEngineConfig
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever


@pytest.fixture()
def production_config(tmp_path):
    """生产模式配置：kylin + milvus（真实环境不可用时无法直接启动应用）。"""
    return AppConfig(
        runtime=RuntimeConfig(mode="production", allow_fallback=False),
        embedding=EmbeddingConfig(provider="kylin", dimension=768),
        vector_engine=VectorEngineConfig(provider="milvus", app_id="test-app-id", dimension=768),
    )


def test_production_config_passes_static_gate(production_config) -> None:
    """正确的生产配置应通过静态门禁。"""
    from memoryhub.config import validate_production_gate

    validate_production_gate(production_config)


def test_production_config_rejected_when_vector_engine_not_connected(
    production_config,
) -> None:
    """运行时门禁应拒绝未连接的向量引擎。"""
    from memoryhub.config import ProductionGateError, validate_production_runtime

    class FakeClient:
        def is_available(self):
            return True

        def get_dimension(self):
            return 768

    class FakeEngine:
        _connected = False
        _closed = False

    with pytest.raises(ProductionGateError, match="vector engine is not connected"):
        validate_production_runtime(production_config, FakeClient(), FakeEngine())


def test_create_app_with_production_config_fails_at_runtime(production_config) -> None:
    """生产模式启动时因无法连接真实 Milvus 而失败。"""
    with pytest.raises(Exception):
        with TestClient(create_app(production_config)):
            pass
