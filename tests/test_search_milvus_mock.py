# -*- coding: utf-8 -*-
"""端到端测试：milvus_mock 向量引擎 + kylin_mock Embedding 全链路。

以 vector_engine.provider="milvus_mock" + embedding.provider="kylin_mock"
创建应用，启动时对存量记忆全量 insert 到 mock 引擎，再通过
POST /api/memory/search 断言能检索到记忆。

说明：当前 app.py 的 startup 未接线事件写入（event_repo），记忆写入
没有可用的 HTTP API；且 PreferenceRepository.save 与当前
PreferenceMemory schema 存在 content/text 字段错位（存量问题，
test_search_integration.py 因此报错）。因此直接写 PreferenceRow /
KnowledgeRepository 把记忆放进临时 SQLite，再由 startup 同步进向量引擎。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory, SceneScope
from memoryhub.app import create_app
from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    StorageConfig,
    VectorEngineConfig,
)
from memoryhub.storage.database import Database, KnowledgeRepository
from memoryhub.storage.models import PreferenceRow


def _save_preference(db: Database, memory: PreferenceMemory) -> None:
    """直接写 PreferenceRow（PreferenceRepository.save 依赖已错位的 content 字段）"""
    with db.session() as s:
        s.merge(
            PreferenceRow(
                memory_id=memory.memory_id,
                user_id=memory.user_id,
                preference_type=memory.preference_type.value,
                content=memory.text,
                scope_scene=memory.scope.scene,
                scope_task_type=memory.scope.task_type,
                scope_app=memory.scope.app,
                confidence=memory.confidence,
                status=memory.status.value,
                level=memory.level.value,
                version=memory.version,
                parent_id=memory.parent_id or None,
                evidences=[],
            )
        )


@pytest.fixture()
def milvus_mock_config(tmp_path):
    """先在临时 DB 里写入两条记忆，再返回 milvus_mock 链路配置"""
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path=db_path)
    db.init_schema()

    pref = PreferenceMemory(
        user_id="u1",
        text="项目周报默认使用 Markdown 格式",
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
        confidence=0.9,
    )
    know = KnowledgeMemory(
        user_id="u1",
        name="周报生成流程",
        content="收集事件、生成大纲、填充模板",
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
        confidence=0.85,
    )
    _save_preference(db, pref)
    KnowledgeRepository(db).save(know)
    db.close()

    config = AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        # kylin_mock 动态库固定 768 维模型
        embedding=EmbeddingConfig(provider="kylin_mock", dimension=768),
        vector_engine=VectorEngineConfig(provider="milvus_mock"),
    )
    config._seeded = (pref, know)
    return config


def test_milvus_mock_search_recalls_seeded_memories(milvus_mock_config):
    """startup 全量 insert 后，/api/memory/search 能检索到刚写入的记忆"""
    pref, know = milvus_mock_config._seeded
    with TestClient(create_app(milvus_mock_config)) as client:
        resp = client.post(
            "/api/memory/search",
            json={"user_id": "u1", "query": "周报", "top_k": 5},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    pref_ids = [p["memory_id"] for p in body["preferences"]]
    know_ids = [k["memory_id"] for k in body["knowledge"]]
    assert pref.memory_id in pref_ids, f"偏好未召回: {body}"
    assert know.memory_id in know_ids, f"知识未召回: {body}"

    # 结果走 hybrid 链路，返回完整记忆对象
    assert all(r["source"] == "hybrid" for r in body["results"])
    full_pref = body["preferences"][pref_ids.index(pref.memory_id)]
    assert full_pref["text"] == "项目周报默认使用 Markdown 格式"
    assert body["latency_ms"] >= 0


def test_milvus_mock_search_filters(milvus_mock_config):
    """memory_types 过滤在 milvus_mock 链路同样生效"""
    pref, know = milvus_mock_config._seeded
    with TestClient(create_app(milvus_mock_config)) as client:
        resp = client.post(
            "/api/memory/search",
            json={
                "user_id": "u1",
                "query": "周报",
                "top_k": 5,
                "memory_types": ["knowledge"],
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preferences"] == []
    assert [k["memory_id"] for k in body["knowledge"]] == [know.memory_id]


def test_milvus_mock_embedding_python_client(tmp_path):
    """embedding.provider="mock"（纯 Python）+ milvus_mock 引擎也可跑通"""
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path=db_path)
    db.init_schema()
    pref = PreferenceMemory(user_id="u1", text="代码评审前先跑单元测试", confidence=0.8)
    _save_preference(db, pref)
    db.close()

    config = AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="mock", dimension=64),
        vector_engine=VectorEngineConfig(provider="milvus_mock"),
    )
    with TestClient(create_app(config)) as client:
        resp = client.post(
            "/api/memory/search",
            json={"user_id": "u1", "query": "单元测试", "top_k": 5},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [p["memory_id"] for p in body["preferences"]] == [pref.memory_id]
