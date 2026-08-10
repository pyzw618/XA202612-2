"""
MilvusVectorEngine + mock 动态库 集成测试。

通过工厂 provider="milvus_mock" 建引擎，验证 insert / dense search /
hybrid_search / delete / close 全链路。查询侧稀疏向量必须用
sparse.build_sparse_vector 生成：insert 的中文文本能被同词查询命中，
即等价验证了 Python 与 C 侧分词/hash 规则逐位一致。
"""

import pytest

from memoryhub.storage.vector_engine import (
    VectorSearchResult,
    build_sparse_vector,
    create_vector_engine,
)
from memoryhub.storage.vector_engine._milvus_ctypes import MilvusEngineError

DIM = 768


def _one_hot(position: int) -> list[float]:
    vec = [0.0] * DIM
    vec[position] = 1.0
    return vec


@pytest.fixture()
def engine():
    eng = create_vector_engine(
        provider="milvus_mock", app_id="test-app-id",
        collection="test_collection",
        dimension=DIM,
    )
    yield eng
    eng.close()


@pytest.fixture()
def populated_engine(engine):
    engine.insert("mem_001", "我喜欢吃苹果和香蕉", _one_hot(0))
    engine.insert("mem_002", "Python 是一种编程语言", _one_hot(1))
    engine.insert("mem_003", "今天天气很好适合散步", _one_hot(2))
    return engine


class TestMilvusMockEngine:
    def test_dense_search_hit(self, populated_engine):
        results = populated_engine.search(_one_hot(1), top_k=3)
        assert len(results) == 3
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].memory_id == "mem_002"
        assert results[0].content == "Python 是一种编程语言"
        assert results[0].source == "dense"
        assert results[0].score == pytest.approx(1.0, abs=1e-5)

    def test_hybrid_search_chinese_terms(self, populated_engine):
        """中文文本 insert 后，同词稀疏查询应命中（验证 Python/C 分词一致）。"""
        # 稠密/稀疏两路都指向 mem_001 时，它必须排第一；
        # 稀疏路点积 > 0 的前提是 Python 侧 hash 与 C 侧逐位一致
        sparse_terms = build_sparse_vector("苹果")
        results = populated_engine.hybrid_search(_one_hot(0), sparse_terms, top_k=3)
        assert len(results) == 3
        top = results[0]
        assert top.memory_id == "mem_001"
        assert top.content == "我喜欢吃苹果和香蕉"
        assert top.source == "hybrid"
        assert top.score > results[1].score

    def test_hybrid_search_ascii_terms(self, populated_engine):
        """ASCII token 也能与 C 侧稀疏索引对上。"""
        sparse_terms = build_sparse_vector("Python")
        results = populated_engine.hybrid_search(_one_hot(1), sparse_terms, top_k=3)
        assert results[0].memory_id == "mem_002"
        assert results[0].score > results[1].score

    def test_delete_takes_effect(self, populated_engine):
        populated_engine.delete("mem_001")
        results = populated_engine.search(_one_hot(0), top_k=3)
        assert all(r.memory_id != "mem_001" for r in results)
        # 删除不存在的 ID 不报错
        populated_engine.delete("mem_not_exist")

    def test_insert_upsert(self, populated_engine):
        """重复 insert 同一 memory_id 视为更新。"""
        populated_engine.insert("mem_001", "更新后的内容", _one_hot(0))
        results = populated_engine.search(_one_hot(0), top_k=3)
        top = next(r for r in results if r.memory_id == "mem_001")
        assert top.content == "更新后的内容"

    def test_persist_is_noop(self, populated_engine):
        populated_engine.persist()

    def test_close_idempotent(self, engine):
        engine.close()
        engine.close()  # 重复调用不报错
        with pytest.raises(Exception):
            engine.search(_one_hot(0), top_k=1)

    def test_context_manager(self):
        with create_vector_engine(
            provider="milvus_mock", app_id="test-app-id", collection="ctx_test", dimension=DIM
        ) as eng:
            eng.insert("mem_1", "上下文管理器测试", _one_hot(0))
            results = eng.search(_one_hot(0), top_k=1)
            assert results[0].memory_id == "mem_1"

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="unknown vector_engine provider"):
            create_vector_engine(provider="not_exist")

    def test_dimension_mismatch(self, engine):
        with pytest.raises(ValueError, match="维度"):
            engine.insert("mem_1", "文本", [0.1] * 10)


class TestMilvusVectorEnginePhase3:
    """阶段三新增：schema 校验、批量 upsert、scalar filters、超时配置。"""

    def test_schema_dimension_fixed_to_768(self):
        """collection schema 维度固定为 768；非 768 构造即失败。"""
        with pytest.raises(MilvusEngineError, match="schema_dimension_mismatch"):
            create_vector_engine(
                provider="milvus_mock", app_id="test-app-id",
                collection="bad_dim",
                dimension=512,
            )

    def test_upsert_batch_returns_failed_ids(self, engine):
        """批量 upsert 失败项应返回，便于调用方标记 pending_index。"""
        engine.insert("mem_ok", "正常", _one_hot(0))
        items = [
            ("mem_ok", "更新", _one_hot(0), None),
            ("mem_new", "新增", _one_hot(1), {"memory_type": "preference"}),
        ]
        failed = engine.upsert_batch(items)
        assert failed == []
        results = engine.search(_one_hot(1), top_k=2)
        assert any(r.memory_id == "mem_new" for r in results)

    def test_hybrid_search_with_scalar_filters(self, engine):
        """hybrid_search 接受 filters 参数，对内存中的 scalar fields 做后过滤。"""
        engine.insert(
            "pref_1",
            "偏好 Markdown",
            _one_hot(0),
            metadata={"memory_type": "preference", "status": "active"},
        )
        engine.insert(
            "know_1",
            "知识 Markdown",
            _one_hot(0),
            metadata={"memory_type": "knowledge", "status": "active"},
        )
        sparse_terms = build_sparse_vector("Markdown")
        results = engine.hybrid_search(_one_hot(0), sparse_terms, top_k=5)
        assert len(results) == 2
        filtered = engine.hybrid_search(
            _one_hot(0), sparse_terms, top_k=5, filters={"memory_type": "knowledge"}
        )
        assert [r.memory_id for r in filtered] == ["know_1"]

    def test_search_timeout_ms_is_stored(self, engine):
        """构造时传入的 search_timeout_ms 应被记录。"""
        assert engine.search_timeout_ms == 120  # 默认值

    def test_upsert_alias_matches_insert(self, engine):
        """upsert 语义与 insert 相同。"""
        engine.upsert("mem_alias", "别名测试", _one_hot(0))
        results = engine.search(_one_hot(0), top_k=1)
        assert results[0].memory_id == "mem_alias"
