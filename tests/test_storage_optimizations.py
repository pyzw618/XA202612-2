"""
存储层优化测试。

覆盖:
  1. get_version_chain 的 root_id 快路径（单条 SQL 取全链）
  2. save() 的 root_id 自动继承兜底
  3. MemorySyncService.reconcile() 正向补写 + 反向删除漂移
"""

from __future__ import annotations

from pathlib import Path

from memoryhub.adapter.schemas import KnowledgeMemory, PreferenceMemory
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.sync_service import MemorySyncService


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "opt.db"))
    db.init_schema()
    return db


class _FakeEmbedding:
    """固定维度假 embedding，仅用于对账流程测试。"""

    def __init__(self, dim: int = 768):
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        # 确定性向量：按字符 hash 生成，保证同文本同向量
        seed = sum(ord(c) for c in text)
        return [(seed % 97 + i * 0.001) for i in range(self._dim)]

    def get_dimension(self) -> int:
        return self._dim


class _FakeVectorEngine:
    """记录 upsert/delete 调用的假向量引擎。"""

    def __init__(self):
        self.upserted: dict[str, bool] = {}
        self.deleted: list[str] = []

    def upsert(self, memory_id, text, vector, metadata=None):
        self.upserted[memory_id] = True

    def delete(self, memory_id: str):
        self.deleted.append(memory_id)


# ============================================================
# 1. get_version_chain 优化
# ============================================================

def test_version_chain_fast_path_orders_by_version(tmp_path: Path) -> None:
    """有 root_id 的记录一次查全链，按 version 升序。"""
    repo = PreferenceRepository(_db(tmp_path))
    repo.save(PreferenceMemory(memory_id="p1", user_id="u1", text="V1",
                               version=1, root_id="p1"))
    repo.save(PreferenceMemory(memory_id="p2", user_id="u1", text="V2",
                               version=2, parent_id="p1", root_id="p1"))
    repo.save(PreferenceMemory(memory_id="p3", user_id="u1", text="V3",
                               version=3, parent_id="p2", root_id="p1"))

    chain = repo.get_version_chain("p3")
    assert [m.memory_id for m in chain] == ["p1", "p2", "p3"]
    assert [m.text for m in chain] == ["V1", "V2", "V3"]


def test_version_chain_mid_chain_entry_still_returns_full_chain(tmp_path: Path) -> None:
    """从链中间（p2）查询，同样返回完整链。"""
    repo = PreferenceRepository(_db(tmp_path))
    repo.save(PreferenceMemory(memory_id="p1", user_id="u1", text="V1",
                               version=1, root_id="p1"))
    repo.save(PreferenceMemory(memory_id="p2", user_id="u1", text="V2",
                               version=2, parent_id="p1", root_id="p1"))

    chain = repo.get_version_chain("p2")
    assert [m.memory_id for m in chain] == ["p1", "p2"]


def test_save_inherits_root_id_from_parent(tmp_path: Path) -> None:
    """传 parent_id 但没传 root_id 时，save() 自动从父记录继承。"""
    repo = PreferenceRepository(_db(tmp_path))
    repo.save(PreferenceMemory(memory_id="r1", user_id="u1", text="根",
                               version=1, root_id="r1"))
    # 新版本：故意不传 root_id
    repo.save(PreferenceMemory(memory_id="r2", user_id="u1", text="子",
                               version=2, parent_id="r1"))

    chain = repo.get_version_chain("r2")
    assert [m.memory_id for m in chain] == ["r1", "r2"]


def test_version_chain_legacy_data_without_root_id(tmp_path: Path) -> None:
    """旧数据没有 root_id 时走 parent 链兜底路径，结果仍正确。

    用底层 SQL 直插模拟 save() 改造前落库的旧数据
    （save() 现在会自动继承 root_id，无法通过正常路径造出）。
    """
    db = _db(tmp_path)
    from memoryhub.storage.models import PreferenceRow
    with db.session() as s:
        s.add(PreferenceRow(memory_id="l1", user_id="u1", content="旧1",
                            preference_type="format_preference",
                            version=1, parent_id=None, root_id=None))
        s.add(PreferenceRow(memory_id="l2", user_id="u1", content="旧2",
                            preference_type="format_preference",
                            version=2, parent_id="l1", root_id=None))
    repo = PreferenceRepository(db)

    chain = repo.get_version_chain("l2")
    assert [m.memory_id for m in chain] == ["l1", "l2"]


def test_version_chain_missing_returns_empty(tmp_path: Path) -> None:
    repo = PreferenceRepository(_db(tmp_path))
    assert repo.get_version_chain("nonexistent") == []


# ============================================================
# 2. reconcile 对账
# ============================================================

def _make_sync(tmp_path: Path):
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    engine = _FakeVectorEngine()
    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        embedding_client=_FakeEmbedding(64),
        vector_engine=engine,
    )
    return service, pref_repo, know_repo, engine


def test_reconcile_upserts_pending_active(tmp_path: Path) -> None:
    """正向：active 且 pending 的记录被补写进向量引擎。"""
    service, pref_repo, _, engine = _make_sync(tmp_path)
    pref_repo.save(PreferenceMemory(memory_id="pa", user_id="u1", text="活跃偏好"))

    report = service.reconcile()
    assert "pa" in engine.upserted, "pending active 记录应被补写"
    assert report["synced"] == 1
    assert report["still_pending"] == 0


def test_reconcile_deletes_pending_inactive(tmp_path: Path) -> None:
    """反向：归档/删除且 pending 的记录，其向量被删除。"""
    service, pref_repo, _, engine = _make_sync(tmp_path)
    pref_repo.save(PreferenceMemory(memory_id="pb", user_id="u1", text="待删偏好"))
    pref_repo.update_status("pb", "deleted")  # update_status 会置 pending_index

    report = service.reconcile()
    assert "pb" in engine.deleted, "pending 非 active 记录应删除向量"
    assert report["synced"] == 1
    assert report["still_pending"] == 0


def test_reconcile_covers_preference_and_knowledge(tmp_path: Path) -> None:
    """两类记忆的 pending 都参与对账。"""
    service, pref_repo, know_repo, engine = _make_sync(tmp_path)
    pref_repo.save(PreferenceMemory(memory_id="pc", user_id="u1", text="偏好"))
    know_repo.save(KnowledgeMemory(memory_id="kc", user_id="u1",
                                   knowledge_type="case", name="知识"))

    report = service.reconcile()
    assert "pc" in engine.upserted
    assert "kc" in engine.upserted
    assert report["synced"] == 2


def test_reconcile_clean_when_no_pending(tmp_path: Path) -> None:
    """没有 pending 记录时对账返回干净状态。"""
    service, _, _, _ = _make_sync(tmp_path)
    report = service.reconcile()
    assert report["synced"] == 0
    assert report["failed"] == 0
    assert report["still_pending"] == 0


def test_reconcile_reports_failure_without_engine(tmp_path: Path) -> None:
    """向量引擎不可用时，对账报告失败而不是崩溃。"""
    db = _db(tmp_path)
    pref_repo = PreferenceRepository(db)
    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=KnowledgeRepository(db),
        embedding_client=_FakeEmbedding(64),
        vector_engine=None,  # 引擎缺失
    )
    pref_repo.save(PreferenceMemory(memory_id="pd", user_id="u1", text="会失败"))

    report = service.reconcile()
    assert report["failed"] == 1
    assert report["still_pending"] == 1  # 保留 pending 等待下次重试
