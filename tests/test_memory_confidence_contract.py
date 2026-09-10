# -*- coding: utf-8 -*-
"""写入置信度契约：调用方的 confidence 是占位值，服务端按证据链重算。

回归背景：此前 `MemoryWriteService._enforce_confidence_contract` 只处理偏好，
且注入的写入证据把来源类型写死成 manual_config、权重写死成 1.0，于是每条新写入
的偏好都恒为 0.8833；知识记忆因为直接 return 而完全不重算，全部落成调用方的占位
值 0.5。本文件同时钉住「值可复现」与「值随来源/结构/证据变化」两件事。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from memoryhub.adapter.schemas import (
    Evidence,
    KnowledgeMemory,
    KnowledgeType,
    PreferenceMemory,
    SourceType,
)
from memoryhub.app import create_app
from memoryhub.config import AppConfig, SafetyConfig, StorageConfig, UserRuleConfig
from memoryhub.core.knowledge.confidence import KnowledgeConfidenceCalculator
from memoryhub.core.memory.confidence import UnifiedConfidenceCalculator
from memoryhub.core.memory_write import _TIEBREAK_SPAN, MemoryWriteService
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)

#: 修复前偏好写入的恒定值，任何写入都不应再落在这个数上。
LEGACY_CONSTANT = 0.8833


def _service(tmp_path):
    db = Database(str(tmp_path / "memoryhub.db"))
    db.init_schema()
    service = MemoryWriteService(
        pref_repo=PreferenceRepository(db),
        know_repo=KnowledgeRepository(db),
    )
    return service, db


def _api_client(tmp_path) -> TestClient:
    config = AppConfig(
        storage=StorageConfig(
            db_path=str(tmp_path / "memoryhub.db"),
            vector_index_path=str(tmp_path / "vector_index"),
            evidence_path=str(tmp_path / "evidence"),
        ),
        safety=SafetyConfig(user_rules=UserRuleConfig(enabled=False)),
    )
    return TestClient(create_app(config))


def _pref(service, memory_id: str, *, extract_source: str, quality_score: float = 1.0):
    memory = PreferenceMemory(
        memory_id=memory_id,
        user_id="u1",
        text="Weekend deploys are frozen",
        extract_source=extract_source,
        quality_score=quality_score,
    )
    service.upsert_memory(memory)
    return service.pref_repo.get_by_id(memory_id)


def test_preference_confidence_varies_with_provenance(tmp_path) -> None:
    """不同来源的偏好必须得到不同的置信度，而不是同一个常数。"""
    service, db = _service(tmp_path)
    try:
        explicit = _pref(service, "pref_explicit", extract_source="explicit_feedback")
        implicit = _pref(service, "pref_implicit", extract_source="implicit_inference")
        weak = _pref(
            service,
            "pref_weak",
            extract_source="implicit_inference",
            quality_score=0.6,
        )

        values = {explicit.confidence, implicit.confidence, weak.confidence}
        assert len(values) == 3
        assert LEGACY_CONSTANT not in values
        # 用户显式反馈比隐式推断可信；同样的来源下质量分低的更弱。
        assert explicit.confidence > implicit.confidence > weak.confidence
    finally:
        db.close()


def test_confidence_differs_per_memory_within_one_provenance(tmp_path) -> None:
    """同一来源下的不同记忆也必须得到不同置信度——置信度要区分「这一条」而非通道。"""
    service, db = _service(tmp_path)
    try:
        texts = [
            "用中文",
            "输出一律使用中文",
            "生成周报时输出一律使用中文，不要夹杂英文术语，表格用 Markdown",
        ]
        for index, text in enumerate(texts):
            service.upsert_memory(
                PreferenceMemory(
                    memory_id=f"pref_content_{index}",
                    user_id="u1",
                    text=text,
                    extract_source="explicit_feedback",
                )
            )
        values = [
            service.pref_repo.get_by_id(f"pref_content_{index}").confidence
            for index in range(len(texts))
        ]
        assert len(set(values)) == len(values)
        # 信息量更大的一条不应低于信息量更小的一条。
        assert values == sorted(values)
    finally:
        db.close()


def test_confidence_separates_same_shape_records(tmp_path) -> None:
    """结构与长度都相同、只有内容不同的两条记录也必须区分开（内容微扰的职责）。"""
    service, db = _service(tmp_path)
    try:
        for index, (name, subject) in enumerate(
            (("部署流程", "打包后重启"), ("发布流程", "发布前需回归"))
        ):
            service.upsert_memory(
                KnowledgeMemory(
                    memory_id=f"know_shape_{index}",
                    user_id="u1",
                    knowledge_type=KnowledgeType.FACT,
                    name=name,
                    content=name,
                    subject=subject,
                )
            )
        left = service.know_repo.get_by_id("know_shape_0").confidence
        right = service.know_repo.get_by_id("know_shape_1").confidence
        assert left != right
    finally:
        db.close()


def test_confidence_is_stable_for_identical_content(tmp_path) -> None:
    """确定性：内容、来源、质量都相同的两条记忆，置信度必须一致，不做随机扰动。"""
    service, db = _service(tmp_path)
    try:
        for memory_id in ("pref_same_a", "pref_same_b"):
            service.upsert_memory(
                PreferenceMemory(
                    memory_id=memory_id,
                    user_id="u1",
                    text="输出一律使用中文",
                    extract_source="explicit_feedback",
                )
            )
        assert (
            service.pref_repo.get_by_id("pref_same_a").confidence
            == service.pref_repo.get_by_id("pref_same_b").confidence
        )
    finally:
        db.close()


def test_preference_write_evidence_uses_real_provenance(tmp_path) -> None:
    """注入的写入证据必须带真实来源与质量分，而不是写死的 manual_config/1.0。"""
    service, db = _service(tmp_path)
    try:
        explicit = _pref(service, "pref_explicit_ev", extract_source="explicit_feedback")
        implicit = _pref(service, "pref_implicit_ev", extract_source="implicit_inference")
        weak = _pref(
            service,
            "pref_weak_ev",
            extract_source="implicit_inference",
            quality_score=0.6,
        )

        assert len(explicit.evidences) == 1
        assert explicit.evidences[0].source_type is SourceType.USER_BEHAVIOR
        assert implicit.evidences[0].source_type is SourceType.TOOL_RESULT
        # 权重 = 来源质量分 × 内容信息量，落在 (0, 1] 且质量分低的更小。
        assert 0.0 < weak.evidences[0].weight < explicit.evidences[0].weight <= 1.0
    finally:
        db.close()


def test_knowledge_write_is_not_the_caller_placeholder(tmp_path) -> None:
    """知识记忆与偏好一样在写入收口点重算，0.5 占位值不得落库。"""
    service, db = _service(tmp_path)
    try:
        memory = KnowledgeMemory(
            memory_id="know_recomputed",
            user_id="u1",
            knowledge_type=KnowledgeType.FACT,
            name="Deploy window",
            content="Deploy window is Friday",
            subject="Deploy window",
            predicate="is",
            object_value="Friday",
            confidence=0.5,  # MCP remember() 的默认占位值
        )
        service.upsert_memory(memory)
        stored = service.know_repo.get_by_id("know_recomputed")

        assert stored.confidence != 0.5
        # 落库值 = 公式值 ± 有界的内容微扰（微扰只用来打破并列）。
        assert (
            abs(stored.confidence - KnowledgeConfidenceCalculator().from_memory(stored))
            <= _TIEBREAK_SPAN
        )
        assert stored.confidence > UnifiedConfidenceCalculator.review_threshold
    finally:
        db.close()


def test_knowledge_confidence_tracks_structure_and_reliability(tmp_path) -> None:
    """知识置信度随结构完整度与成功复用率变化。"""
    service, db = _service(tmp_path)
    try:
        bare = KnowledgeMemory(
            memory_id="know_bare",
            user_id="u1",
            knowledge_type=KnowledgeType.WORKFLOW,
            name="Bare workflow",
            content="do the thing",
        )
        structured = KnowledgeMemory(
            memory_id="know_structured",
            user_id="u1",
            knowledge_type=KnowledgeType.WORKFLOW,
            name="Structured workflow",
            content="do the thing",
            steps=["collect", "summarize", "review"],
            tools=["search", "writer"],
        )
        for memory in (bare, structured):
            service.upsert_memory(memory)
        assert (
            service.know_repo.get_by_id("know_bare").confidence
            < service.know_repo.get_by_id("know_structured").confidence
        )

        # 复用率：其余条件全同，只改 success/total。
        fact = {
            "user_id": "u1",
            "knowledge_type": KnowledgeType.FACT,
            "name": "Owner",
            "content": "Owner is Alice",
            "subject": "Owner",
            "predicate": "is",
            "object_value": "Alice",
        }
        fresh = KnowledgeMemory(
            memory_id="know_fresh", success_count=0, total_count=5, **fact
        )
        proven = KnowledgeMemory(
            memory_id="know_proven", success_count=5, total_count=5, **fact
        )
        # 结构完整度：其余条件全同（都未复用），只改 S/P/O 的完整程度。
        complete = KnowledgeMemory(memory_id="know_complete", **fact)
        partial = KnowledgeMemory(
            memory_id="know_partial",
            user_id="u1",
            knowledge_type=KnowledgeType.FACT,
            name="Owner",
            content="Owner is Alice",
            subject="Owner",
        )
        for memory in (fresh, proven, complete, partial):
            service.upsert_memory(memory)
        assert (
            service.know_repo.get_by_id("know_proven").confidence
            > service.know_repo.get_by_id("know_fresh").confidence
        )
        # 只有主语、缺谓词与客体 → 结构完整度更低。
        assert (
            service.know_repo.get_by_id("know_complete").confidence
            > service.know_repo.get_by_id("know_partial").confidence
        )
    finally:
        db.close()


def test_knowledge_confidence_grows_with_evidence_chain(tmp_path) -> None:
    """证据链变长 → support 分档上升 → 置信度提高。"""
    service, db = _service(tmp_path)
    try:
        single = KnowledgeMemory(
            memory_id="know_single",
            user_id="u1",
            knowledge_type=KnowledgeType.FACT,
            name="Owner",
            content="Owner is Alice",
            subject="Owner",
            predicate="is",
            object_value="Alice",
            evidences=[
                Evidence(event_id="e1", content="first", source_type=SourceType.TOOL_RESULT)
            ],
        )
        double = single.model_copy(
            update={
                "memory_id": "know_double",
                "evidences": [
                    Evidence(
                        event_id="e1", content="first", source_type=SourceType.TOOL_RESULT
                    ),
                    Evidence(
                        event_id="e2", content="second", source_type=SourceType.TOOL_RESULT
                    ),
                ],
            }
        )
        for memory in (single, double):
            service.upsert_memory(memory)
        assert (
            service.know_repo.get_by_id("know_double").confidence
            > service.know_repo.get_by_id("know_single").confidence
        )
    finally:
        db.close()


def test_governed_writes_keep_pipeline_confidence(tmp_path) -> None:
    """治理来源（vnext_authority）的置信度由权威流水线管理，写入路径不覆盖。"""
    service, db = _service(tmp_path)
    try:
        preference = PreferenceMemory(
            memory_id="pref_governed",
            user_id="u1",
            text="Governed preference",
            extract_source="vnext_authority",
            confidence=0.85,
        )
        knowledge = KnowledgeMemory(
            memory_id="know_governed",
            user_id="u1",
            knowledge_type=KnowledgeType.FACT,
            name="Governed fact",
            content="Governed fact content",
            subject="a",
            predicate="b",
            object_value="c",
            confidence=0.93,
            extra_payload={"vnext_authority": {"envelope_id": "env-1"}},
            evidences=[
                Evidence(event_id="e1", content="proof", source_type=SourceType.TOOL_RESULT)
            ],
        )
        service.upsert_memory(preference)
        service.upsert_memory(knowledge)
        assert service.pref_repo.get_by_id("pref_governed").confidence == 0.85
        assert service.know_repo.get_by_id("know_governed").confidence == 0.93
    finally:
        db.close()


def test_api_knowledge_write_recomputes_placeholder(tmp_path) -> None:
    """端到端：走 REST 写入的知识记忆不再把占位 confidence 原样落库。"""
    with _api_client(tmp_path) as client:
        response = client.post(
            "/api/memory/memories/knowledge",
            json={
                "user_id": "u-api",
                "knowledge_type": "workflow",
                "name": "Release checklist",
                "content": "How releases are cut",
                "steps": ["branch", "tag"],
                "tools": ["git"],
                "confidence": 0.0,
            },
        )
        assert response.status_code == 200, response.text
        memory_id = response.json()["memory_id"]
        stored = client.app.state.know_repo.get_by_id(memory_id)
        assert stored.confidence != 0.0
        assert stored.confidence > UnifiedConfidenceCalculator.review_threshold
