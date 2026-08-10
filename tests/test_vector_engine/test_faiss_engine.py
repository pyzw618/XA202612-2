"""
FAISSVectorEngine 单元测试。

验证对现有 VectorStore 的包装：insert / search / hybrid_search /
delete / persist / close 基本链路。
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
def engine(tmp_path):
    eng = create_vector_engine(
        provider="faiss",
        index_path=str(tmp_path / "vector_index"),
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


class TestFAISSVectorEngine:
    def test_search_hit(self, populated_engine):
        results = populated_engine.search(_one_hot(1), top_k=3)
        assert len(results) == 3
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].memory_id == "mem_002"
        assert results[0].content == "Python 是一种编程语言"
        assert results[0].source == "dense"
        assert results[0].score == pytest.approx(1.0, abs=1e-5)

    def test_hybrid_search_sparse_route(self, populated_engine):
        """稠密/稀疏两路都指向同一记录时，RRF 融合后它必须排第一。"""
        sparse_terms = build_sparse_vector("苹果")
        results = populated_engine.hybrid_search(_one_hot(0), sparse_terms, top_k=3)
        assert len(results) == 3
        assert all(r.source == "hybrid" for r in results)
        assert results[0].memory_id == "mem_001"
        assert results[0].score > results[1].score

    def test_delete_takes_effect(self, populated_engine):
        populated_engine.delete("mem_001")
        results = populated_engine.search(_one_hot(0), top_k=3)
        assert all(r.memory_id != "mem_001" for r in results)
        populated_engine.delete("mem_not_exist")  # 不报错

    def test_persist_and_reload(self, tmp_path):
        index_path = str(tmp_path / "vector_index")
        eng = create_vector_engine("faiss", index_path=index_path, dimension=DIM)
        eng.insert("mem_001", "持久化测试文本", _one_hot(0))
        eng.persist()
        eng.close()

        eng2 = create_vector_engine("faiss", index_path=index_path, dimension=DIM)
        results = eng2.search(_one_hot(0), top_k=1)
        assert results[0].memory_id == "mem_001"
        # 文本映射也应随持久化恢复，hybrid_search 稀疏路仍可用
        hybrid = eng2.hybrid_search(_one_hot(1), build_sparse_vector("持久化"), top_k=1)
        assert hybrid[0].memory_id == "mem_001"
        assert hybrid[0].content == "持久化测试文本"
        eng2.close()

    def test_close_idempotent(self, engine):
        engine.close()
        engine.close()
        with pytest.raises(Exception):
            engine.search(_one_hot(0), top_k=1)

    def test_context_manager(self, tmp_path):
        with create_vector_engine(
            "faiss", index_path=str(tmp_path / "ctx_index"), dimension=DIM
        ) as eng:
            eng.insert("mem_1", "上下文管理器测试", _one_hot(0))
            assert eng.search(_one_hot(0), top_k=1)[0].memory_id == "mem_1"
