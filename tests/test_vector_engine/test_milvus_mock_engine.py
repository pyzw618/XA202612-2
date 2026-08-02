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

DIM = 768


def _one_hot(position: int) -> list[float]:
    vec = [0.0] * DIM
    vec[position] = 1.0
    return vec


@pytest.fixture()
def engine():
    eng = create_vector_engine(
        provider="milvus_mock",
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
            provider="milvus_mock", collection="ctx_test", dimension=DIM
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
