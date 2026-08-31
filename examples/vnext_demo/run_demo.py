"""Fixed, redacted and replayable MemoryHub vNext acceptance demo.

Each scenario creates an isolated SQLite database, exercises the real vNext
services, and writes only a redacted ``<scenario>.json`` artifact. ``all``
replays all six scenarios in a deterministic order and also writes ``all.json``.

The default output is outside the repository. Use ``--output-dir`` to select
an explicit artifact directory; the demo database is always created there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryhub.adapter.vnext_api import router as vnext_router
from memoryhub.adapter.vnext_schemas import ConsistencyMode, MemoryRetrievalRequest
from memoryhub.application.canonical_write import CanonicalWriteService
from memoryhub.application.episode_service import EpisodeService
from memoryhub.application.event_gateway import EventGateway
from memoryhub.application.forget_service import ForgetService
from memoryhub.application.formation_worker import FormationWorker
from memoryhub.application.reflection_service import (
    DeterministicReflectionModel,
    ReflectionService,
)
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.application.rollout_service import RolloutController
from memoryhub.application.shadow_read_service import RolloutReadService, ShadowReadService
from memoryhub.application.working_service import WorkingService
from memoryhub.config import VNextConfig
from memoryhub.core.ingestion.retry import ExtractionRetryService
from memoryhub.core.memory_write import MemoryWriteService
from memoryhub.domain.contracts import (
    EpisodeEventContract,
    EpisodeSnapshot,
    EpisodeStatus,
    EvolutionStatus,
    LongTermEnvelope,
    MemoryEventContract,
    MemoryScope,
    MemoryType,
    WorkingSnapshot,
)
from memoryhub.domain.long_term import LongTermAuthorityFacade
from memoryhub.observability.audit_store import AuditStore
from memoryhub.observability.trace_store import TraceStore
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import (
    Database,
    EventRepository,
    ExtractionTaskRepository,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.models import MemoryEvidenceRow
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
    CandidateRepository,
    EpisodeRepository,
    RetrievalLogRepository,
    WorkingStateRepository,
)

DEMO_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = Path(gettempdir()) / "memoryhub-vnext-demo"
TENANT_ID = "tenant-demo"
USER_ID = "user-demo"
SCENARIOS = ("formation", "evidence", "scope", "retrieval", "resume", "forget")
FIXED_TIME = datetime(2026, 8, 25, tzinfo=timezone.utc)


@dataclass
class DemoRuntime:
    db: Database
    authority: AuthorityRepository
    canonical: CanonicalWriteService
    tasks: ExtractionTaskRepository
    retry: ExtractionRetryService
    client: TestClient

    def close(self) -> None:
        self.client.close()
        self.db.close()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_fixture(name: str) -> dict[str, Any]:
    with (DEMO_DIR / name).open("r", encoding="utf-8") as handle:
        return json.load(handle)[0]


def _clean_db_path(path: Path) -> None:
    """Remove only the demo database files owned by this run."""
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def _event(raw: dict[str, Any], *, task_id: str | None = None) -> MemoryEventContract:
    task_id = task_id or f"task-{raw['session_id']}"
    payload = dict(raw["payload"])
    if raw["event_type"] == "user_goal":
        payload["_working_snapshot"] = WorkingSnapshot(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            task_id=task_id,
            session_id=raw["session_id"],
            current_goal=payload.get("goal", "complete task"),
            current_step="outline",
            pending_steps=["draft", "review"],
            constraints=payload.get("constraints", []),
        ).model_dump(mode="json")
    event_id = f"event-{raw['session_id']}-{raw['turn_id']}"
    return MemoryEventContract(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        event_id=event_id,
        event_type=raw["event_type"],
        source_type="user_behavior",
        task_id=task_id,
        session_id=raw["session_id"],
        occurred_at=FIXED_TIME,
        payload=payload,
        policy_action="ALLOW",
        source_hash=_stable_hash({"event_id": event_id, "payload": payload}),
        idempotency_key=f"idem-{raw['session_id']}-{raw['turn_id']}",
        trace_id=f"trace-{raw['session_id']}",
    )


def _make_runtime(
    output_dir: Path, *, formation_mode: str = "candidate-only", reset_db: bool = True
) -> DemoRuntime:
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "demo.db"
    if reset_db:
        _clean_db_path(db_path)
    db = Database(str(db_path))
    db.init_schema()
    pref_repo = PreferenceRepository(db)
    know_repo = KnowledgeRepository(db)
    authority = AuthorityRepository(
        db, preference_repository=pref_repo, knowledge_repository=know_repo
    )
    facade = LongTermAuthorityFacade(authority)
    writer = MemoryWriteService(
        pref_repo=pref_repo, know_repo=know_repo, project_immediately=False
    )
    tasks = ExtractionTaskRepository(db)
    canonical = CanonicalWriteService(
        db,
        event_gateway=EventGateway(db, policy=lambda event: event),
        working_service=WorkingService(WorkingStateRepository(db)),
        episode_service=EpisodeService(EpisodeRepository(db)),
        extraction_tasks=tasks,
        authority_facade=facade,
        memory_write_service=writer,
        formation_mode=formation_mode,
    )
    worker = FormationWorker(
        db,
        task_repository=tasks,
        event_repository=EventRepository(db),
        canonical_write_service=canonical,
        mode=formation_mode,
        reflection_service=ReflectionService(model=DeterministicReflectionModel()),
    )
    retry = ExtractionRetryService(
        task_repo=tasks,
        event_repo=EventRepository(db),
        executor=object(),
        vnext_executor=worker,
    )

    trace_store = TraceStore(db=db)
    audit_store = AuditStore(db)

    def active_memories(
        request: MemoryRetrievalRequest, _plan: Any, channel: str
    ) -> list[Any]:
        from memoryhub.adapter.vnext_schemas import RetrievedMemory

        values = authority.list(
            tenant_id=request.tenant_id, user_id=request.user_id, include_inactive=False
        )
        return [
            RetrievedMemory(
                tenant_id=value.tenant_id,
                user_id=value.user_id,
                memory_id=value.memory_id,
                memory_type=value.memory_type,
                layer=value.layer,
                scope_level=value.scope_level,
                scope=value.scope,
                content_version=value.content_version,
                projection_version=value.projection_version,
                evolution_status=value.evolution_status.value,
                content={**value.content, "normalized_key": value.normalized_key},
                score=0.9,
                score_breakdown={"channel": channel, "authority": True},
                source_ids=[channel],
            )
            for value in values
        ]

    channels = {name: active_memories for name in ("vector", "keyword", "metadata", "authority")}
    retrieval = RetrievalService(
        channel_executors=channels,
        activation_repository=ActivationRepository(db),
        retrieval_log_repository=RetrievalLogRepository(db),
        trace_store=trace_store,
        authority_repository=authority,
        db=db,
    )
    rollout = RolloutController(VNextConfig(mode="vnext"), db=db)
    app = FastAPI()
    app.state.canonical_write_service = canonical
    app.state.episode_service = canonical.episode_service
    app.state.extraction_task_repo = tasks
    app.state.retrieval_service = retrieval
    app.state.forget_service = ForgetService(
        db, authority, trace_store=trace_store, audit_store=audit_store
    )
    app.state.rollout_controller = rollout
    app.state.rollout_read_service = RolloutReadService(
        controller=rollout,
        shadow_read=ShadowReadService(
            trace_store=trace_store,
            reflection_service=ReflectionService(model=DeterministicReflectionModel()),
        ),
    )
    app.state.user_rule_identity_resolver = None
    app.include_router(vnext_router)
    return DemoRuntime(db, authority, canonical, tasks, retry, TestClient(app))


def _write(runtime: DemoRuntime, event: MemoryEventContract) -> Any:
    payload = dict(event.payload)
    working_raw = payload.pop("_working_snapshot", None)
    episode_event_raw = payload.pop("_episode_event", None)
    episode_snapshot_raw = payload.pop("_episode_snapshot", None)
    checkpoint_raw = payload.pop("_checkpoint", None)
    working = WorkingSnapshot.model_validate(working_raw) if working_raw else None
    episode_event = (
        EpisodeEventContract.model_validate(episode_event_raw) if episode_event_raw else None
    )
    episode_snapshot = (
        EpisodeSnapshot.model_validate(episode_snapshot_raw) if episode_snapshot_raw else None
    )
    checkpoint = EpisodeSnapshot.model_validate(checkpoint_raw) if checkpoint_raw else None
    clean_event = event.model_copy(update={"payload": payload})
    return runtime.canonical.write(
        clean_event,
        working_snapshot=working,
        working_state_id=working.task_id if working else None,
        episode_event=episode_event,
        episode_snapshot=episode_snapshot,
        checkpoint=checkpoint,
    )


def _run_task(runtime: DemoRuntime, result: Any) -> Any:
    if result.reflection_task is None:
        raise RuntimeError("demo event did not enqueue Formation work")
    runtime.retry.run_due(user_id=USER_ID)
    task = runtime.tasks.get(result.reflection_task.task_id, user_id=USER_ID)
    if task is None:
        raise RuntimeError("demo Formation task disappeared")
    return task


def _envelope(
    memory_id: str,
    *,
    scope_level: MemoryScope = MemoryScope.GLOBAL,
    scope: str = "GLOBAL",
    normalized_key: str = "report.format",
    value: str = "DOCX",
) -> LongTermEnvelope:
    return LongTermEnvelope(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        memory_id=memory_id,
        memory_type=MemoryType.PREFERENCE,
        normalized_key=normalized_key,
        content={"text": value, "format": value},
        scope_level=scope_level,
        scope=scope,
        evolution_status=EvolutionStatus.ACTIVE,
        confidence=0.95,
        utility=0.8,
        evidence_refs=[f"evidence:{memory_id}"],
    )


def _search(runtime: DemoRuntime, request_id: str, **overrides: Any) -> dict[str, Any]:
    payload = {
        "api_version": "vnext/v1",
        "request_id": request_id,
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "query": "report format",
        "intent_hint": "PREFERENCE",
        "consistency": ConsistencyMode.AUTHORITY_CHECKED.value,
        "token_budget": 384,
        "page_size": 5,
        **overrides,
    }
    response = runtime.client.post(
        "/api/memory/vnext/search",
        json=payload,
        headers={"X-MemoryHub-Tenant": TENANT_ID, "X-MemoryHub-User": USER_ID},
    )
    if response.status_code != 200:
        raise RuntimeError(f"search failed: {response.status_code} {response.text}")
    return response.json()


def scenario_formation(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir, formation_mode="candidate-only")
    try:
        result = _write(runtime, _event(_load_fixture("event_start_report.json")))
        task = _run_task(runtime, result)
        working = WorkingStateRepository(runtime.db).get(
            tenant_id=TENANT_ID, user_id=USER_ID, task_id="task-demo_session_001"
        )
        candidate = CandidateRepository(runtime.db).get(
            tenant_id=TENANT_ID, user_id=USER_ID, candidate_id=task.candidate_ids[0]
        )
        if working is None or candidate is None:
            raise RuntimeError("formation state was not persisted")
        return {
            "scenario": "formation",
            "redacted": True,
            "formation": {
                "event_count": 1,
                "working_state_version": working.version,
                "goal_hash": _stable_hash(working.state.get("current_goal")),
                "candidate_count": len(task.candidate_ids),
                "candidate_status": candidate.status,
                "authority_memory_count": 0,
                "task_status": task.status.value,
            },
        }
    finally:
        runtime.close()


def scenario_evidence(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir, formation_mode="authority")
    try:
        first_raw = _load_fixture("event_use_docx.json")
        second_raw = {
            **first_raw,
            "session_id": "demo_evidence_session_002",
            "turn_id": "turn_001",
            "payload": dict(first_raw["payload"]),
        }
        results = [
            _write(runtime, _event(first_raw, task_id="task-evidence-1")),
            _write(
                runtime,
                _event(second_raw, task_id="task-evidence-2"),
            ),
        ]
        tasks = [_run_task(runtime, item) for item in results]
        candidate_rows = CandidateRepository(runtime.db).search(
            tenant_id=TENANT_ID, user_id=USER_ID, include_candidates=True
        )
        candidate = candidate_rows[0] if candidate_rows else None
        memories = runtime.authority.list(tenant_id=TENANT_ID, user_id=USER_ID)
        evidence_count = 0
        if memories:
            with runtime.db.session() as session:
                evidence_count = session.query(MemoryEvidenceRow).filter(
                    MemoryEvidenceRow.memory_id == memories[0].memory_id
                ).count()
        if candidate is None or len(memories) != 1 or candidate.status != "CONFIRMED":
            raise RuntimeError("independent evidence did not promote the candidate")
        return {
            "scenario": "evidence",
            "redacted": True,
            "evidence_consolidation": {
                "independent_task_count": len(tasks),
                "candidate_frequency": candidate.frequency,
                "evidence_ref_count": len(candidate.evidence_refs),
                "persisted_evidence_count": evidence_count,
                "candidate_status": candidate.status,
                "promoted_memory_count": len(memories),
                "memory_ids": [item.memory_id for item in memories],
                "task_statuses": [item.status.value for item in tasks],
            },
        }
    finally:
        runtime.close()


def scenario_scope(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir)
    try:
        runtime.authority.save(_envelope("memory-scope-global"))
        runtime.authority.save(
            _envelope(
                "memory-scope-project",
                scope_level=MemoryScope.PROJECT,
                scope="PROJECT:project-a",
            )
        )
        body = _search(
            runtime,
            "req-demo-scope",
            scope_level=MemoryScope.PROJECT.value,
            scope="PROJECT:project-a",
        )
        selected = body["selected_memories"]
        if [item["memory_id"] for item in selected] != ["memory-scope-project"]:
            raise RuntimeError("project scope did not override the global value")
        return {
            "scenario": "scope",
            "redacted": True,
            "scope_resolution": {
                "coexisting_memory_count": 2,
                "preferred_scope": "PROJECT:project-a",
                "selected_memory_ids": [item["memory_id"] for item in selected],
                "selected_scope_levels": [item["scope_level"] for item in selected],
            },
        }
    finally:
        runtime.close()


def scenario_retrieval(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir)
    try:
        runtime.authority.save(_envelope("memory-retrieval-demo"))
        body = _search(runtime, "req-demo-retrieval", token_budget=384)
        plan = body["retrieval_plan"]
        selected = body["selected_memories"]
        explanation = {
            "intent": body["intent"],
            "channels": plan["enabled_channels"],
            "authority_checked": plan["authority_checked"],
            "scope": {"level": "GLOBAL", "value": "GLOBAL"},
            "budget": {
                "requested_tokens": 384,
                "selected_tokens": body["context"]["selected_tokens"],
                "dropped_count": len(body["context"]["dropped_reasons"]),
            },
            "selected_memory_ids": [item["memory_id"] for item in selected],
        }
        if not explanation["channels"] or explanation["intent"] != "PREFERENCE":
            raise RuntimeError("retrieval explanation is incomplete")
        return {"scenario": "retrieval", "redacted": True, "retrieval_explanation": explanation}
    finally:
        runtime.close()


def scenario_resume(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir)
    task_id = "task-resume-demo"
    episode_id = "episode-resume-demo"
    try:
        working = WorkingSnapshot(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            task_id=task_id,
            session_id="resume-session-1",
            current_goal="resume the report task",
            current_step="draft",
            pending_steps=["review", "publish"],
            constraints=["formal tone", "include metrics"],
        )
        episode = EpisodeSnapshot(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            episode_id=episode_id,
            task_id=task_id,
            session_id="resume-session-1",
            status=EpisodeStatus.ACTIVE,
            current_phase="draft",
            goal="resume the report task",
            pending_steps=["review", "publish"],
            constraints=["formal tone", "include metrics"],
            last_event_seq=1,
        )
        episode_event = EpisodeEventContract(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            episode_id=episode_id,
            task_id=task_id,
            seq_no=1,
            event_type="TASK_SUSPENDED",
            payload={"phase": "draft"},
            source_event_id="event-resume-demo",
        )
        raw = {
            "event_type": "task_checkpoint",
            "session_id": "resume-session-1",
            "turn_id": "turn-001",
            "payload": {
                "text": "checkpoint payload",
                "_working_snapshot": working.model_dump(mode="json"),
                "_episode_event": episode_event.model_dump(mode="json"),
                "_episode_snapshot": episode.model_dump(mode="json"),
            },
        }
        result = _write(runtime, _event(raw, task_id=task_id))
        if result.episode_snapshot is None:
            raise RuntimeError("resume checkpoint was not persisted")
        resume_token = result.episode_snapshot.resume_token
    finally:
        runtime.close()

    restarted = _make_runtime(output_dir, formation_mode="candidate-only", reset_db=False)
    try:
        response = restarted.client.get(
            f"/api/memory/vnext/tasks/{task_id}/resume",
            headers={
                "X-MemoryHub-Tenant": TENANT_ID,
                "X-MemoryHub-User": USER_ID,
                "X-MemoryHub-Resume-Token": resume_token,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"resume failed after restart: {response.status_code} {response.text}"
            )
        body = response.json()
        restored = body["restored_state"]
        return {
            "scenario": "resume",
            "redacted": True,
            "resume": {
                "restart_verified": True,
                "goal_restored": bool(restored.get("goal")),
                "goal_hash": _stable_hash(restored.get("goal")),
                "constraints_restored": bool(restored.get("constraints")),
                "constraints_hash": _stable_hash(restored.get("constraints")),
                "pending_steps_restored": bool(restored.get("pending_steps")),
                "pending_steps_hash": _stable_hash(restored.get("pending_steps")),
                "required_revalidation_count": len(body["required_revalidation"]),
            },
        }
    finally:
        restarted.close()


def scenario_forget(output_dir: Path) -> dict[str, Any]:
    runtime = _make_runtime(output_dir)
    try:
        memory_id = "memory-forget-demo"
        runtime.authority.save(_envelope(memory_id))
        before = _search(runtime, "req-demo-forget-before")
        forget_payload = {
            "api_version": "vnext/v1",
            "request_id": "req-demo-forget",
            "idempotency_key": "idem-demo-forget",
            "tenant_id": TENANT_ID,
            "user_id": USER_ID,
            "target_memory_ids": [memory_id],
            "dry_run": False,
            "confirm": True,
        }
        forget_response = runtime.client.post(
            "/api/memory/vnext/forget",
            json=forget_payload,
            headers={"X-MemoryHub-Tenant": TENANT_ID, "X-MemoryHub-User": USER_ID},
        )
        if forget_response.status_code != 200:
            raise RuntimeError(
                f"forget failed: {forget_response.status_code} {forget_response.text}"
            )
        after = _search(runtime, "req-demo-forget-after")
        residual = after["total_count"]
        if before["total_count"] == 0 or residual != 0:
            raise RuntimeError("Forget residual retrieval is not zero")
        body = forget_response.json()
        return {
            "scenario": "forget",
            "redacted": True,
            "forget": {
                "before_count": before["total_count"],
                "authority_status": body["authority_status"],
                "projection_status": body["projection_status"],
                "verification_status": body["verification_status"],
                "residual_retrieval_count": residual,
                "affected_memory_count": len(body["affected_memory_ids"]),
            },
        }
    finally:
        runtime.close()


SCENARIO_RUNNERS: dict[str, Callable[[Path], dict[str, Any]]] = {
    "formation": scenario_formation,
    "evidence": scenario_evidence,
    "scope": scenario_scope,
    "retrieval": scenario_retrieval,
    "resume": scenario_resume,
    "forget": scenario_forget,
}


def _write_artifact(output_dir: Path, name: str, body: dict[str, Any]) -> Path:
    path = output_dir / f"{name}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the vNext acceptance scenarios.")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _clean_db_path(output_dir / "demo.db")

    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    artifacts: dict[str, str] = {}
    for name in names:
        body = SCENARIO_RUNNERS[name](output_dir)
        artifacts[name] = _write_artifact(output_dir, name, body).name
    if args.scenario == "all":
        _write_artifact(
            output_dir,
            "all",
            {
                "scenario": "all",
                "redacted": True,
                "covered_scenarios": names,
                "artifacts": artifacts,
            },
        )
    print(f"vNext demo artifacts written to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
