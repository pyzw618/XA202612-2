"""Offline integrity checks for showcase datasets."""
import json
from pathlib import Path

def validate(root=Path(__file__).parent / "datasets"):
    pref=json.loads((root/"preference_golden_v1.json").read_text(encoding="utf-8")); conf=json.loads((root/"conflict_golden_v1.json").read_text(encoding="utf-8")); ret=json.loads((root/"vnext_retrieval_eval.json").read_text(encoding="utf-8"))
    memories={m["memory_id"]:m for m in ret["memories"]}; assert len(memories)==len(ret["memories"])>=800
    assert len(pref["samples"])>=120 and len(conf["samples"])>=100 and len(ret["queries"])>=250
    for q in ret["queries"]:
        c=set(q.get("expected_candidate_memory_ids",q.get("expected_memory_ids",[]))); s=set(q.get("expected_selected_memory_ids",q.get("expected_memory_ids",[]))); x=set(q.get("expected_context_ids",[])); f=set(q.get("forbidden_memory_ids",[]))
        assert s<=c and not s&f
        for mid in c|s|x|f: assert mid in memories
        for mid in c|s|x|f: assert memories[mid]["tenant_id"]==q.get("tenant_id","tenant-a") or mid in f
    assert any(q.get("scenario")=="token_budget" for q in ret["queries"])
    assert any(len(q.get("expected_candidate_memory_ids",[]))>len(q.get("expected_selected_memory_ids",[])) for q in ret["queries"])
    return {"preferences":len(pref["samples"]),"conflicts":len(conf["samples"]),"queries":len(ret["queries"]),"memories":len(memories)}

if __name__ == "__main__": print(validate())
