import type { FactProposal, MemoryCardData, MemoryEvent, ReplaySession, ReplayTurn, ToolCall } from "./types";

const EMAIL = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const PHONE = /(?<!\d)1[3-9]\d{9}(?!\d)/g;
const TOKEN = /\b(?:sk|Bearer)[-_ A-Za-z0-9]{10,}\b/gi;

export function maskForDisplay(value: unknown): unknown {
  if (typeof value === "string") return value.replace(EMAIL, "[REDACTED_EMAIL]").replace(PHONE, "[REDACTED_PHONE]").replace(TOKEN, "[REDACTED_TOKEN]");
  if (Array.isArray(value)) return value.map(maskForDisplay);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, maskForDisplay(item)]));
  return value;
}

function normalizeToolCalls(calls: unknown, turnId: string): ToolCall[] {
  if (!Array.isArray(calls)) return [];
  const normalized = calls.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
      call_id: String(item.call_id || `${turnId}_call_${index + 1}`),
      tool_name: String(item.tool_name || item.name || "unknown_tool"),
      arguments: maskForDisplay(item.arguments ?? {}), result: maskForDisplay(item.result ?? {}),
      status: String(item.status || "success"), sequence: Number(item.sequence ?? index + 1),
      error: item.error ? String(maskForDisplay(item.error)) : "", latency_ms: Number(item.latency_ms ?? 0) || undefined,
    };
  });
  const ids = new Set<string>();
  for (const call of normalized) {
    if (ids.has(call.call_id)) throw new Error(`回合 ${turnId} 存在重复 call_id: ${call.call_id}`);
    ids.add(call.call_id);
  }
  normalized.sort((a, b) => a.sequence - b.sequence);
  normalized.forEach((call, index) => { if (index && call.sequence <= normalized[index - 1].sequence) throw new Error(`回合 ${turnId} 的工具 sequence 必须严格递增`); });
  return normalized;
}

function memoryFromRaw(raw: unknown, usedIds: string[]): MemoryCardData {
  const item = (raw ?? {}) as Record<string, unknown>;
  const memoryId = String(item.memory_id || item.id || `memory_${Math.random().toString(36).slice(2)}`);
  const memoryType = String(item.memory_type || item.type || "knowledge");
  return {
    memory_id: memoryId, memory_type: memoryType,
    title: String(item.title || item.name || (memoryType === "preference" ? "用户偏好" : "相关知识")),
    summary: String(item.summary || item.text || item.content || ""), relevance: Number(item.relevance ?? item.score ?? 0),
    source: String(item.source || item.source_type || "MemoryHub"), level: String(item.level || "长期记忆"),
    scope: typeof item.scope === "string" ? item.scope : JSON.stringify(item.scope || "global"),
    updated_at: item.updated_at ? String(item.updated_at) : undefined,
    tags: Array.isArray(item.tags) ? item.tags.map(String) : [], used: usedIds.includes(memoryId),
    knowledge_type: item.knowledge_type ? String(item.knowledge_type) : undefined,
  };
}

function factFromRaw(raw: unknown): FactProposal {
  const item = (raw ?? {}) as Record<string, unknown>;
  const triple = (item.raw_triple ?? item) as Record<string, unknown>;
  const admission = (item.admission ?? {}) as Record<string, unknown>;
  return {
    proposal_id: String(item.proposal_id || item.id || `proposal_${Date.now()}`), subject: String(triple.subject || ""),
    predicate: String(triple.predicate || ""), object: String(triple.object || triple.object_value || ""),
    evidence: String(triple.evidence || item.evidence || ""), confidence: Number(triple.confidence ?? admission.confidence ?? 0.8),
    admission_reason: String(admission.reason || item.admission_reason || "满足事实候选准入条件"),
    suggested_scope: (item.suggested_scope || "project") as FactProposal["suggested_scope"], status: String(item.status || "proposed"),
  };
}

function turnFromRaw(raw: unknown, index: number): ReplayTurn {
  const item = (raw ?? {}) as Record<string, unknown>;
  const turnId = String(item.turn_id || `turn_${index + 1}`);
  const events = Array.isArray(item.events) ? item.events.map((event) => maskForDisplay(event) as MemoryEvent) : [];
  const eventCalls = events.flatMap((event) => event.tool_calls || []);
  const usedIds = Array.isArray(item.used_memory_ids) ? item.used_memory_ids.map(String) : [];
  return {
    turn_id: turnId, user_message: String(maskForDisplay(item.user_message || item.user || "")),
    retrieval_query: item.retrieval_query ? String(item.retrieval_query) : undefined,
    assistant_message: String(maskForDisplay(item.assistant_message || item.assistant || "")), occurred_at: item.occurred_at ? String(item.occurred_at) : undefined,
    tool_calls: normalizeToolCalls(item.tool_calls ?? eventCalls, turnId),
    candidate_memories: Array.isArray(item.candidate_memories) ? item.candidate_memories.map((memory) => memoryFromRaw(memory, usedIds)) : [],
    used_memory_ids: usedIds, fact_proposals: Array.isArray(item.fact_proposals) ? item.fact_proposals.map(factFromRaw) : [],
    write_summary: Array.isArray(item.write_summary) ? item.write_summary.map(String) : [], latency_ms: Number(item.latency_ms ?? 0) || undefined, events,
  };
}

function turnsFromEvents(events: MemoryEvent[]): ReplayTurn[] {
  const groups = new Map<string, MemoryEvent[]>();
  events.forEach((event) => { if (!event.turn_id) throw new Error(`事件 ${event.event_id} 缺少 turn_id`); groups.set(event.turn_id, [...(groups.get(event.turn_id) || []), event]); });
  return [...groups.entries()].map(([turnId, grouped], index) => {
    const userEvent = grouped.find((event) => event.event_type === "user_message");
    const agentEvent = [...grouped].reverse().find((event) => ["assistant_reply", "agent_response"].includes(event.event_type));
    const usedIds = Array.isArray(agentEvent?.payload?.used_memory_ids) ? (agentEvent?.payload?.used_memory_ids as unknown[]).map(String) : [];
    return turnFromRaw({ turn_id: turnId, user_message: userEvent?.text || String(agentEvent?.payload?.user_message || "导入的用户消息"), assistant_message: agentEvent?.text || "", occurred_at: grouped[0]?.occurred_at, events: grouped, tool_calls: grouped.flatMap((event) => event.tool_calls || []), used_memory_ids: usedIds, candidate_memories: agentEvent?.payload?.candidate_memories || [], fact_proposals: agentEvent?.payload?.fact_proposals || [], write_summary: agentEvent?.payload?.write_summary || [], latency_ms: agentEvent?.payload?.latency_ms }, index);
  });
}

export function parseReplayJson(value: unknown): ReplaySession {
  if (!value || typeof value !== "object") throw new Error("JSON 顶层必须是对象");
  const raw = value as Record<string, unknown>;
  if (raw.schema_version && raw.schema_version !== "conversation-replay/1.0") throw new Error("仅支持 conversation-replay/1.0");
  const events = Array.isArray(raw.events) ? (maskForDisplay(raw.events) as MemoryEvent[]) : [];
  const turns = Array.isArray(raw.turns) ? raw.turns.map(turnFromRaw) : turnsFromEvents(events);
  if (!turns.length) throw new Error("JSON 中没有可回放的 turns 或 events");
  return { schema_version: "conversation-replay/1.0", session_id: String(raw.session_id || events[0]?.session_id || `import_${Date.now()}`), title: String(raw.title || "导入的 Agent 对话"), source: "json", read_only: true, turns, events };
}

const sampleEvent: MemoryEvent = {
  event_id: "evt_demo_001", source_type: "chat", event_type: "assistant_reply", user_id: "default", session_id: "session_weekly_demo", turn_id: "turn_002",
  scene: "office", task_type: "weekly_report", occurred_at: "2026-08-05T10:00:00+08:00", text: "已生成周报。", schema_version: "1.1",
  payload: { user_message: "帮我生成本周项目周报。", used_memory_ids: ["pref_markdown", "know_workflow"] },
};

export const sampleSession: ReplaySession = {
  schema_version: "conversation-replay/1.0", session_id: "session_weekly_demo", title: "周报格式与生成", source: "sample", read_only: true, events: [sampleEvent],
  turns: [
    { turn_id: "turn_001", user_message: "以后项目周报都用 Markdown，先给结论，再补充数据。", assistant_message: "好的，我会把这个格式作为项目周报的长期偏好。", tool_calls: [], candidate_memories: [], used_memory_ids: [], fact_proposals: [], write_summary: ["写入格式偏好：Markdown", "写入结构偏好：结论优先"], latency_ms: 26 },
    { turn_id: "turn_002", user_message: "查一下项目资料和本周日程，帮我生成周报。", assistant_message: "已根据项目文档和本周日程生成周报，并按你的偏好使用 Markdown、将结论放在首段。",
      tool_calls: [
        { call_id: "call_file", tool_name: "file_search", arguments: { query: "XA202612-2 本周进展" }, result: { files: ["技术方案.md", "评测结果.json"], hit_count: 2 }, status: "success", sequence: 1, latency_ms: 12 },
        { call_id: "call_calendar", tool_name: "calendar_query", arguments: { range: "this_week" }, result: { events: ["冲突模块评审", "前端方案讨论"] }, status: "success", sequence: 2, latency_ms: 9 },
        { call_id: "call_writer", tool_name: "report_writer", arguments: { format: "markdown" }, result: { document: "项目周报-0805.md", status: "created" }, status: "success", sequence: 3, latency_ms: 31 },
      ],
      candidate_memories: [
        { memory_id: "pref_markdown", memory_type: "preference", title: "周报使用 Markdown", summary: "项目周报默认使用 Markdown，结论优先。", relevance: .96, source: "用户显式反馈", level: "长期记忆", scope: "office.weekly_report", updated_at: "2 小时前", tags: ["偏好", "周报"], used: true },
        { memory_id: "know_workflow", memory_type: "knowledge", knowledge_type: "workflow", title: "项目周报生成工作流", summary: "读取日历 → 检索项目文件 → 生成报告", relevance: .89, source: "工具执行轨迹", level: "长期记忆", scope: "office.weekly_report", updated_at: "昨天", tags: ["工作流"], used: true },
        { memory_id: "know_template", memory_type: "knowledge", knowledge_type: "template", title: "研发周报模板", summary: "结论、本周进展、风险、下周计划", relevance: .72, source: "知识库模板", level: "中期记忆", scope: "office", updated_at: "3 天前", tags: ["模板"], used: false },
      ], used_memory_ids: ["pref_markdown", "know_workflow"],
      fact_proposals: [{ proposal_id: "proposal_demo_owner", subject: "XA202612-2", predicate: "当前负责人", object: "莫耀华", evidence: "项目成员分工表显示前端交互界面由莫耀华负责。", confidence: .91, admission_reason: "检测到可跨会话复用的项目客观事实", suggested_scope: "project", status: "proposed" }],
      write_summary: ["工作流复用成功次数 +1", "发现 1 条事实候选，等待用户查看"], latency_ms: 52, events: [sampleEvent] },
  ],
};
