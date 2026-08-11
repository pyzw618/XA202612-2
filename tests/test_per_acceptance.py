# -*- coding: utf-8 -*-
"""PER-01 ~ PER-04 持久化与恢复专项验收测试。

对应 docs/TEST_PLAN.md 6.10 持久化与恢复(PER-01~04)：
  PER-01  SQLite 表结构与 INTERFACE.md 6.1 对齐
  PER-02  重启恢复（写入→重建进程→查询，数据不丢）
  PER-03  证据链 JSONL（每 memory_id 一个文件，行格式正确）
  PER-04  向量落盘（FAISS save/load，id_map/reverse_map 一致）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from memoryhub.adapter.schemas import (
    ConflictDecision,
    Evidence,
    KnowledgeMemory,
    PreferenceMemory,
    SceneScope,
)
from memoryhub.storage.database import (
    Database,
    KnowledgeRepository,
    PreferenceRepository,
)
from memoryhub.storage.evidence_store import EvidenceStore
from memoryhub.storage.vector_store import VectorStore

INTERFACE_6_1_TABLES = {
    "events",
    "preferences",
    "knowledge",
    "knowledge_versions",
    "conflicts",
    "forget_history",
    "extraction_tasks",
}

PREFERENCE_COLUMNS = {
    "memory_id",
    "user_id",
    "memory_type",
    "preference_type",
    "content",
    "payload",
    "scope_scene",
    "scope_task_type",
    "scope_app",
    "is_global",
    "confidence",
    "quality_score",
    "extract_source",
    "status",
    "level",
    "version",
    "parent_id",
    "root_id",
    "evidences",
    "tags",
    "extra_payload",
    "health_score",
    "stability",
    "last_accessed_at",
    "access_count_30d",
    "created_at",
    "updated_at",
}


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(str(tmp_path / "memoryhub.db"))
    database.init_schema()
    yield database
    database.close()


def _columns(db: Database, table: str) -> set[str]:
    with db.session() as s:
        rows = s.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def test_per_01_schema_has_all_business_tables(db: Database) -> None:
    """PER-01a: 建库后存在全部业务表"""
    with db.session() as s:
        tables = {r[0] for r in s.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )).fetchall()}
    assert INTERFACE_6_1_TABLES <= tables


def test_per_01_preferences_has_extended_columns(db: Database) -> None:
    """PER-01b: preferences 表具备 INTERFACE.md 6.1 扩展列"""
    assert PREFERENCE_COLUMNS <= _columns(db, "preferences")


def test_per_01_knowledge_has_extended_columns(db: Database) -> None:
    """PER-01c: knowledge 表具备健康度/索引同步扩展列"""
    columns = _columns(db, "knowledge")
    assert {
        "memory_id",
        "knowledge_type",
        "name",
        "steps",
        "tools",
        "template_body",
        "pending_index",
        "index_version",
        "health_score",
        "stability",
        "access_count_30d",
    } <= columns


def test_per_01_events_table_matches_interface(db: Database) -> None:
    """PER-01d: events 表字段与 INTERFACE.md 6.1 events 契约一致"""
    columns = _columns(db, "events")
    expected = {
        "event_id",
        "source_type",
        "event_type",
        "user_id",
        "session_id",
        "turn_id",
        "scene",
        "task_type",
        "occurred_at",
        "text",
        "payload",
        "tool_calls",
        "schema_version",
        "source_hash",
        "redactions",
        "quality",
    }
    assert expected <= columns


def test_per_02_restart_recovery_keeps_data(tmp_path: Path) -> None:
    """PER-02a: 重建连接后数据不丢（模拟进程重启）"""
    db_path = str(tmp_path / "memoryhub.db")
    first = Database(db_path)
    first.init_schema()
    pref_repo = PreferenceRepository(first)
    pref = PreferenceMemory(
        memory_id="pref_survive",
        user_id="u1",
        text="周报用 Markdown",
        scope=SceneScope(scene="office"),
        confidence=0.9,
    )
    pref_repo.save(pref)
    first.close()

    second = Database(db_path)
    second.init_schema()
    restored = PreferenceRepository(second).get_by_id("pref_survive")
    assert restored is not None
    assert restored.text == "周报用 Markdown"
    assert restored.user_id == "u1"
    second.close()


def test_per_02_evidence_chain_survives_restart(tmp_path: Path) -> None:
    """PER-02b: 证据链在重建存储实例后可加载"""
    base = tmp_path / "evidence"
    first = EvidenceStore(str(base))
    first.save(
        "mem_ev",
        Evidence(event_id="e1", content="第一份证据", weight=0.8),
    )
    first.save(
        "mem_ev",
        Evidence(event_id="e2", content="第二份证据", weight=0.6),
    )

    second = EvidenceStore(str(base))
    evidences = second.load("mem_ev")
    assert len(evidences) == 2
    assert [ev.content for ev in evidences] == ["第一份证据", "第二份证据"]


def test_per_03_evidence_jsonl_round_trip(tmp_path: Path) -> None:
    """PER-03a: 写入/追加后每 memory_id 一个 JSONL 文件,行格式正确"""
    store = EvidenceStore(str(tmp_path / "evidence"))
    ev1 = Evidence(event_id="e1", content="证据甲", weight=0.7)
    ev2 = Evidence(event_id="e2", content="证据乙", weight=0.9)

    store.save("mem_a", ev1)
    store.batch_save("mem_a", [ev2])
    store.save("mem_b", Evidence(event_id="e3", content="其他记忆证据"))

    file_a = tmp_path / "evidence" / "mem_a.jsonl"
    file_b = tmp_path / "evidence" / "mem_b.jsonl"
    assert file_a.exists()
    assert file_b.exists()
    assert len(list((tmp_path / "evidence").glob("*.jsonl"))) == 2

    lines = file_a.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        data = json.loads(line)
        assert data["event_id"] in {"e1", "e2"}
    assert Evidence.model_validate_json(lines[0]).content == "证据甲"

    loaded = store.load("mem_a")
    assert [ev.event_id for ev in loaded] == ["e1", "e2"]
    assert store.list_all() == ["mem_a", "mem_b"]


def test_per_03_evidence_delete_removes_file(tmp_path: Path) -> None:
    """PER-03b: 删除证据链时物理删除对应 JSONL 文件"""
    store = EvidenceStore(str(tmp_path / "evidence"))
    store.save("mem_c", Evidence(event_id="e1", content="待删除"))
    assert store.load("mem_c")
    assert store.delete("mem_c") is True
    assert store.load("mem_c") == []
    assert not (tmp_path / "evidence" / "mem_c.jsonl").exists()
    assert store.delete("mem_c") is False  # 二次删除返回 False


def test_per_04_vector_store_persist_and_reload(tmp_path: Path) -> None:
    """PER-04a: FAISS save/load 后 id_map/reverse_map 一致且可检索"""
    dimension = 16
    index_path = str(tmp_path / "vector_index")
    first = VectorStore(index_path, dimension=dimension)
    first.init_index()
    first.add("mem_v1", _unit_vec(0, dimension))
    first.add("mem_v2", _unit_vec(1, dimension))
    first.batch_add([("mem_v3", _unit_vec(2, dimension))])
    first.save()

    second = VectorStore(index_path, dimension=dimension)
    second.init_index()  # 从磁盘加载成功
    assert second.index is not None
    assert second.reverse_map == {"mem_v1": 0, "mem_v2": 1, "mem_v3": 2}
    assert second.id_map == {0: "mem_v1", 1: "mem_v2", 2: "mem_v3"}
    assert second.size() == 3

    results = second.search(_unit_vec(0, dimension), top_k=1)
    assert results[0][0] == "mem_v1"
    assert results[0][1] > 0.9


def test_per_04_vector_reload_after_deletion(tmp_path: Path) -> None:
    """PER-04b: 删除并重建后落盘,reload 不再返回已删向量"""
    dimension = 16
    index_path = str(tmp_path / "vector_index")
    first = VectorStore(index_path, dimension=dimension)
    first.init_index()
    first.add("mem_d1", _unit_vec(0, dimension))
    first.add("mem_d2", _unit_vec(1, dimension))
    first.delete("mem_d1")
    first.save()

    second = VectorStore(index_path, dimension=dimension)
    second.init_index()
    assert second.index is not None
    assert second.size() == 1
    results = second.search(_unit_vec(0, dimension), top_k=1)
    assert [mid for mid, _ in results] == ["mem_d2"]


def _unit_vec(position: int, dimension: int) -> list[float]:
    vec = [0.0] * dimension
    vec[position] = 1.0
    return vec


def test_per_02_knowledge_with_conflict_survives_restart(tmp_path: Path) -> None:
    """PER-02c: knowledge 写入与冲突解决记录在重建后保持"""
    from memoryhub.adapter.schemas import ConflictRecord
    from memoryhub.storage.database import ConflictRepository

    db_path = str(tmp_path / "memoryhub.db")
    first = Database(db_path)
    first.init_schema()
    know_repo = KnowledgeRepository(first)
    know = KnowledgeMemory(
        memory_id="know_survive",
        user_id="u1",
        name="周报流程",
        content="收集→生成→填充",
        knowledge_type="workflow",
    )
    know_repo.save(know)
    conflict = ConflictRecord(
        conflict_id="conf_survive",
        user_id="u1",
        old_memory_id="know_old",
        new_memory_id="know_survive",
        memory_type="knowledge",
        old_content="旧内容",
        new_content="新内容",
        conflict_field="content",
        decision=ConflictDecision.OVERRIDE,
    )
    ConflictRepository(first).save(conflict)
    first.close()

    second = Database(db_path)
    second.init_schema()
    restored = KnowledgeRepository(second).get_by_id("know_survive")
    assert restored is not None
    assert restored.name == "周报流程"
    assert restored.content == "收集→生成→填充"
    restored_conflict = ConflictRepository(second).list_all(status="override")
    assert len(restored_conflict) == 1
    assert restored_conflict[0].result_memory_id == ""
    second.close()
