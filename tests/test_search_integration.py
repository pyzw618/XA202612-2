# -*- coding: utf-8 -*-
"""检索 + storage 集成的端到端测试

验证 create_app 启动接线：
- 启动时从 SQLite 全量加载记忆 → memory_lookup / BM25 索引
- VectorStore 为空时按记忆文本重建向量索引并保存
- POST /api/memory/search 返回完整记忆对象（而非空壳）
- scope 过滤与缓存命中行为
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory, SceneScope
from memoryhub.app import create_app
from memoryhub.config import AppConfig, EmbeddingConfig, StorageConfig
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository


@pytest.fixture()
def seeded_config(tmp_path):
    """先在临时 DB 里写入两条记忆，再返回指向该 DB 的配置"""
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path=db_path)
    db.init_schema()

    pref = PreferenceMemory(
        user_id="u1",
        content="项目周报默认使用 Markdown 格式",
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
    PreferenceRepository(db).save(pref)
    KnowledgeRepository(db).save(know)
    db.close()

    config = AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="mock", dimension=64),
    )
    config._seeded = (pref, know)  # 测试断言用
    return config


def test_search_returns_full_memory_objects(seeded_config):
    pref, know = seeded_config._seeded
    with TestClient(create_app(seeded_config)) as client:
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

    # 返回的是完整记忆对象，不是空壳
    full_pref = body["preferences"][pref_ids.index(pref.memory_id)]
    assert full_pref["content"] == "项目周报默认使用 Markdown 格式"
    assert full_pref["confidence"] == 0.9
    full_know = body["knowledge"][know_ids.index(know.memory_id)]
    assert full_know["name"] == "周报生成流程"
    assert body["latency_ms"] >= 0


def test_vector_index_rebuilt_and_persisted(seeded_config, tmp_path):
    """启动时 VectorStore 为空 → 从 SQLite 重建并保存到磁盘"""
    with TestClient(create_app(seeded_config)):
        pass
    index_files = list(tmp_path.glob("vector_index*"))
    assert index_files, "向量索引未保存到磁盘"


def test_search_scope_filter(seeded_config):
    pref, know = seeded_config._seeded
    with TestClient(create_app(seeded_config)) as client:
        # context 与两条记忆的 scope 冲突（scene 不匹配），应被过滤
        resp = client.post(
            "/api/memory/search",
            json={
                "user_id": "u1",
                "query": "周报",
                "top_k": 5,
                "context": {"scene": "code", "task_type": "code.review"},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["preferences"] == []
        assert body["knowledge"] == []

        # memory_types 过滤：只要 knowledge
        resp2 = client.post(
            "/api/memory/search",
            json={
                "user_id": "u1",
                "query": "周报",
                "top_k": 5,
                "memory_types": ["knowledge"],
            },
        )
        body2 = resp2.json()
        assert body2["preferences"] == []
        assert [k["memory_id"] for k in body2["knowledge"]] == [know.memory_id]


def test_search_cache_hit(seeded_config):
    with TestClient(create_app(seeded_config)) as client:
        payload = {"user_id": "u1", "query": "周报", "top_k": 5}
        first = client.post("/api/memory/search", json=payload).json()
        second = client.post("/api/memory/search", json=payload).json()
    assert first["total_count"] == second["total_count"]
    assert [p["memory_id"] for p in first["preferences"]] == [
        p["memory_id"] for p in second["preferences"]
    ]
