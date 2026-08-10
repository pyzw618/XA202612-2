"""复杂隐晦轨迹的真实 LLM 知识提取演示。
需要设置 RUN_LLM_API_TESTS=1 与 DASHSCOPE_API_KEY 后运行。
"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from memoryhub.core.knowledge.extractor import KnowledgeExtractor
from tests.test_knowledge.test_knowledge_api import _call_dashscope_api

OUT = Path(__file__).with_name("complex_llm_pipeline_result.json")
QUALITY = {"score": 0.94, "status": "accepted", "completeness": 0.95, "validity": 1.0, "consistency": 0.9, "freshness": 0.9, "issues": []}

def event(event_id, event_type, text, payload, occurred_at):
    return {"event_id": event_id, "source_type": "tool_result", "event_type": event_type, "user_id": "demo-user", "session_id": "complex-session", "turn_id": "turn-17", "scene": "finance_ops", "task_type": "finance.monthly_close", "occurred_at": occurred_at, "text": text, "payload": payload, "tool_calls": [], "schema_version": "1.1", "source_hash": event_id * 64, "redactions": [], "quality": QUALITY}

EVENTS = [
    event("a", "task_trajectory", "月末关账已完成，但中间有一笔跨境费用需要复核", {"task_name": "月末关账与异常费用复核", "result": "账套已提交，异常费用待确认"}, "2026-07-30T01:00:00Z"),
    event("b", "tool_call", "从报销系统导出本月费用，发现一笔金额和币种不一致", {"tool_name": "expense_export", "input": "本月跨境费用", "output": "EUR 12,480；发票记录为 USD 13,420", "status": "success"}, "2026-07-30T01:02:00Z"),
    event("c", "tool_call", "先查汇率快照，再对照发票附件和采购合同，不直接改账", {"tool_name": "fx_snapshot", "input": "2026-07-29 EUR/USD", "output": "1.084", "status": "success"}, "2026-07-30T01:04:00Z"),
    event("d", "tool_call", "系统提示供应商名称有两个近似匹配，人工打开原始附件确认税号", {"tool_name": "invoice_match", "input": "供应商+税号+合同号", "output": "候选 2 条，需人工确认", "status": "success"}, "2026-07-30T01:06:00Z"),
    event("e", "tool_call", "确认后把差异放入待摊费用，不覆盖原始记录，并在备注中记录依据", {"tool_name": "ledger_post", "input": "差异调整分录", "output": "草稿已生成，等待复核", "status": "success"}, "2026-07-30T01:09:00Z"),
    event("f", "user_feedback", "财务主管要求：遇到币种或供应商不一致时必须保留原始值并升级人工复核", {"text": "保留原值、记录依据、异常升级", "feedback_type": "policy"}, "2026-07-30T01:12:00Z"),
]

class DashScopeKnowledgeClient:
    def is_available(self): return True
    def _call(self, prompt):
        response = _call_dashscope_api(prompt)
        choices = response.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else "") or ""
        return content
    def generate(self, prompt: str, system_prompt: str = "", **kwargs):
        return type("Response", (), {"content": self._call(prompt), "model": "qwen3.7-flash"})()
    def generate_json(self, prompt: str, schema: dict, system_prompt: str = ""):
        text = self._call(prompt + "\n????? JSON ????? Markdown?")
        text = text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(text)

def main():
    Path(__file__).with_name("complex_llm_input.json").write_text(json.dumps(EVENTS, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = "??????????????????????????????????????????????????????????\n" + json.dumps(EVENTS, ensure_ascii=False)
    # 先用 test_knowledge_api.py 的同一 API helper 做一次原始 API 调用，保存模型原文。
    raw_api = _call_dashscope_api(prompt)
    extractor = KnowledgeExtractor(llm_client=DashScopeKnowledgeClient())
    knowledge = extractor.extract_from_trajectory(EVENTS)
    output = {"input_events": EVENTS, "api_response": raw_api, "knowledge": [item.model_dump(mode="json") for item in knowledge]}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {OUT}")
    for item in knowledge: print(item.knowledge_type.value, item.name, item.steps)

if __name__ == "__main__": main()



