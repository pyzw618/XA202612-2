from __future__ import annotations

from types import SimpleNamespace

from memoryhub.adapter.schemas import KnowledgeMemory, KnowledgeType, SceneScope
from memoryhub.adapter.simulator import OSAgentSimulator
from memoryhub.config import AppConfig, ExtractionRetryConfig, KnowledgeMergeConfig, RuntimeConfig
from memoryhub.core.conflict.detector import ConflictDetector
from memoryhub.core.ingestion.retry import ExtractionRetryRunResult
from memoryhub.core.ingestion.retry_task import ExtractionRetryTask
from memoryhub.core.knowledge.updater import KnowledgeUpdater
from memoryhub.storage.compensation_task import PendingIndexCompensationTask
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.app import create_app


class _RetryService:
    def run_due(self, *, limit: int):
        assert limit == 7
        return ExtractionRetryRunResult(claimed=2, succeeded=1, retried=1)


def test_extraction_retry_task_collects_metrics_without_changing_api() -> None:
    task = ExtractionRetryTask(_RetryService(), enabled=False, batch_size=7)
    result = task.run_once()
    metrics = task.metrics
    assert result.claimed == 2
    assert metrics.total_runs == 1
    assert metrics.total_claimed == 2
    assert metrics.total_succeeded == 1
    assert metrics.total_retried == 1
    assert metrics.last_error_code == ""


class _Engine:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.ids: set[str] = set()

    def upsert(self, memory_id, text, vector, metadata=None):
        if self.fail:
            raise RuntimeError("unavailable")
        self.ids.add(memory_id)

    def delete(self, memory_id):
        if self.fail:
            raise RuntimeError("unavailable")
        self.ids.discard(memory_id)


class _Embedding:
    def embed(self, text):
        return [0.1, 0.2]


def test_fact_projection_failure_remains_pending_and_is_compensated(tmp_path) -> None:
    from memoryhub.storage.sync_service import MemorySyncService

    db = Database(str(tmp_path / "facts-pending.db"))
    db.init_schema()
    know_repo = KnowledgeRepository(db)
    fact = KnowledgeMemory(
        memory_id="fact_pending",
        user_id="u1",
        knowledge_type=KnowledgeType.FACT,
        subject="subject",
        predicate="predicate",
        object_value="value",
        content="subject predicate value",
        confidence=0.9,
    )
    know_repo.save(fact)
    engine = _Engine(fail=True)
    service = MemorySyncService(
        pref_repo=PreferenceRepository(db),
        know_repo=know_repo,
        embedding_client=_Embedding(),
        vector_engine=engine,
    )
    failed = service.sync_pending()
    assert failed.failed == [fact.memory_id]
    assert [m.memory_id for m in know_repo.list_pending()] == [fact.memory_id]

    engine.fail = False
    repaired = service.sync_pending()
    assert repaired.succeeded == [fact.memory_id]
    assert know_repo.list_pending() == []
    assert fact.memory_id in engine.ids
    db.close()


class _ProjectionSync:
    def sync_pending(self):
        return SimpleNamespace(succeeded=["memory_ok"], failed=["fact_failed"])


def test_compensation_metrics_include_failed_projection_syncs() -> None:
    task = PendingIndexCompensationTask(_ProjectionSync(), enabled=False)
    task.run_once()
    metrics = task.metrics
    assert metrics.total_runs == 1
    assert metrics.total_succeeded == 1
    assert metrics.total_failed == 1
    assert "fact_failed" in metrics.last_error
    assert metrics.last_run_at > 0
    assert metrics.last_duration_ms >= 0


class _KnowledgeRepo:
    def __init__(self, old: KnowledgeMemory) -> None:
        self.items = {old.memory_id: old}

    def get_by_id(self, memory_id):
        return self.items.get(memory_id)

    def list_all(self, status="active", user_id=""):
        return [item for item in self.items.values() if item.user_id == user_id]


class _Writer:
    def __init__(self, repo) -> None:
        self.know_repo = repo

    def upsert_memory(self, memory, *, action=None, **_kwargs):
        self.know_repo.items[memory.memory_id] = memory


class _ConflictRepo:
    def __init__(self) -> None:
        self.records = []

    def save(self, record):
        self.records.append(record)


def test_knowledge_ambiguous_similarity_creates_owner_scoped_conflict() -> None:
    old = KnowledgeMemory(
        memory_id="know_old",
        user_id="u1",
        name="Deploy service",
        content="Deploy staging then production",
        steps=["deploy staging", "verify", "deploy production"],
        scope=SceneScope(scene="ops", task_type="deploy"),
    )
    incoming = KnowledgeMemory(
        memory_id="know_new",
        user_id="u1",
        name="Deploy service",
        content="Deploy directly to production",
        steps=["deploy production", "verify"],
        scope=SceneScope(scene="ops", task_type="deploy"),
    )
    repo = _KnowledgeRepo(old)
    conflicts = _ConflictRepo()
    updater = KnowledgeUpdater(
        write_service=_Writer(repo),
        merge_config=KnowledgeMergeConfig(
            equivalent_threshold=0.95,
            conflict_threshold=0.2,
        ),
        conflict_repo=conflicts,
    )
    assert updater.add(incoming) == "know_new"
    assert conflicts.records
    assert conflicts.records[0].user_id == "u1"
    assert conflicts.records[0].conflict_field == "semantic_equivalence"


def test_conflict_detector_is_owner_and_scope_isolated() -> None:
    detector = ConflictDetector(similarity_threshold=0.2)
    left = SimpleNamespace(scene="code", task_type="format", app="")
    right = SimpleNamespace(scene="office", task_type="report", app="")
    assert detector._is_same_scope(left, right) is False
    assert detector._semantic_contradiction("always use markdown", "do not use markdown") is True


def test_simulator_emits_complete_ordered_trajectory() -> None:
    events = OSAgentSimulator(user_id="u1").simulate_task("prepare report")
    assert [event.turn_id for event in events] == ["1", "2", "3"]
    assert len({event.session_id for event in events}) == 1
    assert events[-1].event_type == "task_completed"
    assert events[-1].payload["success"] is True


def test_application_uses_lifespan_instead_of_deprecated_on_event() -> None:
    config = AppConfig(
        runtime=RuntimeConfig(mode="test", allow_fallback=True),
        extraction_retry=ExtractionRetryConfig(enabled=False),
    )
    app = create_app(config)
    assert app.router.lifespan_context is not None
    assert app.router.on_startup == []
    assert app.router.on_shutdown == []
