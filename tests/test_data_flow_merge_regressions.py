from __future__ import annotations

from pathlib import Path

from memoryhub.adapter.schemas import (
    KnowledgeMemory,
    PreferenceMemory,
    SearchRequest,
    SearchResult,
)
from memoryhub.core.forget.forgetter import MemoryForgetter
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.retrieval.milvus_hybrid import MilvusHybridRetriever
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import KnowledgeRow, PreferenceRow
from memoryhub.storage.sync_service import MemorySyncService


class FakeEmbedding:
    def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeVectorEngine:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, str, dict]] = []
        self.upserted: list[tuple[str, str, dict]] = []
        self.deleted: list[str] = []

    def insert(self, memory_id, text, vector, metadata=None) -> None:
        self.inserted.append((memory_id, text, metadata or {}))

    def upsert(self, memory_id, text, vector, metadata=None) -> None:
        self.upserted.append((memory_id, text, metadata or {}))

    def delete(self, memory_id) -> None:
        self.deleted.append(memory_id)


class FakeVectorStore:
    def __init__(self) -> None:
        self.updated: list[str] = []
        self.deleted: list[str] = []
        self.save_count = 0

    def update(self, memory_id, vector) -> None:
        self.updated.append(memory_id)

    def delete(self, memory_id) -> None:
        self.deleted.append(memory_id)

    def save(self) -> None:
        self.save_count += 1


class FakeKeywordSearch:
    def __init__(self) -> None:
        self.updated: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []

    def update(self, memory_id, text, metadata) -> None:
        self.updated.append((memory_id, text, metadata))

    def delete(self, memory_id) -> None:
        self.deleted.append(memory_id)


def make_repositories(tmp_path: Path):
    db = Database(str(tmp_path / "merge-regressions.db"))
    db.init_schema()
    return db, PreferenceRepository(db), KnowledgeRepository(db)


def test_milvus_retriever_fails_closed_for_foreign_or_ownerless_results() -> None:
    retriever = MilvusHybridRetriever.__new__(MilvusHybridRetriever)
    retriever.memory_lookup = {}
    request = SearchRequest(user_id="u1", query="secret")
    results = [
        SearchResult(
            memory_id="foreign",
            memory_type="knowledge",
            metadata={"user_id": "u2", "status": "active"},
        ),
        SearchResult(
            memory_id="ownerless",
            memory_type="knowledge",
            metadata={"status": "active"},
        ),
        SearchResult(
            memory_id="owned",
            memory_type="knowledge",
            metadata={"user_id": "u1", "status": "active"},
        ),
        SearchResult(
            memory_id="archived",
            memory_type="knowledge",
            metadata={"user_id": "u1", "status": "archived"},
        ),
    ]
    assert [r.memory_id for r in retriever._filter_by_context(results, request)] == [
        "owned"
    ]


def test_milvus_retriever_preserves_shared_empty_lookup() -> None:
    lookup: dict = {}
    retriever = MilvusHybridRetriever(
        engine=FakeVectorEngine(),
        embedding_fn=lambda _text: [0.1, 0.2, 0.3],
        memory_lookup=lookup,
    )
    assert retriever.memory_lookup is lookup


def test_knowledge_forget_enforces_owner_and_cascades(tmp_path: Path) -> None:
    db, pref_repo, know_repo = make_repositories(tmp_path)
    engine = FakeVectorEngine()
    lookup = {}
    memory = KnowledgeMemory(
        memory_id="knowledge-owner",
        user_id="u2",
        name="Private workflow",
        content="secret",
    )
    know_repo.save(memory)
    lookup[memory.memory_id] = memory
    forgetter = MemoryForgetter(
        pref_repo=pref_repo,
        know_repo=know_repo,
        vector_engine=engine,
        memory_lookup=lookup,
    )

    assert forgetter.delete_memories([memory.memory_id], user_id="u1") == 0
    assert know_repo.get_by_id(memory.memory_id).status.value == "active"
    assert forgetter.delete_memories([memory.memory_id], user_id="u2") == 1
    assert know_repo.get_by_id(memory.memory_id).status.value == "deleted"
    assert engine.deleted == [memory.memory_id]
    assert memory.memory_id not in lookup
    with db.session() as session:
        row = session.query(KnowledgeRow).filter_by(memory_id=memory.memory_id).one()
        assert row.pending_index is False
    db.close()


def test_main_writer_marks_projection_synced_and_keeps_full_knowledge_text(
    tmp_path: Path,
) -> None:
    db, pref_repo, know_repo = make_repositories(tmp_path)
    engine = FakeVectorEngine()
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        vector_engine=engine,
        embedding_client=FakeEmbedding(),
        memory_lookup={},
    )
    memory = KnowledgeMemory(
        memory_id="full-text",
        user_id="u1",
        name="Workflow",
        content="Base",
        steps=["step-marker"],
        tools=["tool-marker"],
        template_body="template-marker",
    )
    writer.upsert_memory(memory)

    text = engine.inserted[0][1]
    metadata = engine.inserted[0][2]
    assert all(marker in text for marker in ("step-marker", "tool-marker", "template-marker"))
    assert metadata["user_id"] == "u1"
    assert metadata["status"] == "active"
    with db.session() as session:
        row = session.query(KnowledgeRow).filter_by(memory_id=memory.memory_id).one()
        assert row.pending_index is False
    db.close()


def test_pending_inactive_memory_is_deleted_instead_of_reupserted(tmp_path: Path) -> None:
    db, pref_repo, know_repo = make_repositories(tmp_path)
    memory = KnowledgeMemory(
        memory_id="archived-pending",
        user_id="u1",
        name="Old workflow",
        content="old",
    )
    know_repo.save(memory)
    assert know_repo.update_status(memory.memory_id, "archived", user_id="u1") is True
    engine = FakeVectorEngine()
    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        embedding_client=FakeEmbedding(),
        vector_engine=engine,
    )

    result = service.sync_pending()
    assert result.succeeded == [memory.memory_id]
    assert engine.deleted == [memory.memory_id]
    assert engine.upserted == []
    with db.session() as session:
        row = session.query(KnowledgeRow).filter_by(memory_id=memory.memory_id).one()
        assert row.pending_index is False
    db.close()


def test_explicit_write_uses_unified_dev_indexes_and_lookup(tmp_path: Path) -> None:
    db, pref_repo, know_repo = make_repositories(tmp_path)
    vector_store = FakeVectorStore()
    keyword = FakeKeywordSearch()
    lookup = {}
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        vector_store=vector_store,
        keyword_search=keyword,
        memory_lookup=lookup,
        embedding_client=FakeEmbedding(),
    )
    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        embedding_client=FakeEmbedding(),
        vector_engine=None,
        memory_write_service=writer,
    )
    memory = PreferenceMemory(
        memory_id="dev-explicit",
        user_id="u1",
        text="development explicit write",
    )

    assert service.index_memory(memory) == (True, memory.memory_id)
    assert vector_store.updated == [memory.memory_id]
    assert keyword.updated[0][0] == memory.memory_id
    assert lookup[memory.memory_id] is memory
    with db.session() as session:
        row = session.query(PreferenceRow).filter_by(memory_id=memory.memory_id).one()
        assert row.pending_index is False
    db.close()


def test_sync_delete_missing_or_foreign_memory_reports_failure(tmp_path: Path) -> None:
    db, pref_repo, know_repo = make_repositories(tmp_path)
    know_repo.save(
        KnowledgeMemory(
            memory_id="foreign-delete",
            user_id="u2",
            name="Foreign",
            content="secret",
        )
    )
    engine = FakeVectorEngine()
    service = MemorySyncService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        embedding_client=FakeEmbedding(),
        vector_engine=engine,
    )
    assert service.delete_memory("missing", user_id="u1") is False
    assert service.delete_memory("foreign-delete", user_id="u1") is False
    assert engine.deleted == []
    db.close()


def test_failed_inactive_delete_keeps_pending_tombstone_in_lookup(tmp_path: Path) -> None:
    class FailingDeleteEngine(FakeVectorEngine):
        def delete(self, memory_id) -> None:
            raise RuntimeError("vector unavailable")

    db, pref_repo, know_repo = make_repositories(tmp_path)
    active = KnowledgeMemory(
        memory_id="delete-tombstone",
        user_id="u1",
        name="Workflow",
        content="content",
    )
    know_repo.save(active)
    lookup = {active.memory_id: active}
    writer = MemoryWriteService(
        pref_repo=pref_repo,
        know_repo=know_repo,
        vector_engine=FailingDeleteEngine(),
        embedding_client=FakeEmbedding(),
        memory_lookup=lookup,
    )
    archived = active.model_copy(update={"status": "archived"})

    try:
        writer.upsert_memory(archived)
    except RuntimeError:
        pass
    else:
        raise AssertionError("delete failure must propagate for compensation")

    assert str(lookup[active.memory_id].status) == "archived"
    with db.session() as session:
        row = session.query(KnowledgeRow).filter_by(memory_id=active.memory_id).one()
        assert row.pending_index is True
    retriever = MilvusHybridRetriever.__new__(MilvusHybridRetriever)
    retriever.memory_lookup = lookup
    stale = SearchResult(
        memory_id=active.memory_id,
        memory_type="knowledge",
        metadata={"user_id": "u1", "status": "active"},
    )
    assert retriever._filter_by_context(
        [stale], SearchRequest(user_id="u1", query="workflow")
    ) == []
    db.close()
