from __future__ import annotations

from memoryhub.core.fact.admission import FactAdmissionPolicy
from memoryhub.core.fact.conflict import ConflictDetector
from memoryhub.core.fact.models import PredicateDef, RawTriple
from memoryhub.core.fact.pipeline import FactMemoryPipeline
from memoryhub.core.fact.store import FactStore
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.models import MemoryProjectionOutboxRow
from memoryhub.storage.projection_outbox import ProjectionOutboxWorker


class _Extractor:
    last_error = None

    def extract(self, _text, _source_id=""):
        return [
            RawTriple(
                subject_text="Project A",
                subject_type="Other",
                predicate_text="owner",
                object_text="Alice",
                object_type="Person",
                evidence="Project A owner is Alice",
                confidence=0.95,
            )
        ]


class _Normalizer:
    def __init__(self, values):
        self.values = values

    def normalize(self, text, _entity_type=None):
        return self.values[text]


class _FactProjector:
    def __init__(self):
        self.calls = []

    def sync_fact(self, fact, *, remove=False):
        self.calls.append((fact.fact_id, remove))


def _pipeline(db_path: str) -> FactMemoryPipeline:
    pipeline = FactMemoryPipeline.__new__(FactMemoryPipeline)
    pipeline.store = FactStore(db_path)
    pipeline.store.upsert_predicate(
        PredicateDef(predicate_id="owner", canonical_name="owner", single_value=True)
    )
    pipeline.extractor = _Extractor()
    pipeline.entity_norm = _Normalizer(
        {"Project A": "entity:project:a", "Alice": "entity:person:alice"}
    )
    pipeline.pred_norm = _Normalizer({"owner": "owner"})
    pipeline.detector = ConflictDetector(pipeline.store)
    pipeline.admission = FactAdmissionPolicy()
    pipeline.index_service = None
    pipeline.safety_gate = None
    pipeline.project_immediately = False
    return pipeline


def test_fact_commit_enqueues_durable_projection_and_worker_projects_it(tmp_path):
    db_path = str(tmp_path / "memoryhub.db")
    db = Database(db_path)
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    pipeline = _pipeline(db_path)
    proposal = pipeline.propose("Project A owner is Alice", scope_hint="global")[0]

    result = pipeline.commit_unsafe_for_test(proposal, scope="global")

    with db.session() as session:
        row = (
            session.query(MemoryProjectionOutboxRow)
            .filter(
                MemoryProjectionOutboxRow.memory_id == result.new_fact.fact_id,
                MemoryProjectionOutboxRow.memory_type == "fact",
            )
            .one()
        )
        assert row.status == "pending"
        outbox_id = row.outbox_id

    fact_projector = _FactProjector()
    worker = ProjectionOutboxWorker(
        pref_repo=pref_repo,
        know_repo=know_repo,
        memory_write_service=object(),
        fact_store=pipeline.store,
        fact_index_service=fact_projector,
    )
    run = worker.run_once()

    assert run.succeeded == [outbox_id]
    assert fact_projector.calls == [(result.new_fact.fact_id, False)]
    with db.session() as session:
        row = session.get(MemoryProjectionOutboxRow, outbox_id)
        assert row.status == "completed"

    pipeline.close()
    db.close()
