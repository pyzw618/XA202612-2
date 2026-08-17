"""临时验证脚本：启动完整 app，逐个验证 management_api 新增接口。

用法: py12 python scripts/verify_management_api.py
"""
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

tmp = tempfile.mkdtemp(prefix="memoryhub_verify_")
tmp_posix = tmp.replace("\\", "/")
db = os.path.join(tmp, "memoryhub.db").replace("\\", "/")
cfg = os.path.join(tmp, "config.yaml")
os.makedirs(os.path.join(tmp, "vector_index"), exist_ok=True)

with open(cfg, "w", encoding="utf-8") as f:
    f.write(f"""runtime:
  mode: development
storage:
  db_path: "{db}"
  vector_index_path: "{tmp_posix}/vector_index"
  evidence_path: "{tmp_posix}/evidence"
  cache_max_size: 1000
retrieval:
  default_top_k: 5
  vector_weight: 0.6
  keyword_weight: 0.3
  metadata_weight: 0.1
  rerank_enabled: true
  cache_ttl_seconds: 300
llm:
  api_base: "https://api.openai.com/v1"
  api_key: ""
  model: "gpt-4o-mini"
embedding:
  provider: "mock"
  dimension: 1024
vector_engine:
  provider: "faiss"
safety:
  user_rules:
    enabled: false
  audit:
    enabled: false
  quarantine:
    enabled: false
debug: true
""")

os.environ["MEMORYHUB_CONFIG"] = cfg

from fastapi.testclient import TestClient  # noqa: E402
from memoryhub.app import create_app  # noqa: E402
from memoryhub.adapter.schemas import (  # noqa: E402
    EventQuality,
    KnowledgeMemory,
    MemoryEvent,
    MemoryStatus,
    PreferenceMemory,
    QualityStatus,
    SceneScope,
    SourceType,
)
from memoryhub.core.fact.models import Fact, MemoryScope  # noqa: E402


def _mk_event(state, event_id):
    from memoryhub.adapter.schemas import canonical_sha256
    event = MemoryEvent(
        event_id=event_id,
        source_type=SourceType.USER_BEHAVIOR,
        event_type="user_message",
        user_id="default",
        session_id="sess_v1",
        scene="office",
        task_type="office.weekly_report",
        occurred_at="2026-08-01T10:00:00Z",
        text="帮我写周报",
        payload={"k": "v"},
        source_hash=canonical_sha256({"event_id": event_id}),
        quality=EventQuality(
            score=0.9, status=QualityStatus.ACCEPTED,
            completeness=0.9, validity=0.9, consistency=0.9, freshness=0.9,
        ),
    )
    return event

app = create_app()

passed = 0
failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {extra}")


with TestClient(app) as client:
    st = app.state

    # ---- 播种数据 ----
    pref = PreferenceMemory(
        memory_id="pref_test1", user_id="default", text="周报使用 Markdown 格式",
        scope=SceneScope(scene="office", task_type="office.weekly_report"),
        preference_type="format_preference",
    )
    st.pref_repo.save(pref)
    pref2 = PreferenceMemory(
        memory_id="pref_test2", user_id="default", text="回复邮件保持简洁",
        scope=SceneScope(scene="office"),
    )
    st.pref_repo.save(pref2)
    know = KnowledgeMemory(
        memory_id="know_test1", user_id="default", name="项目周报生成流程",
        content="三步生成周报", steps=["收集数据", "生成草稿", "审阅发送"],
        tools=["file_search", "report_writer"], knowledge_type="workflow",
    )
    st.know_repo.save(know)
    st.fact_store.insert_fact(Fact(
        fact_id="fact_test1", subject_id="entity:person:a_1", predicate_id="pred:works_at_x",
        object_id="entity:org:b_1", object_value="银河麒麟", source_text="小明在银河麒麟工作",
        source_id="evt_1", observed_at="2026-08-01T00:00:00+00:00", confidence=0.9,
        user_id="default", scope=MemoryScope.GLOBAL.value,
    ))

    # 1. PATCH 单条状态流转（归档）
    r = client.patch("/api/memory/memories/pref_test1/status",
                     json={"user_id": "default", "status": "archived"})
    check("PATCH status -> archived", r.status_code == 200 and r.json()["status"] == "archived", r.text)
    check("archived reflected in list", any(
        m["memory_id"] == "pref_test1" for m in client.get("/api/memory/preferences?status=archived").json()
    ))

    # 2. PATCH 非法状态 -> 422
    r = client.patch("/api/memory/memories/pref_test1/status",
                     json={"user_id": "default", "status": "bogus"})
    check("PATCH invalid status -> 422", r.status_code == 422, r.text)

    # 3. PATCH 不存在 -> 404
    r = client.patch("/api/memory/memories/nope_123/status",
                     json={"user_id": "default", "status": "active"})
    check("PATCH missing memory -> 404", r.status_code == 404, r.text)

    # 4. 批量状态流转（恢复为 active）
    r = client.post("/api/memory/memories/status",
                    json={"user_id": "default", "memory_ids": ["pref_test1", "pref_test2"], "status": "active"})
    check("batch status -> applied 2",
          r.status_code == 200 and r.json()["applied"] == 2, r.text)

    # 5. 批量软删除
    r = client.post("/api/memory/memories/delete",
                    json={"user_id": "default", "memory_ids": ["pref_test2", "know_test1"], "cascade": True})
    body = r.json()
    check("batch delete -> 2 deleted", r.status_code == 200 and body["deleted_count"] == 2, r.text)
    forget_record_id = body.get("record_id")
    check("batch delete creates forget record", bool(forget_record_id), r.text)

    # 6. 遗忘历史详情
    r = client.get(f"/api/memory/forget/history/{forget_record_id}")
    check("forget history detail -> 200",
          r.status_code == 200 and r.json()["record"]["record_id"] == forget_record_id, r.text)
    check("forget history detail resolves memories",
          len(r.json()["memories"]) == 2 and r.json()["memories"][0]["memory_type"] in ("preference", "knowledge"), r.text)

    # 7. 硬删除（回收站彻底删除）
    r = client.delete("/api/memory/memories/pref_test1?hard=true&user_id=default")
    check("hard delete -> 200 hard=true", r.status_code == 200 and r.json()["hard"] is True, r.text)
    r = client.get("/api/memory/preferences/pref_test1")
    check("hard-deleted memory gone -> 404", r.status_code == 404, r.text)

    # 8. 知识版本历史
    r = client.get("/api/memory/knowledge/know_test1/versions")
    check("knowledge versions -> 200", r.status_code == 200 and isinstance(r.json(), list), r.text)

    # 9. 健康度批量查询
    r = client.get("/api/memory/memories/health?user_id=default&status=active")
    hb = r.json()
    check("health bulk -> 200 with items", r.status_code == 200 and hb["total"] >= 1, r.text)
    check("health bulk has factors", all(k in hb["items"][0] for k in ("health_score", "time_decay", "usage_frequency")), r.text)

    # 10. 生命周期阈值
    r = client.get("/api/memory/lifecycle/settings")
    check("lifecycle settings -> 200", r.status_code == 200 and "auto_forget" in r.json(), r.text)

    # 11. 生命周期检查 + 自动遗忘（应能运行，返回 stats 键）
    r = client.post("/api/memory/lifecycle/check")
    check("lifecycle check -> stats", r.status_code == 200 and "promoted" in r.json(), r.text)
    r = client.post("/api/memory/lifecycle/auto-forget")
    check("auto-forget -> stats", r.status_code == 200 and "archived" in r.json(), r.text)

    # 12. 全量事件列表（先写一个事件）
    st.event_repo.save(_mk_event(st, "evt_v1"))
    r = client.get("/api/memory/events?user_id=default&limit=10&offset=0")
    check("events list -> 200 with total", r.status_code == 200 and r.json()["total"] >= 1, r.text)

    # 13. 冲突分页（旧接口兼容 + 分页结构）
    r = client.get("/api/memory/conflicts?status=pending")
    check("conflicts list (no page) -> list", isinstance(r.json(), list), r.text)
    r = client.get("/api/memory/conflicts?status=&page=1&size=5")
    check("conflicts page -> object", r.status_code == 200 and "total" in r.json() and "items" in r.json(), r.text)

    # 14. 审计日志（当前 config 未启用 -> 503 稳定码）
    r = client.get("/api/memory/safety/audit-logs")
    check("audit-logs (disabled) -> 503", r.status_code == 503, r.text)
    r = client.get("/api/memory/safety/quarantine")
    check("quarantine (disabled) -> 503", r.status_code == 503, r.text)

    # 15. 评测：preference 未实现 -> 501；retrieval 缺数据集 -> 400
    r = client.post("/api/memory/evaluate/preference")
    check("evaluate preference -> 501", r.status_code == 501, r.text)
    r = client.post("/api/memory/evaluate/retrieval")
    check("evaluate retrieval (no dataset) -> 400", r.status_code == 400, r.text)

    # 16. 系统状态 / 配置
    r = client.get("/api/memory/system/status")
    check("system status -> 200", r.status_code == 200 and "storage" in r.json() and "safety" in r.json(), r.text)
    r = client.get("/api/memory/system/config")
    c = r.json()
    check("system config -> no api_key leaked",
          r.status_code == 200 and "api_key" not in str(c), r.text)

print(f"\nRESULT: passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
