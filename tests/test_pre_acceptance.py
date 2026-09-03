"""PRE-01~07 偏好记忆验收测试。

对应 old/docs/0811功能性测试/TEST_PLAN.md 6.3 偏好记忆(PRE)。
直接驱动真实实现，作为可复现的逐项通过记录。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memoryhub.adapter.schemas import (
    ConflictDecision,
    Evidence,
    MemoryEvent,
    MemoryLevel,
    MemoryStatus,
    PreferenceMemory,
    PreferenceType,
    SceneScope,
    SourceType,
)
from memoryhub.core.preference.confidence import ConfidenceCalculator
from memoryhub.core.preference.extractor import PreferenceExtractor
from memoryhub.core.preference.updater import ConflictDetector, PreferenceUpdater
from memoryhub.storage.database import (
    ConflictRepository,
    Database,
    PreferenceRepository,
)


def _db(tmp_path: Path) -> Database:
    db = Database(str(tmp_path / "pre.db"))
    db.init_schema()
    return db


def _hash(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _quality_score() -> dict:
    return {
        "score": 0.9,
        "status": "accepted",
        "completeness": 0.9,
        "validity": 0.9,
        "consistency": 0.9,
        "freshness": 0.9,
        "issues": [],
    }


def _event(
    event_id: str,
    *,
    user_id: str = "u1",
    text: str = "以后用 markdown 输出周报",
    scene: str = "office",
    task_type: str = "office.report",
    source_type: SourceType = SourceType.USER_BEHAVIOR,
    occurred_at: str = "2026-08-03T12:00:00Z",
) -> MemoryEvent:
    st = source_type.value
    return MemoryEvent.model_validate({
        "event_id": event_id,
        "source_type": st,
        "event_type": "user_action",
        "user_id": user_id,
        "session_id": "s1",
        "turn_id": "turn-1",
        "scene": scene,
        "task_type": task_type,
        "occurred_at": occurred_at,
        "text": text,
        "payload": {"action": "message", "role": "user"},
        "tool_calls": [],
        "schema_version": "1.1",
        "source_hash": _hash(event_id),
        "redactions": [],
        "quality": _quality_score(),
    })


def _pref(
    memory_id: str,
    *,
    user_id: str = "u1",
    text: str = "偏好使用 markdown 格式",
    pref_type: PreferenceType = PreferenceType.FORMAT_PREF,
    scene: str = "office",
    task_type: str = "office.report",
    is_global: bool = False,
    extract_source: str = "explicit_feedback",
    evidence: Evidence | None = None,
    payload: dict | None = None,
) -> PreferenceMemory:
    return PreferenceMemory(
        memory_id=memory_id,
        user_id=user_id,
        preference_type=pref_type,
        text=text,
        payload=payload if payload is not None else {"target": "output_format", "value": "markdown"},
        scope=SceneScope(scene=scene, task_type=task_type),
        is_global=is_global,
        quality_score=0.9,
        extract_source=extract_source,
        level=MemoryLevel.LONG,
        evidences=[evidence] if evidence is not None else [],
    )


class _FakeLLM:
    """顺序返回预置 JSON 响应；raise 则模拟 LLM 故障。"""

    def __init__(self, responses=None, raise_error=False):
        self.responses = list(responses or [])
        self.raise_error = raise_error
        self.calls = 0

    def generate(self, prompt, system_prompt=None):
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("llm unavailable")
        return _Resp(self.responses.pop(0) if self.responses else "{}")


class _Resp:
    def __init__(self, content):
        self.content = content


# ==============================================================================
# PRE-01 规则抽取 / PRE-02 LLM 抽取
# ==============================================================================


class TestPre01RuleExtraction:
    def test_explicit_format_rule(self) -> None:
        extractor = PreferenceExtractor()
        prefs = extractor.extract(_event("evt_fmt1", text="以后用 markdown 输出周报"))
        assert len(prefs) == 1
        pref = prefs[0]
        assert pref.preference_type is PreferenceType.FORMAT_PREF
        assert pref.extract_source == "explicit_feedback"
        assert pref.is_global is False
        assert pref.scope.scene == "office"

    def test_global_format_rule(self) -> None:
        extractor = PreferenceExtractor()
        prefs = extractor.extract(_event("evt_fmt2", text="始终使用 JSON 输出"))
        assert len(prefs) == 1
        pref = prefs[0]
        assert pref.preference_type is PreferenceType.FORMAT_PREF
        assert pref.is_global is True
        assert pref.scope.scene == "*"

    def test_privacy_rule_maps_to_safety_pref(self) -> None:
        extractor = PreferenceExtractor()
        prefs = extractor.extract(_event("evt_safe1", text="不要记住我的密码和位置"))
        assert len(prefs) == 1
        pref = prefs[0]
        assert pref.preference_type is PreferenceType.SAFETY_PREF
        assert pref.is_global is True
        assert pref.scope.scene == "*"

    def test_llm_maps_all_seven_preference_types(self) -> None:
        type_text = {t.value: t for t in PreferenceType}
        llm = _FakeLLM(responses=[
            json.dumps({"implicit_pref": f"用户偏好 {v} 相关的行为习惯描述", "preference_type": v,
                        "action_payload": {"action": "set", "target": v, "value": "on"},
                        "tags": [v], "is_global": False})
            for v in type_text
        ])
        extractor = PreferenceExtractor(llm_client=llm)
        for i, pref_type in enumerate(type_text.values()):
            prefs = extractor.extract(_event(f"evt_llm{i}", text="一些中性的行为描述文字"))
            assert len(prefs) == 1, f"type {pref_type.value} should extract"
            assert prefs[0].preference_type is pref_type, (
                f"expected {pref_type.value}, got {prefs[0].preference_type.value}"
            )

    def test_llm_global_detection(self) -> None:
        llm = _FakeLLM(responses=[
            json.dumps({"implicit_pref": "用户希望所有场景都使用简洁摘要输出", "preference_type": "output_style",
                        "action_payload": {"action": "set", "target": "summary_style", "value": "concise"},
                        "tags": ["summary"], "is_global": True})
        ])
        extractor = PreferenceExtractor(llm_client=llm)
        prefs = extractor.extract(_event("evt_llm_g", text="中性行为描述"))
        assert len(prefs) == 1
        assert prefs[0].is_global is True
        assert prefs[0].scope.scene == "*"


class TestPre02LlmExtraction:
    def test_structured_output(self) -> None:
        llm = _FakeLLM(responses=[
            json.dumps({"implicit_pref": "用户在出行场景偏好提前规划路线",
                        "preference_type": "workflow_preference",
                        "action_payload": {"action": "prefer", "target": "route_planning", "value": "early"},
                        "tags": ["travel", "planning"], "is_global": False})
        ])
        extractor = PreferenceExtractor(llm_client=llm)
        prefs = extractor.extract(_event("evt_llm1", text="出行场景的中性描述文本"))
        assert len(prefs) == 1
        pref = prefs[0]
        assert pref.preference_type is PreferenceType.WORKFLOW_PREF
        assert "路线" in pref.text or "route" in pref.text.lower()
        assert pref.payload.get("target") == "route_planning"

    def test_llm_failure_degrades_gracefully(self) -> None:
        extractor = PreferenceExtractor(llm_client=_FakeLLM(raise_error=True))
        assert extractor.extract(_event("evt_llm_fail", text="中性行为描述")) == []

    def test_llm_garbage_json_degrades_gracefully(self) -> None:
        extractor = PreferenceExtractor(llm_client=_FakeLLM(responses=["not-json{{{" ]))
        assert extractor.extract(_event("evt_llm_bad", text="中性行为描述")) == []

    def test_no_llm_client_returns_empty(self) -> None:
        extractor = PreferenceExtractor()
        prefs = extractor.extract(_event("evt_llm_none", text="中性行为描述"))
        assert prefs == []


# ==============================================================================
# PRE-03 置信度计算
# ==============================================================================


class TestPre03Confidence:
    def test_baseline_explicit_vs_implicit(self) -> None:
        calc = ConfidenceCalculator()
        explicit = _pref("mem_base_e", extract_source="explicit_feedback")
        implicit = _pref("mem_base_i", extract_source="implicit_inference")
        assert calc.calculate(explicit) == pytest.approx(0.8)
        assert calc.calculate(implicit) == pytest.approx(0.5)

    def test_user_behavior_outranks_tool_result(self) -> None:
        calc = ConfidenceCalculator()
        fresh = "2026-08-03T12:00:00Z"
        user = _pref("mem_u", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp=fresh, weight=1.0))
        tool = _pref("mem_t", evidence=Evidence(
            event_id="e2", source_type=SourceType.TOOL_RESULT, timestamp=fresh, weight=1.0))
        assert calc.calculate(user) > calc.calculate(tool)

    def test_fresh_evidence_outranks_old(self) -> None:
        calc = ConfidenceCalculator()
        fresh = _pref("mem_f", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp="2026-08-03T12:00:00Z", weight=1.0))
        stale = _pref("mem_o", evidence=Evidence(
            event_id="e2", source_type=SourceType.USER_BEHAVIOR, timestamp="2020-01-01T00:00:00Z", weight=1.0))
        assert calc.calculate(fresh) > calc.calculate(stale)

    def test_override_marked_evidence_lowers_confidence(self) -> None:
        calc = ConfidenceCalculator()
        clean = _pref("mem_c", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp="2026-08-03T12:00:00Z", weight=1.0))
        conflicted = _pref("mem_x", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp="2026-08-03T12:00:00Z", weight=1.0))
        conflicted.evidences.append(Evidence(
            event_id="e2", source_type=SourceType.USER_BEHAVIOR,
            timestamp="2026-08-03T13:00:00Z", weight=1.0, decision=ConflictDecision.OVERRIDE))
        assert calc.calculate(clean) > calc.calculate(conflicted)

    def test_new_evidence_moves_confidence(self) -> None:
        calc = ConfidenceCalculator()
        pref = _pref("mem_e", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp="2026-08-03T12:00:00Z", weight=0.6))
        before = calc.calculate(pref)
        after = calc.update_confidence(
            pref,
            _event("evt_new", occurred_at="2026-08-04T12:00:00Z"),
        )
        assert len(pref.evidences) == 2
        assert after != before

    def test_duplicate_event_id_not_appended_twice(self) -> None:
        calc = ConfidenceCalculator()
        pref = _pref("mem_n", evidence=Evidence(
            event_id="e1", source_type=SourceType.USER_BEHAVIOR, timestamp="2026-08-03T12:00:00Z", weight=1.0))
        calc.update_confidence(pref, _event("e1"))
        assert len(pref.evidences) == 1


# ==============================================================================
# PRE-04 版本链
# ==============================================================================


class TestPre04VersionChain:
    def _updater(self, db: Database) -> PreferenceUpdater:
        return PreferenceUpdater(
            pref_repo=PreferenceRepository(db),
            conflict_repo=ConflictRepository(db),
        )

    def test_continuous_update_builds_version_chain(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        updater = self._updater(db)
        repo = PreferenceRepository(db)

        v1 = _pref("mem_v1", text="偏好使用 markdown 格式")
        assert updater.add(v1) == "mem_v1"

        v2 = _pref("mem_v2", text="偏好使用 HTML 格式", payload={"target": "output_format", "value": "html"})
        assert updater.add(v2) == "mem_v2"

        chain = repo.get_version_chain("mem_v2")
        assert [m.version for m in chain] == [1, 2]
        assert chain[0].memory_id == "mem_v1"
        assert chain[0].status is MemoryStatus.ARCHIVED
        assert chain[1].memory_id == "mem_v2"
        assert chain[1].status is MemoryStatus.ACTIVE
        assert chain[1].parent_id == "mem_v1"
        assert chain[1].root_id == "mem_v1"

    def test_new_pref_gets_own_root(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        updater = self._updater(db)
        updater.add(_pref("mem_r1", text="偏好使用 markdown 格式"))
        updater.add(_pref("mem_r2", text="偏好在早间时段安排工作", pref_type=PreferenceType.SCENE_PREF))
        repo = PreferenceRepository(db)
        saved = repo.get_by_id("mem_r2")
        assert saved is not None
        assert saved.root_id == "mem_r2"
        assert saved.version == 1


# ==============================================================================
# PRE-05 全局兜底
# ==============================================================================


class TestPre05GlobalFallback:
    def test_global_pref_fallback_when_no_scene_pref(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        repo = PreferenceRepository(db)
        repo.save(_pref("mem_g", text="全局都偏好 markdown", is_global=True, scene="*", task_type="*"))
        repo.save(_pref("mem_o", text="办公场景偏好 markdown", scene="office", task_type="*"))

        in_office = repo.get_active("u1", scene="office")
        assert {m.memory_id for m in in_office} == {"mem_g", "mem_o"}

        no_scene_pref = repo.get_active("u1", scene="travel")
        assert [m.memory_id for m in no_scene_pref] == ["mem_g"]

    def test_search_ranks_scene_specific_above_global(self, tmp_path: Path) -> None:
        from memoryhub.adapter.schemas import SceneScope, SearchRequest
        from memoryhub.adapter.service import MemoryService

        db_path = str(tmp_path / "pre.db")
        db = _db(tmp_path)
        repo = PreferenceRepository(db)
        repo.save(_pref("mem_g", text="全局都偏好 markdown", is_global=True, scene="*", task_type="*"))
        repo.save(_pref("mem_o", text="办公场景偏好 markdown", scene="office", task_type="*"))

        service = MemoryService(db_path=db_path)
        service.start()
        resp = service.search(SearchRequest(
            query="markdown", user_id="u1",
            context=SceneScope(scene="office", task_type="office.report"),
        ))
        memories = [r.memory_id for r in resp.results]
        assert "mem_g" in memories
        assert "mem_o" in memories
        service.close()


# ==============================================================================
# PRE-06 证据链
# ==============================================================================


class TestPre06EvidenceChain:
    def test_extraction_creates_evidence(self) -> None:
        extractor = PreferenceExtractor()
        event = _event("evt_ev1", text="以后用 markdown 输出周报")
        prefs = extractor.extract(event)
        assert len(prefs) == 1
        ev = prefs[0].evidences[0]
        assert ev.event_id == "evt_ev1"
        assert ev.weight == pytest.approx(0.9)
        assert ev.decision is None

    def test_evidence_json_readable(self) -> None:
        extractor = PreferenceExtractor()
        prefs = extractor.extract(_event("evt_ev2", text="以后用 markdown 输出周报"))
        dumped = [e.model_dump(mode="json") for e in prefs[0].evidences]
        assert "event_id" in dumped[0]
        assert "weight" in dumped[0]
        assert "decision" in dumped[0]
        json.dumps(dumped)

    def test_conflict_marks_evidence_decision(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        updater = PreferenceUpdater(
            pref_repo=PreferenceRepository(db),
            conflict_repo=ConflictRepository(db),
        )
        updater.add(_pref("mem_ev1", text="偏好使用 markdown 格式"))
        override = _pref("mem_ev2", text="偏好使用 HTML 格式", payload={"target": "output_format", "value": "html"})
        updater.add(override)
        repo = PreferenceRepository(db)
        saved = repo.get_by_id("mem_ev2")
        assert saved is not None
        assert all(e.decision is not None for e in saved.evidences)


# ==============================================================================
# PRE-07 用户隔离
# ==============================================================================


class TestPre07UserIsolation:
    def test_repo_retrieval_scoped_by_user(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        repo = PreferenceRepository(db)
        repo.save(_pref("mem_u1", user_id="alice"))
        repo.save(_pref("mem_u2", user_id="bob"))
        assert {m.memory_id for m in repo.get_active("alice")} == {"mem_u1"}
        assert {m.memory_id for m in repo.get_active("bob")} == {"mem_u2"}

    def test_updater_does_not_cross_users(self, tmp_path: Path) -> None:
        db = _db(tmp_path)
        updater = PreferenceUpdater(pref_repo=PreferenceRepository(db))
        updater.add(_pref("mem_ua", user_id="alice", text="偏好使用 markdown"))
        updater.add(_pref("mem_ub", user_id="bob", text="偏好使用 HTML", payload={"target": "output_format", "value": "html"}))
        repo = PreferenceRepository(db)
        bob = repo.get_by_id("mem_ub")
        alice = repo.get_by_id("mem_ua")
        assert bob is not None and alice is not None
        assert bob.version == 1
        assert alice.version == 1
        assert bob.root_id == "mem_ub"
