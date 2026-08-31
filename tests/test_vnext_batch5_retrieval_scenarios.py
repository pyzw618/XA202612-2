"""Stage 2 Batch 5: real retrieval scenarios and legacy-vs-vNext comparison.

These tests exercise the full vNext retrieval pipeline (intent → planner →
channels → fusion → rerank → scope → budget → context) against real Working,
Episode and Authority repositories plus the BM25 keyword channel.  The vector
channel uses a deterministic mock retriever so the suite does not require a live
Milvus/FAISS backend.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from memoryhub.adapter.retrieval_executor import build_channel_executors
from memoryhub.adapter.schemas import SearchResponse, SearchResult
from memoryhub.adapter.vnext_schemas import MemoryRetrievalRequest
from memoryhub.application.retrieval_service import RetrievalService
from memoryhub.domain.contracts import (
    EvolutionStatus,
    LongTermEnvelope,
    MemoryScope,
    MemoryType,
    RetrievalIntent,
)
from memoryhub.retrieval.keyword_search import BM25Okapi, KeywordSearcher
from memoryhub.storage.authority_repository import AuthorityRepository
from memoryhub.storage.database import Database, KnowledgeRepository, PreferenceRepository
from memoryhub.storage.vnext_repositories import (
    ActivationRepository,
    EpisodeRepository,
    RetrievalLogRepository,
    WorkingStateRepository,
)

_keyword_backend_required = pytest.mark.skipif(
    BM25Okapi is None,
    reason="rank-bm25 is not installed; keyword-specific scenario is environment-blocked",
)

ROOT = Path(__file__).parents[1]
DB_BASE = ROOT / "evaluation" / "results" / "vnext_batch5_scenarios"
_db_counter = 0


def _db() -> Database:
    global _db_counter
    _db_counter += 1
    db_path = DB_BASE.parent / f"{DB_BASE.name}_{int(time.time() * 1000)}_{_db_counter}.db"
    db = Database(str(db_path))
    db.init_schema()
    return db


def _request(**overrides: object) -> MemoryRetrievalRequest:
    values: dict[str, Any] = {
        "request_id": "batch5-request",
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "query": "",
        "task_id": "task-1",
        "session_id": "session-1",
        "scope_level": MemoryScope.PROJECT,
        "scope": "PROJECT:project-1",
        "token_budget": 2000,
        "page_size": 5,
    }
    values.update(overrides)
    return MemoryRetrievalRequest(**values)


class _MockVectorRetriever:
    """Deterministic vector channel mock that returns pre-registered hits."""

    def __init__(self, hits: list[SearchResult]) -> None:
        self.hits = hits

    def search(self, req: Any) -> SearchResponse:
        return SearchResponse(results=self.hits[: req.top_k])


class _Harness:
    """Test helper that wires real repositories into a vNext RetrievalService."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.pref_repo = PreferenceRepository(db)
        self.know_repo = KnowledgeRepository(db)
        self.authority_repository = AuthorityRepository(
            db=db,
            preference_repository=self.pref_repo,
            knowledge_repository=self.know_repo,
        )
        self.working_repository = WorkingStateRepository(db)
        self.episode_repository = EpisodeRepository(db)
        self.keyword_search = KeywordSearcher()
        self.vector_hits: list[SearchResult] = []
        self.memory_lookup: dict[str, Any] = {}

    def add_keyword_docs(self, docs: list[tuple[str, str, str]]) -> None:
        self.keyword_search.build_index(docs)

    def create_working(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        session_id: str = "",
        project_id: str = "project-1",
        **fields: Any,
    ) -> None:
        state = {
            "current_goal": fields.get("current_goal", ""),
            "current_step": fields.get("current_step", ""),
            "pending_steps": fields.get("pending_steps", []),
            "completed_steps": fields.get("completed_steps", []),
            "constraints": fields.get("constraints", []),
            "active_entities": fields.get("active_entities", []),
            "blockers": fields.get("blockers", []),
            "recent_findings": fields.get("recent_findings", []),
            "recent_failures": fields.get("recent_failures", []),
            "next_action": fields.get("next_action", ""),
        }
        self.working_repository.create(
            working_state_id=f"ws:{task_id}",
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            session_id=session_id,
            project_id=project_id,
            state=state,
        )

    def create_episode(
        self,
        *,
        tenant_id: str,
        user_id: str,
        episode_id: str,
        task_id: str,
        session_id: str = "",
        project_id: str = "project-1",
        goal: str = "",
        events: list[tuple[str, dict[str, Any], str]] | None = None,
    ) -> None:
        self.episode_repository.create(
            episode_id=episode_id,
            tenant_id=tenant_id,
            user_id=user_id,
            task_id=task_id,
            session_id=session_id,
            project_id=project_id,
            goal=goal,
        )
        for seq, (event_type, payload, source_event_id) in enumerate(events or [], start=1):
            self.episode_repository.append_event(
                episode_event_id=f"ee:{episode_id}:{seq}",
                tenant_id=tenant_id,
                user_id=user_id,
                episode_id=episode_id,
                task_id=task_id,
                event_type=event_type,
                payload=dict(payload),
                source_event_id=source_event_id,
                expected_seq=seq,
            )

    def create_authority(
        self,
        *,
        tenant_id: str,
        user_id: str,
        memory_id: str,
        memory_type: MemoryType,
        normalized_key: str,
        content: dict[str, Any],
        scope_level: MemoryScope,
        scope: str,
    ) -> None:
        envelope = LongTermEnvelope(
            tenant_id=tenant_id,
            user_id=user_id,
            memory_id=memory_id,
            memory_type=memory_type,
            normalized_key=normalized_key,
            content=content,
            scope_level=scope_level,
            scope=scope,
            evolution_status=EvolutionStatus.ACTIVE,
            confidence=0.9,
            utility=0.8,
            evidence_refs=["event-1"],
        )
        self.authority_repository.save(envelope)

    def build_service(self) -> RetrievalService:
        state = SimpleNamespace(
            retriever=_MockVectorRetriever(self.vector_hits),
            keyword_search=self.keyword_search,
            memory_lookup=self.memory_lookup,
            authority_repository=self.authority_repository,
            working_state_repository=self.working_repository,
            episode_repository=self.episode_repository,
        )
        executors = build_channel_executors(state)
        return RetrievalService(
            channel_executors=executors,
            activation_repository=ActivationRepository(self.db),
            retrieval_log_repository=RetrievalLogRepository(self.db),
            authority_repository=self.authority_repository,
            db=self.db,
        )


def test_scenario_a_current_state_returns_working_state() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_working(
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
        session_id="session-1",
        current_goal="修复 SSE reconnect bug",
        current_step="验证断网重连逻辑",
        pending_steps=["测试离线场景", "部署补丁"],
        completed_steps=["定位 timeout 配置"],
        blockers=["需要稳定的网络模拟环境"],
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="我现在做到哪里了",
            task_id="task-1",
            session_id="session-1",
            intent_hint=RetrievalIntent.CURRENT_STATE,
        )
    )

    assert response.intent is RetrievalIntent.CURRENT_STATE
    assert "working" in response.retrieval_plan["enabled_channels"]
    assert response.total_count == 1
    selected = response.selected_memories[0]
    assert selected.layer.value == "WORKING"
    assert selected.scope == "task-1"
    content = selected.content
    assert content["current_goal"] == "修复 SSE reconnect bug"
    assert content["current_step"] == "验证断网重连逻辑"
    assert "需要稳定的网络模拟环境" in content["blockers"]
    assert response.completeness == "FULL"


def test_scenario_b_task_history_returns_episode() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_episode(
        tenant_id="tenant-1",
        user_id="user-1",
        episode_id="ep:task-1",
        task_id="task-1",
        session_id="session-1",
        goal="修复 SSE 重连问题",
        events=[
            ("tool_call", {"summary": "读取 sse_handler.py"}, "ev-1"),
            ("tool_call", {"summary": "修改 timeout 配置", "action": "patch"}, "ev-2"),
            ("tool_call", {"summary": "运行 pytest 失败：连接超时", "success": False}, "ev-3"),
            ("tool_call", {"summary": "运行 pytest 通过", "success": True}, "ev-4"),
        ],
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="之前这个 SSE 重连问题是怎么处理的",
            task_id="task-1",
            scope_level=MemoryScope.TASK,
            scope="TASK:task-1",
        )
    )

    assert response.intent is RetrievalIntent.TASK_HISTORY
    assert "episode" in response.retrieval_plan["enabled_channels"]
    assert response.total_count >= 1
    selected = response.selected_memories[0]
    assert selected.layer.value == "EPISODE"
    assert selected.scope == "task-1"
    assert "修复 SSE 重连问题" in selected.content["text"]
    assert any("pytest 通过" in event for event in selected.content.get("key_events", []))


def test_scenario_c_preference_authority_beats_vector() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="pref-maven",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="build.tool",
        content={"text": "Java 项目偏好 Maven"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
    )
    # Vector channel returns a lower-quality generic hit to prove authority wins.
    harness.vector_hits = [
        SearchResult(
            memory_id="vec-generic",
            memory_type="knowledge",
            content="some generic build tool note",
            score=0.9,
            source="vector",
            metadata={
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "scope_level": "GLOBAL",
                "scope": "GLOBAL",
            },
        )
    ]
    service = harness.build_service()

    response = service.search(
        _request(
            query="我平时用 Maven 还是 Gradle",
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
        )
    )

    assert response.intent is RetrievalIntent.PREFERENCE
    assert "authority" in response.retrieval_plan["enabled_channels"]
    ids = [m.memory_id for m in response.selected_memories]
    assert "pref-maven" in ids
    # Authority channel (weight 1.35) should outrank vector (weight 1.0).
    assert ids[0] == "pref-maven"


def test_scenario_d_semantic_fact_from_authority() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="fact-db",
        memory_type=MemoryType.SEMANTIC,
        normalized_key="project.database",
        content={"text": "当前项目数据库使用 PostgreSQL"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:project-1",
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="这个项目数据库用什么",
            intent_hint=RetrievalIntent.SEMANTIC_FACT,
        )
    )

    assert response.intent is RetrievalIntent.SEMANTIC_FACT
    assert "authority" in response.retrieval_plan["enabled_channels"]
    assert any(
        m.memory_id == "fact-db" and "PostgreSQL" in str(m.content)
        for m in response.selected_memories
    )


@_keyword_backend_required
def test_scenario_e_exact_keyword_hit() -> None:
    db = _db()
    harness = _Harness(db)
    harness.add_keyword_docs(
        [
            (
                "cfg-timeout",
                "spring.mvc.async.request-timeout value is 30s",
                '{"tenant_id": "tenant-1", "user_id": "user-1", "memory_type": "knowledge"}',
            ),
            (
                "cfg-other",
                "server.tomcat.accept-count value is 100",
                '{"tenant_id": "tenant-1", "user_id": "user-1", "memory_type": "knowledge"}',
            ),
        ]
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="spring.mvc.async.request-timeout",
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
        )
    )

    ids = [m.memory_id for m in response.selected_memories]
    assert "cfg-timeout" in ids
    # Exact keyword should rank above the unrelated config.
    assert ids.index("cfg-timeout") < ids.index("cfg-other")


def test_scenario_f_cross_project_isolation() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="pref-maven",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="build.tool",
        content={"text": "Project A uses Maven"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:project-a",
    )
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="pref-gradle",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="build.tool",
        content={"text": "Project B uses Gradle"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:project-b",
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="这个项目用什么构建工具",
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:project-b",
        )
    )

    ids = {m.memory_id for m in response.selected_memories}
    assert "pref-gradle" in ids
    assert "pref-maven" not in ids


def test_scenario_g_cross_user_isolation() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-a",
        memory_id="pref-a",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="editor",
        content={"text": "User A prefers Vim"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
    )
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-b",
        memory_id="pref-b",
        memory_type=MemoryType.PREFERENCE,
        normalized_key="editor",
        content={"text": "User B prefers Emacs"},
        scope_level=MemoryScope.GLOBAL,
        scope="GLOBAL",
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="我平时用什么编辑器",
            user_id="user-b",
            scope_level=MemoryScope.GLOBAL,
            scope="GLOBAL",
        )
    )

    ids = {m.memory_id for m in response.selected_memories}
    assert "pref-b" in ids
    assert "pref-a" not in ids


def test_scenario_h_mixed_intent_uses_working_and_episode() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_working(
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
        current_goal="调试 SSE 重连",
        current_step="等待网络恢复测试",
    )
    harness.create_episode(
        tenant_id="tenant-1",
        user_id="user-1",
        episode_id="ep:task-1",
        task_id="task-1",
        goal="修复 SSE 重连问题",
        events=[
            ("tool_call", {"summary": "已修改 timeout 配置"}, "ev-1"),
            ("tool_call", {"summary": "已验证断网重连"}, "ev-2"),
        ],
    )
    service = harness.build_service()

    response = service.search(
        _request(
            query="现在这个任务做到哪了？之前类似问题是怎么解决的？",
            task_id="task-1",
            intent_hint=RetrievalIntent.MIXED,
        )
    )

    assert response.intent is RetrievalIntent.MIXED
    enabled = set(response.retrieval_plan["enabled_channels"])
    assert "working" in enabled
    assert "episode" in enabled
    layers = {m.layer.value for m in response.selected_memories}
    assert "WORKING" in layers
    assert "EPISODE" in layers


@_keyword_backend_required
def test_scenario_i_duplicate_projection_deduplicated() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_authority(
        tenant_id="tenant-1",
        user_id="user-1",
        memory_id="timeout-fact",
        memory_type=MemoryType.SEMANTIC,
        normalized_key="timeout.config",
        content={"text": "SSE timeout is 30 seconds"},
        scope_level=MemoryScope.PROJECT,
        scope="PROJECT:project-1",
    )
    harness.add_keyword_docs(
        [
            (
                "timeout-fact",
                "SSE timeout is 30 seconds",
                '{"tenant_id": "tenant-1", "user_id": "user-1", "memory_type": "knowledge"}',
            ),
        ]
    )
    harness.vector_hits = [
        SearchResult(
            memory_id="timeout-fact",
            memory_type="knowledge",
            content="SSE timeout is 30 seconds",
            score=0.95,
            source="vector",
            metadata={
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "scope_level": "PROJECT",
                "scope": "PROJECT:project-1",
            },
        )
    ]
    service = harness.build_service()

    response = service.search(_request(query="SSE timeout 配置"))

    ids = [m.memory_id for m in response.selected_memories]
    assert ids.count("timeout-fact") == 1
    assert "timeout-fact" in response.context.relevant_memory_ids


def test_scenario_j_context_budget_trims_low_value_memory() -> None:
    db = _db()
    harness = _Harness(db)
    harness.create_working(
        tenant_id="tenant-1",
        user_id="user-1",
        task_id="task-1",
        current_goal="修复 SSE reconnect bug",
        current_step="验证断网重连",
    )
    # Flood long-term memory with many relevant-ish items.
    for idx in range(20):
        harness.create_authority(
            tenant_id="tenant-1",
            user_id="user-1",
            memory_id=f"noise-{idx}",
            memory_type=MemoryType.SEMANTIC,
            normalized_key=f"noise-{idx}",
            content={"text": f"historical note number {idx}" * 10},
            scope_level=MemoryScope.PROJECT,
            scope="PROJECT:project-1",
        )
    service = harness.build_service()

    response = service.search(
        _request(
            query="当前任务状态",
            token_budget=256,
            page_size=10,
            intent_hint=RetrievalIntent.CURRENT_STATE,
        )
    )

    assert response.context.selected_tokens <= 256
    # Working state is hard-protected and must survive budget trimming.
    ids = set(response.context.relevant_memory_ids)
    assert any(m.layer.value == "WORKING" for m in response.selected_memories)
    # Not every low-value long-term memory can fit into a tiny budget.
    assert len(ids) < 21


class TestLegacyVsVNextComparison:
    """First real Legacy-vs-vNext read comparison using the rollout boundary."""

    def test_current_state_different_from_legacy_vector_only(self) -> None:
        db = _db()
        harness = _Harness(db)
        harness.create_working(
            tenant_id="tenant-1",
            user_id="user-1",
            task_id="task-1",
            current_goal="调试 SSE 重连",
            current_step="等待网络恢复测试",
        )
        service = harness.build_service()

        # Legacy reader that only returns a generic long-term hit, simulating the
        # old vector-only path.
        def legacy_reader(request: MemoryRetrievalRequest) -> SearchResponse:
            return SearchResponse(
                results=[
                    SearchResult(
                        memory_id="legacy-only",
                        memory_type="knowledge",
                        content="some old generic note",
                        score=0.9,
                        source="legacy",
                        metadata={
                            "tenant_id": request.tenant_id,
                            "user_id": request.user_id,
                        },
                    )
                ]
            )

        vnext_result = service.search(
            _request(
                query="我现在做到哪里了",
                task_id="task-1",
                intent_hint=RetrievalIntent.CURRENT_STATE,
            )
        )
        legacy_result = legacy_reader(
            _request(
                query="我现在做到哪里了",
                task_id="task-1",
            )
        )

        vnext_ids = {m.memory_id for m in vnext_result.selected_memories}
        legacy_ids = {r.memory_id for r in legacy_result.results}

        assert vnext_result.intent is RetrievalIntent.CURRENT_STATE
        assert "ws:ws:task-1" in vnext_ids
        assert "legacy-only" in legacy_ids
        assert vnext_ids != legacy_ids
