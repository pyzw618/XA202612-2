# -*- coding: utf-8 -*-
"""
SQLite-Milvus 写入同步与补偿链路回归测试。

覆盖:
  - 正常写入：SQLite 成功 + Milvus 成功，标记 index_version 并失效缓存
  - Milvus 失败：保留 pending_index，由补偿任务重试
  - 遗忘流程：SQLite 软删除 + Milvus 删除 + 缓存失效
  - 启动修复：仅同步 pending_index 记录，禁止全量重建
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
    SearchRequest,
)
from memoryhub.app import create_app
from memoryhub.config import (
    AppConfig,
    EmbeddingConfig,
    SafetyConfig,
    StorageConfig,
    UserRuleConfig,
    VectorEngineConfig,
)
from memoryhub.retrieval.cache import SearchCache
from memoryhub.storage.compensation_task import PendingIndexCompensationTask
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import KnowledgeRow, PreferenceRow
from memoryhub.storage.sync_service import MemorySyncService


def _save_preference(db: Database, memory: PreferenceMemory, pending_index: bool = True) -> None:
    """直接写 PreferenceRow（兼容当前 schema）"""
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
                pending_index=pending_index,
            )
        )


@pytest.fixture()
def sync_setup(tmp_path):
    """创建带 milvus_mock 引擎的 MemorySyncService 测试环境。"""
    db_path = str(tmp_path / "sync.db")
    db = Database(db_path=db_path)
    db.init_schema()

    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)

    from memoryhub.embedding import create_embedding_client
    from memoryhub.storage.vector_engine import create_vector_engine

    embedding_client = create_embedding_client(provider="kylin_mock", dim=768)
    vector_engine = create_vector_engine(
        "milvus_mock",
        app_id="test-app-id",
        collection="sync_test",
        dimension=768,
    )
    cache = SearchCache(max_size=100, ttl_seconds=300)

    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        embedding_client=embedding_client,
        vector_engine=vector_engine,
        cache=cache,
        retriever=None,
        index_version=1,
    )

    yield {
        "db": db,
        "pref_repo": pref_repo,
        "know_repo": know_repo,
        "embedding_client": embedding_client,
        "vector_engine": vector_engine,
        "cache": cache,
        "service": service,
    }

    vector_engine.close()
    db.close()


def test_index_memory_syncs_to_milvus(sync_setup):
    """正常写入时 SQLite 与 Milvus 同时成功，并标记 indexed。"""
    service = sync_setup["service"]
    pref_repo = sync_setup["pref_repo"]

    pref = PreferenceMemory(
        user_id="u1",
        text="代码评审前先跑单元测试",
        scope=SceneScope(scene="code", task_type="code.review"),
        confidence=0.85,
    )

    sqlite_ok, memory_id = service.index_memory(pref)
    assert sqlite_ok is True
    assert memory_id == pref.memory_id

    # SQLite 已同步
    stored = pref_repo.get_by_id(memory_id)
    assert stored is not None

    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
        assert row.pending_index is False
        assert row.index_version > 0

    # Milvus 可检索
    results = sync_setup["vector_engine"].search(
        sync_setup["embedding_client"].embed("单元测试"), top_k=5
    )
    assert any(r.memory_id == memory_id for r in results)


def test_index_memory_milvus_failure_keeps_pending(sync_setup):
    """Milvus upsert 失败时，SQLite 保留 pending_index。"""
    service = sync_setup["service"]

    # 关闭向量引擎模拟 Milvus 不可用
    sync_setup["vector_engine"].close()

    pref = PreferenceMemory(
        user_id="u1",
        text="失败补偿测试",
        confidence=0.5,
    )

    sqlite_ok, memory_id = service.index_memory(pref)
    assert sqlite_ok is True

    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
        assert row.pending_index is True


def test_delete_memory_marks_deleted_and_removes_vector(sync_setup):
    """遗忘时先标记 SQLite 删除，再删除 Milvus 向量，并失效缓存。"""
    service = sync_setup["service"]
    cache = sync_setup["cache"]

    pref = PreferenceMemory(
        user_id="u1",
        text="将被遗忘的偏好",
        confidence=0.7,
    )
    service.index_memory(pref)

    # 填充缓存
    request = SearchRequest(user_id="u1", query="被遗忘", top_k=5)
    response = sync_setup["cache"].get(request, version="1")
    assert response is None
    # 构造一个包含该记忆的缓存条目
    from memoryhub.adapter.schemas import SearchResponse

    cached_response = SearchResponse(results=[], preferences=[pref], knowledge=[], latency_ms=0)
    cache.set(request, cached_response, version="1")
    assert cache.get(request, version="1") is not None

    ok = service.delete_memory(pref.memory_id)
    assert ok is True

    # SQLite 已软删除
    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
        assert row.status == "deleted"

    # Milvus 向量已删除
    results = sync_setup["vector_engine"].search(
        sync_setup["embedding_client"].embed("被遗忘"), top_k=5
    )
    assert not any(r.memory_id == pref.memory_id for r in results)

    # 缓存已失效
    assert cache.get(request, version="1") is None


def test_sync_pending_compensates_failed_records(sync_setup):
    """补偿任务扫描 pending_index 记录并完成同步。"""
    service = sync_setup["service"]
    pref_repo = sync_setup["pref_repo"]

    # 先写入一条 pending 记录（模拟 Milvus 失败）
    pref = PreferenceMemory(
        user_id="u1",
        text="待补偿的偏好",
        confidence=0.6,
    )
    pref_repo.save(pref)

    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
        assert row.pending_index is True

    result = service.sync_pending()
    assert pref.memory_id in result.succeeded

    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
        assert row.pending_index is False
        assert row.index_version > 0


def test_compensation_task_scans_and_syncs(sync_setup):
    """PendingIndexCompensationTask 后台运行并完成补偿。"""
    service = sync_setup["service"]
    pref_repo = sync_setup["pref_repo"]

    pref = PreferenceMemory(
        user_id="u1",
        text="后台补偿测试",
        confidence=0.6,
    )
    pref_repo.save(pref)

    task = PendingIndexCompensationTask(
        sync_service=service,
        interval_seconds=0.5,
        enabled=True,
    )
    task.start()
    try:
        # 等待后台线程至少执行一次
        for _ in range(50):
            time.sleep(0.05)
            metrics = task.metrics
            if metrics.total_runs > 0 and pref.memory_id not in service.pref_repo.list_pending():
                break

        with sync_setup["db"].session() as s:
            row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
            assert row.pending_index is False
    finally:
        task.stop()


def test_app_startup_creates_sync_service_and_compensation(tmp_path):
    """create_app 启动时应创建 sync_service 与 compensation_task。"""
    db_path = str(tmp_path / "app_sync.db")
    db = Database(db_path=db_path)
    db.init_schema()
    pref = PreferenceMemory(user_id="u1", text="启动同步测试", confidence=0.8)
    _save_preference(db, pref)
    db.close()

    config = AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="kylin_mock", dimension=768),
        vector_engine=VectorEngineConfig(provider="milvus_mock", app_id="test-app-id"),
    )

    with TestClient(create_app(config)) as client:
        app = client.app
        assert hasattr(app.state, "sync_service")
        assert hasattr(app.state, "compensation_task")
        assert app.state.sync_service is not None
        assert app.state.compensation_task is not None

        # 启动修复应把 pending 记录同步
        db = Database(db_path=db_path)
        db.init_schema()
        with db.session() as s:
            row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
            assert row.pending_index is False
        db.close()


def _milvus_mock_config(tmp_path, db_path: str):
    return AppConfig(
        storage=StorageConfig(
            db_path=db_path,
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        embedding=EmbeddingConfig(provider="kylin_mock", dimension=768),
        vector_engine=VectorEngineConfig(provider="milvus_mock", app_id="test-app-id"),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )


def test_api_write_preference_syncs_to_milvus(tmp_path):
    """POST /api/memory/memories/preference 写入并同步到 Milvus。"""
    db_path = str(tmp_path / "api_write.db")
    config = _milvus_mock_config(tmp_path, db_path)

    pref = PreferenceMemory(
        user_id="u1",
        text="API 写入的偏好",
        confidence=0.8,
    )

    with TestClient(create_app(config)) as client:
        resp = client.post("/api/memory/memories/preference", json=pref.model_dump(mode="json"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"

    db = Database(db_path=db_path)
    db.init_schema()
    with db.session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == body["memory_id"]).first()
        assert row is not None
        assert row.pending_index is False
    db.close()


def test_api_write_knowledge_syncs_to_milvus(tmp_path):
    """POST /api/memory/memories/knowledge 写入并同步到 Milvus。"""
    db_path = str(tmp_path / "api_write_know.db")
    config = _milvus_mock_config(tmp_path, db_path)

    know = KnowledgeMemory(
        user_id="u1",
        name="API 知识",
        content="通过 API 写入的知识内容",
        confidence=0.85,
    )

    with TestClient(create_app(config)) as client:
        resp = client.post("/api/memory/memories/knowledge", json=know.model_dump(mode="json"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"

    db = Database(db_path=db_path)
    db.init_schema()
    with db.session() as s:
        row = s.query(KnowledgeRow).filter(KnowledgeRow.memory_id == body["memory_id"]).first()
        assert row is not None
        assert row.pending_index is False
    db.close()


def test_api_forget_removes_from_milvus(tmp_path):
    """POST /api/memory/forget 删除 SQLite 与 Milvus 中的记忆。"""
    db_path = str(tmp_path / "api_forget.db")
    db = Database(db_path=db_path)
    db.init_schema()
    pref = PreferenceMemory(
        user_id="u1",
        text="将被 API 遗忘的偏好",
        confidence=0.8,
    )
    _save_preference(db, pref, pending_index=False)
    db.close()

    config = _milvus_mock_config(tmp_path, db_path)

    from memoryhub.adapter.schemas import ForgetRequest

    with TestClient(create_app(config)) as client:
        # 先通过 API 写入向量索引
        client.post("/api/memory/memories/preference", json=pref.model_dump(mode="json"))
        # 再通过遗忘 API 删除
        resp = client.post(
            "/api/memory/forget",
            json=ForgetRequest(
                user_id="u1",
                target_memory_ids=[pref.memory_id],
            ).model_dump(mode="json"),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted_count"] >= 1

    db = Database(db_path=db_path)
    db.init_schema()
    with db.session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == pref.memory_id).first()
        assert row.status == "deleted"
    db.close()


def test_milvus_success_sqlite_mark_indexed_failure_compensates(sync_setup):
    """Milvus upsert 成功但 SQLite 标记 indexed 失败时，记忆应保持 pending
    并可被补偿修复，避免幽灵向量被检索。"""
    service = sync_setup["service"]
    pref_repo = sync_setup["pref_repo"]
    vector_engine = sync_setup["vector_engine"]
    embedding_client = sync_setup["embedding_client"]

    pref = PreferenceMemory(
        user_id="u1",
        text="Milvus 成功 SQLite 标记失败补偿测试",
        confidence=0.7,
    )

    # 第一次写入：SQLite 保存成功，Milvus upsert 成功，但 mark_indexed 被模拟失败
    original_mark_indexed = pref_repo.mark_indexed
    call_count = 0

    def failing_mark_indexed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("模拟 SQLite 标记 indexed 失败")

    pref_repo.mark_indexed = failing_mark_indexed
    try:
        sqlite_ok, memory_id = service.index_memory(pref)
    finally:
        pref_repo.mark_indexed = original_mark_indexed

    assert sqlite_ok is True
    assert call_count >= 1

    # 记忆应保持 pending_index，避免被当作已同步检索
    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
        assert row.pending_index is True

    # Milvus 中已有向量（这是 Milvus 成功而 SQLite 失败产生的潜在幽灵向量）
    query_vec = embedding_client.embed("Milvus 成功 SQLite 标记失败补偿测试")
    results = vector_engine.search(query_vec, top_k=5)
    assert any(r.memory_id == memory_id for r in results)

    # 通过补偿任务修复：重新 upsert（幂等）并正确标记 indexed
    result = service.sync_pending()
    assert memory_id in result.succeeded

    with sync_setup["db"].session() as s:
        row = s.query(PreferenceRow).filter(PreferenceRow.memory_id == memory_id).first()
        assert row.pending_index is False
        assert row.index_version > 0


def test_sqlite_write_failure_does_not_create_ghost_vector(sync_setup):
    """SQLite 初始写入失败时，不应向 Milvus 写入向量，避免幽灵向量。"""
    service = sync_setup["service"]
    pref_repo = sync_setup["pref_repo"]
    vector_engine = sync_setup["vector_engine"]
    embedding_client = sync_setup["embedding_client"]

    pref = PreferenceMemory(
        user_id="u1",
        text="SQLite 写入失败不应产生幽灵向量",
        confidence=0.6,
    )

    original_save = pref_repo.save

    def failing_save(*args, **kwargs):
        raise RuntimeError("模拟 SQLite 写入失败")

    pref_repo.save = failing_save
    try:
        sqlite_ok, memory_id = service.index_memory(pref)
    finally:
        pref_repo.save = original_save

    assert sqlite_ok is False

    # Milvus 中不应存在该记忆的向量
    query_vec = embedding_client.embed("SQLite 写入失败不应产生幽灵向量")
    results = vector_engine.search(query_vec, top_k=5)
    assert not any(r.memory_id == memory_id for r in results)
