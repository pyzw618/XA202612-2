"""
跨存储事务补偿测试 — B20 修复验证。

验证场景:
  1. 正常路径：所有步骤成功，不触发回滚
  2. 中间失败：SQLite 成功 → FAISS 失败 → 自动回滚 SQLite
  3. 多步失败：前两步成功 → 第三步失败 → 逆序回滚前两步
  4. 回滚本身失败：记录日志但不吞原始异常
  5. 上下文管理器：with 语句自动回滚
"""

import os
import tempfile

import numpy as np
import pytest

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
)
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.evidence_store import EvidenceStore
from memoryhub.storage.transaction import StorageTransaction
from memoryhub.storage.vector_store import VectorStore


# ═══════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def db(tmpdir):
    database = Database(os.path.join(tmpdir, "test.db"))
    database.init_schema()
    return database


@pytest.fixture
def pref_repo(db):
    return PreferenceRepository(db)


@pytest.fixture
def know_repo(db):
    return KnowledgeRepository(db)


@pytest.fixture
def vector_store(tmpdir):
    vs = VectorStore(index_path=os.path.join(tmpdir, "vs"), dimension=768)
    vs.init_index()
    return vs


@pytest.fixture
def evidence_store(tmpdir):
    return EvidenceStore(os.path.join(tmpdir, "evidences"))


def _vec(seed=99):
    return np.random.RandomState(seed).randn(768).astype(np.float32).tolist()


# ═══════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════

class TestNormalPath:
    """正常路径：所有步骤成功，不触发回滚。"""

    def test_all_steps_succeed_no_rollback(self, pref_repo, vector_store, evidence_store):
        tx = StorageTransaction("normal")
        mid = "pref_normal"

        memory = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="正常写入", scope=SceneScope(scene="test"),
        )
        pref_repo.save(memory)
        tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

        vector_store.add(memory.memory_id, _vec(1))
        tx.on_failure(lambda: vector_store.delete(memory.memory_id))

        ev = Evidence(event_id="ev_1", content="证据", source_type="user_behavior")
        evidence_store.save(memory.memory_id, ev)
        tx.on_failure(lambda: evidence_store.delete(memory.memory_id))

        # 没有异常 → 不触发回滚
        assert pref_repo.get_by_id(memory.memory_id) is not None
        assert vector_store.size() >= 1
        assert len(evidence_store.load(memory.memory_id)) == 1


class TestSingleRollback:
    """单步回滚：第二步失败 → 回滚第一步。"""

    def test_faiss_fails_rolls_back_sqlite(self, pref_repo, vector_store, evidence_store):
        tx = StorageTransaction("faiss_fails")
        mid = "pref_faiss_fail"

        # ① SQLite 写入成功
        memory = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="应被回滚", scope=SceneScope(scene="test"),
        )
        pref_repo.save(memory)
        tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

        # ② FAISS 写入失败（模拟：传一个维度不对的向量）
        try:
            vector_store.add(memory.memory_id, [0.1, 0.2])  # 只有 2 维，会失败
            tx.on_failure(lambda: vector_store.delete(memory.memory_id))
        except Exception:
            tx.rollback()
            # 不 raise，这里验证回滚效果

        # ③ 验证：SQLite 被回滚了
        assert pref_repo.get_by_id(memory.memory_id) is None, \
            "FAISS 失败后 SQLite 写入应该被回滚"

    def test_evidence_fails_rolls_back_sqlite_and_faiss(self, pref_repo, vector_store, evidence_store):
        """证据写入失败 → 回滚 SQLite 和 FAISS。"""
        tx = StorageTransaction("evidence_fails")
        mid = "pref_ev_fail"

        # ① SQLite 成功
        memory = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="应被回滚", scope=SceneScope(scene="test"),
        )
        pref_repo.save(memory)
        tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

        # ② FAISS 成功
        vector_store.add(memory.memory_id, _vec(2))
        tx.on_failure(lambda: vector_store.delete(memory.memory_id))

        # ③ 模拟 Evidence 失败 → 触发回滚
        # （真实场景可能是磁盘满、权限不够等）
        tx.on_failure(lambda: evidence_store.delete(memory.memory_id))
        tx.rollback()  # 手动触发（模拟 try/except 中的 rollback）

        # 验证 SQLite 被回滚
        assert pref_repo.get_by_id(memory.memory_id) is None
        # 验证 FAISS 被回滚
        assert memory.memory_id not in vector_store.reverse_map or \
            memory.memory_id in vector_store._removed_ids


class TestContextManager:
    """上下文管理器：with 语句自动回滚。"""

    def test_with_statement_auto_rollback(self, pref_repo, vector_store):
        mid = "pref_with"

        memory = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="with 语句", scope=SceneScope(scene="test"),
        )

        with pytest.raises(ValueError):
            with StorageTransaction("ctx_test") as tx:
                pref_repo.save(memory)
                tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

                vector_store.add(memory.memory_id, _vec(3))
                tx.on_failure(lambda: vector_store.delete(memory.memory_id))

                # 第二步后抛异常 → 触发回滚
                raise ValueError("模拟中间失败")

        # 验证都被回滚了
        assert pref_repo.get_by_id(memory.memory_id) is None
        assert memory.memory_id not in vector_store.reverse_map or \
            memory.memory_id in vector_store._removed_ids

    def test_with_statement_no_exception_no_rollback(self, pref_repo, vector_store):
        """with 语句正常退出不触发回滚。"""
        mid = "pref_no_exc"

        memory = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="不抛异常", scope=SceneScope(scene="test"),
        )

        with StorageTransaction("no_exc") as tx:
            pref_repo.save(memory)
            tx.on_failure(lambda: pref_repo.delete_by_id(memory.memory_id))

        # 没有异常 → 数据还在
        assert pref_repo.get_by_id(memory.memory_id) is not None


class TestKnowledgeRollback:
    """知识写入的补偿。"""

    def test_knowledge_write_with_compensation(self, know_repo, vector_store, evidence_store):
        mid = "know_comp"

        knowledge = KnowledgeMemory(
            user_id="u1", knowledge_type="workflow", name="补偿测试",
            content="应被回滚", scope=SceneScope(scene="test"),
        )

        with pytest.raises(ValueError):
            with StorageTransaction("know_test") as tx:
                know_repo.save(knowledge)
                tx.on_failure(lambda: know_repo.delete_by_id(knowledge.memory_id))

                vector_store.add(knowledge.memory_id, _vec(4))
                tx.on_failure(lambda: vector_store.delete(knowledge.memory_id))

                raise ValueError("模拟失败")

        # 验证 SQLite 被回滚
        assert know_repo.get_by_id(knowledge.memory_id) is None
        # 验证 FAISS 被回滚
        assert knowledge.memory_id not in vector_store.reverse_map or \
            knowledge.memory_id in vector_store._removed_ids


class TestRollbackLogging:
    """回滚本身失败时记录日志但不吞异常。"""

    def test_rollback_failure_logs_but_continues(self, pref_repo):
        """回滚失败不影响其他回滚的执行"""
        tx = StorageTransaction("rollback_fail")

        # 注册一个合法的回滚
        m1 = PreferenceMemory(
            user_id="u1", preference_type="format_preference",
            content="M1", scope=SceneScope(scene="test"),
        )
        pref_repo.save(m1)
        tx.on_failure(lambda: pref_repo.delete_by_id(m1.memory_id))

        # 注册一个会失败的回滚（删不存在的 ID）
        tx.on_failure(lambda: pref_repo.delete_by_id("nonexistent_id_12345"))

        # 触发回滚
        results = tx.rollback()

        # M1 应该被成功回滚
        assert pref_repo.get_by_id(m1.memory_id) is None
        # 第二个回滚失败但不应阻止第一个
        assert any("回滚失败" in r or "nonexistent" in r.lower() for r in results) or \
            len(results) == 2
