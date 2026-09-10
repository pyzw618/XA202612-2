"""Deterministically expand the showcase golden datasets (offline only)."""
from __future__ import annotations
import argparse, json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOMAINS = ["办公", "开发", "运维", "项目管理", "个人偏好"]

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def generate(seed=42, output_dir=ROOT / "datasets"):
    rng = random.Random(seed); output_dir.mkdir(parents=True, exist_ok=True)
    pref_path = output_dir / "preference_golden_v1.json"
    conf_path = output_dir / "conflict_golden_v1.json"
    ret_path = output_dir / "vnext_retrieval_eval.json"
    pref = load(pref_path) if pref_path.exists() else {"samples": []}
    conf = load(conf_path) if conf_path.exists() else {"samples": []}
    ret = load(ret_path) if ret_path.exists() else {"memories": [], "queries": []}
    pref_samples = pref.get("samples", [])[:]
    while len(pref_samples) < 120:
        i = len(pref_samples) + 1; domain = DOMAINS[i % len(DOMAINS)]
        if i % 5 == 0:
            text, out, typ, found = "这句话只是普通项目背景，不记录任何偏好", "", "", False
        else:
            choices = [("请在%s场景使用 Markdown 要点" % domain, "偏好使用 MARKDOWN 格式进行数据输出", "format_preference"),
                       ("开发任务优先使用 Python 工具", "偏好使用 Python 工具", "tool_preference"),
                       ("不要保存密码和定位信息", "禁止持久化保存敏感凭证及位置数据", "safety_preference")]
            text, out, typ = choices[i % len(choices)]; found = True
        pref_samples.append({"sample_id": f"pref_gen_{i:03d}", "input_text": text, "expected_output": out,
                             "expected_type": typ, "expected_found": found, "scene": domain})
    pref["metadata"] = {"dataset_id":"preference_golden_v1","version":"1.1.0","generated_at":"2026-09-10","seed":seed,
                         "sample_count":len(pref_samples),"annotation_rules":"expected_found=false 表示干扰/无偏好，不因未抽取偏好判错"}
    pref["samples"] = pref_samples
    conf_samples = conf.get("samples", [])[:]
    decisions = ["merge", "override", "coexist", "review"]
    while len(conf_samples) < 100:
        i=len(conf_samples)+1; d=DOMAINS[i%len(DOMAINS)]; dec=decisions[i%4]
        old = f"{d}任务使用方案{i%7}"; new = old if dec=="merge" else f"{d}任务改用方案{(i+1)%7}"
        conf_samples.append({"sample_id":f"conf_gen_{i:03d}","old_preference":old,"new_preference":new,
                             "expected_decision":dec if dec in ("merge","override") else "review",
                             "expected_conflict":dec != "merge","scene":d,"decision_type":dec,
                             "support_status":"native" if dec in ("merge","override") else "待支持：当前 resolver 仅稳定覆盖格式偏好"})
    conf["metadata"]={"dataset_id":"conflict_golden_v1","version":"1.1.0","generated_at":"2026-09-10","seed":seed,
                       "sample_count":len(conf_samples),"annotation_rules":"非格式类别标注 support_status，不能将待支持能力伪装成通过"}; conf["samples"]=conf_samples
    memories=ret.get("memories", [])[:]; queries=ret.get("queries", [])[:]; ids={m["memory_id"] for m in memories}
    for q in queries:
        if q.get("token_budget", 2000) < 128:
            q["token_budget"] = 128
    for i in range(len(memories),800):
        mid=f"mem-gen-{i+1:04d}"; tenant="tenant-a" if i%9 else "tenant-b"; user="user-1" if tenant=="tenant-a" else "user-x"
        memories.append({"memory_id":mid,"tenant_id":tenant,"user_id":user,"memory_type":"SEMANTIC","layer":"LONG_TERM","scope_level":"PROJECT","scope":f"PROJECT:proj-{i%12}","content_version":1,"evolution_status":"ACTIVE","content":{"text":f"{DOMAINS[i%5]}知识条目 {i+1}，包含相似背景与约束"},"score":round(.55+(i%40)/100,3),"source_ids":["authority"]})
    base_len=len(queries)
    while len(queries)<250:
        i=len(queries); m=memories[(i*7+3)%len(memories)]; qid=f"q-gen-{i+1:04d}"
        q={"query_id":qid,"query":f"请查找{DOMAINS[i%5]}中关于条目 {m['memory_id']} 的说明","tenant_id":m["tenant_id"],"user_id":m["user_id"],"expected_intent":"SEMANTIC_FACT","intent_hint":"SEMANTIC_FACT","expected_candidate_memory_ids":[m["memory_id"]],"expected_selected_memory_ids":[m["memory_id"]],"expected_context_ids":[m["memory_id"]],"forbidden_memory_ids":[],"channel_relevance":{"vector":[m["memory_id"]],"keyword":[m["memory_id"]]}}
        if i%10==0: q.update({"token_budget":128,"active_constraints":["关键约束"],"required_constraints":["关键约束"],"scenario":"token_budget"})
        queries.append(q)
    # Explicitly retain a multi-candidate Scope example: both IDs are valid
    # retrieval candidates, while only the task-scoped item is acceptable.
    if queries:
        q = queries[-1]; other = memories[(len(memories)-1)]
        q["expected_candidate_memory_ids"] = [q["expected_selected_memory_ids"][0], other["memory_id"]]
        q["scope_scenario"] = "scope_conflict"
    ret["metadata"]={"schema_version":"vnext/v2","version":"1.1.0","generated_at":"2026-09-10","seed":seed,"top_k":5,"sample_count":len(queries),"memory_count":len(memories),"annotation_rules":"candidate 是召回候选；selected/context 是过滤预算后的最终结果"}; ret["memories"]=memories; ret["queries"]=queries
    for path,data in ((pref_path,pref),(conf_path,conf),(ret_path,ret)): path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--seed",type=int,default=42); p.add_argument("--output-dir",type=Path,default=ROOT/"datasets"); a=p.parse_args(); generate(a.seed,a.output_dir)
