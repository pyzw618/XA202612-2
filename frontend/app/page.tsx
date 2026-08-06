"use client";

import { useEffect, useRef, useState } from "react";
import { memoryApi } from "./api";
import { parseReplayJson, sampleSession } from "./replay";
import type { FactProposal, MemoryCardData, ReplaySession, ReplayTurn, ToolCall, ViewId } from "./types";

type Row = Record<string, unknown>;

const navGroups: { label: string; items: { id: ViewId; icon: string; label: string; badge?: string }[] }[] = [
  { label: "工作台", items: [
    { id: "chat", icon: "⌁", label: "对话" }, { id: "ingestion", icon: "⇥", label: "数据记录" }, { id: "retrieval", icon: "⌕", label: "检索记录" },
  ] },
  { label: "记忆管理", items: [
    { id: "preferences", icon: "≡", label: "偏好记忆" }, { id: "facts", icon: "●", label: "事实记忆", badge: "1" },
    { id: "knowledge", icon: "▤", label: "知识记忆" }, { id: "conflicts", icon: "⚠", label: "冲突处理", badge: "2" }, { id: "forget", icon: "⌫", label: "遗忘管理" },
  ] },
  { label: "系统能力", items: [
    { id: "safety", icon: "◇", label: "安全规则" }, { id: "evaluation", icon: "▥", label: "评测报告" }, { id: "settings", icon: "⚙", label: "系统设置" },
  ] },
];

const fallbackData: Record<string, Row[]> = {
  preferences: [
    { memory_id: "pref_markdown", preference_type: "格式偏好", text: "项目周报默认使用 Markdown，先给结论再补充数据。", confidence: .96, scope: "office.weekly_report", level: "long", status: "active", updated_at: "2026-08-05 09:24" },
    { memory_id: "pref_tool", preference_type: "工具选择", text: "处理表格时优先使用本地数据分析工具。", confidence: .85, scope: "office.data_analysis", level: "mid", status: "active", updated_at: "2026-08-02 14:08" },
  ],
  facts: [{ fact_id: "fact_demo_01", subject_id: "XA202612-2", predicate_id: "current_owner", object_value: "莫耀华", confidence: .91, scope: "project", project_id: "XA202612-2", status: "active", observed_at: "2026-08-05 10:12" }],
  conflicts: [{ conflict_id: "conf_demo_01", old_content: "周报使用 Word 格式", new_content: "周报使用 Markdown 格式", conflict_field: "output_format", decision: "pending", reason: "检测到同一场景下的格式偏好更新" }],
  workflow: [{ memory_id: "know_workflow", knowledge_type: "workflow", name: "项目周报生成工作流", content: "读取日历、检索项目资料并生成周报", steps: ["读取本周日历", "检索项目文件", "汇总任务进展", "生成 Markdown 周报"], tools: ["calendar_query", "file_search", "report_writer"], confidence: .89, success_count: 7, total_count: 8, scope: "office.weekly_report" }],
  template: [{ memory_id: "know_template", knowledge_type: "template", name: "研发项目周报模板", content: "适用于研发项目的结构化周报", template_body: "# 核心结论\n{{summary}}\n\n## 本周进展\n{{progress}}\n\n## 风险与计划\n{{risks}}", confidence: .86, success_count: 4, total_count: 4, scope: "office.weekly_report" }],
};

const labels: Record<ViewId, [string, string]> = {
  chat: ["对话", ""],
  ingestion: ["数据接入记录", "从原始事件到安全过滤、标准化和记忆抽取"], retrieval: ["检索记录", "查看候选记忆与 Agent 实际引用的区别"],
  preferences: ["偏好管理", "查看系统形成的用户偏好及适用范围"], facts: ["事实管理", "管理已提交事实和待裁决候选"],
  knowledge: ["知识管理", "只展示可复用工作流与模板"], conflicts: ["冲突处理", "对新旧知识冲突进行可回溯裁决"],
  forget: ["遗忘管理", "自然语言预览、确认与软删除历史"], safety: ["安全规则", "敏感信息过滤与本地安全策略"],
  evaluation: ["评测报告", "竞赛指标与测试结果设计预览"], settings: ["系统设置", "Agent 适配与运行参数"],
};

function text(value: unknown, fallback = "—") { return value === undefined || value === null || value === "" ? fallback : typeof value === "string" ? value : JSON.stringify(value); }
function pct(value: unknown) { const n = Number(value || 0); return `${Math.round(n <= 1 ? n * 100 : n)}%`; }

function ToolCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  return <article className={`tool-card ${open ? "expanded" : ""}`}>
    <button className="tool-summary" onClick={() => setOpen(!open)}>
      <span className="tool-order">{call.sequence}</span><span className="tool-name"><strong>{call.tool_name}</strong><small>{call.status === "success" ? "执行成功" : call.status}</small></span>
      <time>{call.latency_ms ? `${call.latency_ms}ms` : ""}</time><span className={`tool-status ${call.status}`} /><span className="chevron">⌄</span>
    </button>
    {open && <div className="tool-details"><div><label>调用参数</label><pre>{JSON.stringify(call.arguments, null, 2)}</pre></div><div><label>安全过滤后的返回内容</label><pre>{JSON.stringify(call.result, null, 2)}</pre></div>{call.error && <p className="error-text">{call.error}</p>}</div>}
  </article>;
}

function MemoryCard({ memory }: { memory: MemoryCardData }) {
  return <article className={`result-card ${memory.used ? "used" : "candidate"}`}>
    <div className="result-top"><span className={`memory-type ${memory.memory_type}`}>{memory.memory_type === "preference" ? "偏好" : memory.knowledge_type === "template" ? "模板" : "知识"}</span><span className={`usage-tag ${memory.used ? "is-used" : "not-used"}`}>{memory.used ? "已使用" : "候选"}</span><strong>{pct(memory.relevance)}</strong></div>
    <h4>{memory.title}</h4><p>{memory.summary}</p><div className="result-meta"><span>{memory.source}</span><span>{memory.level}</span><span>{memory.updated_at || "刚刚更新"}</span></div>
    <div className="tag-row">{(memory.tags || []).map((tag) => <span key={tag}>{tag}</span>)}<span>{memory.scope}</span></div>
  </article>;
}

function FactModal({ proposal, onClose, onDone }: { proposal: FactProposal; onClose: () => void; onDone: (message: string) => void }) {
  const [tab, setTab] = useState<"propose" | "commit">("propose"); const [scope, setScope] = useState(proposal.suggested_scope || "project");
  const [projectId, setProjectId] = useState("XA202612-2"); const [resolution, setResolution] = useState("replace"); const [busy, setBusy] = useState(false);
  async function decide(decision: "commit" | "reject") {
    setBusy(true);
    try {
      if (proposal.proposal_id.startsWith("proposal_demo")) { onDone(decision === "commit" ? "演示候选已提交给 Agent" : "演示候选已忽略"); return; }
      await memoryApi.decide(proposal.proposal_id, { action_type: decision === "commit" ? "fact_commit" : "fact_reject", decision, payload: decision === "commit" ? { scope, project_id: scope === "project" ? projectId : null, conflict_decision: resolution } : { reason: "用户在前端忽略" } });
      onDone(decision === "commit" ? "裁决已提交给 Agent" : "候选已忽略");
    } catch (error) { onDone(error instanceof Error ? error.message : "提交失败"); } finally { setBusy(false); }
  }
  return <div className="modal-backdrop" onMouseDown={onClose}><section className="modal" onMouseDown={(event) => event.stopPropagation()}>
    <header className="modal-head"><div><h2>确认事实</h2></div><button onClick={onClose}>×</button></header>
    <div className="modal-tabs"><button className={tab === "propose" ? "active" : ""} onClick={() => setTab("propose")}>候选内容</button><button className={tab === "commit" ? "active" : ""} onClick={() => setTab("commit")}>提交设置</button></div>
    <div className="modal-body">{tab === "propose" ? <>
      <div className="triple"><span>{proposal.subject}</span><b>{proposal.predicate}</b><span>{proposal.object}</span></div>
      <div className="proposal-grid"><div><label>证据</label><p>{proposal.evidence}</p></div><div><label>置信度</label><strong>{pct(proposal.confidence)}</strong></div><div><label>准入理由</label><p>{proposal.admission_reason}</p></div><div><label>建议作用域</label><p>{proposal.suggested_scope === "global" ? "全局" : "项目"}</p></div></div>
      <p className="modal-note">确认前不会写入事实库。</p>
    </> : <>
      <label className="input-label">作用域</label><div className="choice-row"><button className={scope === "global" ? "active" : ""} onClick={() => setScope("global")}>全局</button><button className={scope === "project" ? "active" : ""} onClick={() => setScope("project")}>项目</button></div>
      {scope === "project" && <input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="项目 ID" />}
      <label className="input-label">若发生冲突</label><select value={resolution} onChange={(event) => setResolution(event.target.value)}><option value="replace">替换旧事实</option><option value="keep">保留旧事实</option><option value="merge">合并</option><option value="coexist">共存</option><option value="pending">待审</option></select>
      <p className="modal-note">提交后由 Agent 完成写入。</p>
    </>}</div>
    <footer className="modal-actions"><button className="secondary" disabled={busy} onClick={() => decide("reject")}>忽略</button>{tab === "propose" ? <button onClick={() => setTab("commit")}>继续设置</button> : <button disabled={busy} onClick={() => decide("commit")}>{busy ? "提交中…" : "提交给 Agent"}</button>}</footer>
  </section></div>;
}

function Conversation({ turn }: { turn: ReplayTurn }) {
  return <div className="conversation-turn"><div className="time-divider"><span>{turn.occurred_at || "当前回放"}</span></div>
    <div className="chat-row user"><div className="user-avatar">你</div><div className="bubble"><p>{turn.user_message}</p></div></div>
    {turn.tool_calls.length > 0 && <div className="tool-run"><div className="tool-run-title"><span>⌘</span><div><strong>工具调用</strong><small>{turn.tool_calls.length} 项</small></div></div>{turn.tool_calls.map((call) => <ToolCard key={call.call_id} call={call} />)}</div>}
    <div className="chat-row agent"><div className="chat-avatar">M</div><div className="bubble"><p>{turn.assistant_message}</p><div className="answer-meta"><span>MemoryHub Agent</span><span>{turn.latency_ms ? `${turn.latency_ms}ms` : ""}</span></div></div></div>
    {(turn.write_summary || []).length > 0 && <div className="write-summary"><strong>记忆更新</strong>{turn.write_summary?.map((item) => <span key={item}>✓ {item}</span>)}</div>}
  </div>;
}

function ChatView({ session, turnIndex, setTurnIndex, onProposal, executedTurns, busy, onExecute }: { session: ReplaySession; turnIndex: number; setTurnIndex: (index: number) => void; onProposal: (proposal: FactProposal) => void; executedTurns: Set<number>; busy: boolean; onExecute: () => void }) {
  const threadRef = useRef<HTMLDivElement>(null);
  const turn = session.turns[turnIndex] || session.turns[0];
  const executed = executedTurns.has(turnIndex);
  const visibleTurns = session.turns.slice(0, turnIndex + 1).map((item, index) => {
    if (executedTurns.has(index)) return item;
    const external = item.tool_calls.filter((call) => !call.tool_name.startsWith("memory_") && !["preference_extract", "preference_propose", "fact_propose", "conflict_detect", "template_extract"].includes(call.tool_name));
    return { ...item, tool_calls: external, write_summary: [] };
  });
  const visibleMemories = executed ? turn.candidate_memories : [];
  const used = visibleMemories.filter((item) => item.used); const candidates = visibleMemories.filter((item) => !item.used);
  useEffect(() => { const node = threadRef.current; if (node) node.scrollTop = node.scrollHeight; }, [turnIndex, executedTurns]);
  return <div className="chat-workspace">
    <aside className="turn-list session-list"><div className="turn-list-head"><strong>会话记录</strong><span>1 条</span></div><button className="active"><span>M</span><div><strong>{session.title}</strong><small>{session.turns.length} 轮 · {executedTurns.size} 轮已执行</small></div></button></aside>
    <section className="conversation-panel"><div className="playback-bar"><div><strong>当前第 {turnIndex + 1} / {session.turns.length} 轮</strong><span className={executed ? "step-done" : "step-waiting"}>{executed ? "已真实执行" : "等待执行"}</span></div><div className="playback-track"><i style={{ width: `${((turnIndex + (executed ? 1 : 0)) / session.turns.length) * 100}%` }} /></div><div className="playback-actions"><button disabled={turnIndex === 0 || busy} onClick={() => setTurnIndex(turnIndex - 1)}>上一轮</button><button className="execute-step" disabled={busy} onClick={onExecute}>{busy ? "执行中…" : executed ? "重新检索本轮" : "执行当前轮"}</button><button disabled={turnIndex >= session.turns.length - 1 || busy} onClick={() => setTurnIndex(turnIndex + 1)}>下一轮</button></div></div><div ref={threadRef} className="conversation-scroll conversation-thread">{visibleTurns.map((item) => <Conversation key={item.turn_id} turn={item} />)}</div><div className="chat-composer"><textarea placeholder="这是同一个会话，使用上方按钮继续下一轮" disabled /><button disabled>发送</button></div></section>
    <aside className="activity-panel"><div className="activity-title"><div><h3>真实记忆结果</h3></div><span className="mode-chip">{executed ? "已执行" : "待执行"}</span></div>
      <div className="activity-metrics"><div><strong>{used.length}</strong><span>已使用</span></div><div><strong>{candidates.length}</strong><span>候选</span></div><div><strong>{turn.fact_proposals.length}</strong><span>待确认</span></div></div>
      <div className="activity-section"><div className="section-head"><strong>本轮使用</strong><span>{used.length}</span></div>{used.length ? used.map((item) => <MemoryCard key={item.memory_id} memory={item} />) : <p className="empty-state">没有使用记忆</p>}</div>
      <div className="activity-section"><div className="section-head"><strong>其他候选</strong><span>{candidates.length}</span></div>{candidates.length ? candidates.map((item) => <MemoryCard key={item.memory_id} memory={item} />) : <p className="empty-state">没有其他候选</p>}</div>
      {executed && turn.fact_proposals.length > 0 && <div className="activity-section"><div className="section-head"><strong>待确认事实</strong><span>{turn.fact_proposals.length}</span></div>{turn.fact_proposals.map((proposal) => <button className="proposal-card" key={proposal.proposal_id} onClick={() => onProposal(proposal)}><span>尚未写入</span><strong>{proposal.subject} · {proposal.predicate}</strong><small>查看详情</small></button>)}</div>}
    </aside>
  </div>;
}

function Records({ kind, rows }: { kind: "preferences" | "facts" | "conflicts"; rows: Row[] }) {
  const configs = {
    preferences: ["偏好类型", "内容", "置信度", "作用域", "状态"], facts: ["主体", "谓词", "值", "置信度", "作用域"], conflicts: ["旧知识", "新知识", "冲突字段", "状态", "原因"],
  }[kind];
  return <div className="table-card"><div className="record-head">{configs.map((item) => <span key={item}>{item}</span>)}</div>{rows.map((row, index) => {
    const values = kind === "preferences" ? [row.preference_type, row.text, pct(row.confidence), row.scope, row.status] : kind === "facts" ? [row.subject_id || row.subject, row.predicate_id || row.predicate, row.object_value || row.object, pct(row.confidence), row.project_id || row.scope] : [row.old_content, row.new_content, row.conflict_field, row.decision || row.status, row.reason];
    return <div className="record-row" key={text(row.memory_id || row.fact_id || row.conflict_id || index)}>{values.map((value, i) => <span key={i}>{text(value)}</span>)}</div>;
  })}</div>;
}

function KnowledgeView({ type, setType, rows }: { type: "workflow" | "template"; setType: (type: "workflow" | "template") => void; rows: Row[] }) {
  return <><div className="filter-row"><div className="segmented"><button className={type === "workflow" ? "active" : ""} onClick={() => setType("workflow")}>工作流</button><button className={type === "template" ? "active" : ""} onClick={() => setType("template")}>模板</button></div><span>case 数据保持兼容，但不在第一版展示</span></div>
    <div className="knowledge-grid">{rows.length ? rows.map((row, index) => <article className="knowledge-card" key={text(row.memory_id || index)}><div className="knowledge-top"><span>{type === "workflow" ? "工作流" : "模板"}</span><strong>{pct(row.confidence)}</strong></div><h3>{text(row.name || row.title)}</h3><p>{text(row.content)}</p>{type === "workflow" ? <div className="workflow-detail"><label>执行步骤</label>{(Array.isArray(row.steps) ? row.steps : []).map((step, i) => <span key={String(step)}><b>{i + 1}</b>{String(step)}</span>)}<label>调用工具</label><div className="tag-row">{(Array.isArray(row.tools) ? row.tools : []).map((tool) => <span key={String(tool)}>{String(tool)}</span>)}</div></div> : <pre className="template-preview">{text(row.template_body || row.content)}</pre>}<footer>复用 {text(row.success_count, "0")} 次 · {text(row.scope)}</footer></article>) : <p className="large-empty">当前还没有{type === "workflow" ? "工作流" : "模板"}记忆。Agent 成功复用后会在这里形成记录。</p>}</div>
  </>;
}

function RetrievalView({ onToast }: { onToast: (message: string) => void }) {
  const [query, setQuery] = useState("项目周报格式"); const [items, setItems] = useState<MemoryCardData[]>(sampleSession.turns[1].candidate_memories);
  async function search() { try { const result = await memoryApi.search(query); const raw = (result.results || []) as Row[]; setItems(raw.map((item, index) => ({ memory_id: text(item.memory_id || index), memory_type: text(item.memory_type, "knowledge"), title: text(item.title || item.name, "检索结果"), summary: text(item.text || item.content || item.summary), relevance: Number(item.score || item.relevance || 0), source: text(item.source, "MemoryHub"), scope: text(item.scope, "global"), used: false }))); } catch (error) { onToast(error instanceof Error ? `${error.message}，展示演示结果` : "检索失败"); } }
  return <><div className="search-box"><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && search()} /><button onClick={search}>检索</button></div><div className="retrieval-explain">这里显示完整候选集；只有 Agent 回合返回的 used_memory_ids 才会标记为“实际引用”。</div><div className="retrieval-grid">{items.length ? items.map((item) => <MemoryCard key={item.memory_id} memory={item} />) : <p className="large-empty">未找到相关记忆，请尝试换词或放宽筛选。</p>}</div></>;
}

function ForgetView({ onToast }: { onToast: (message: string) => void }) {
  const [tab, setTab] = useState<"precise" | "history">("precise"); const [instruction, setInstruction] = useState("忘记项目周报使用 Word 格式的旧偏好"); const [candidates, setCandidates] = useState<Row[]>([]); const [history, setHistory] = useState<Row[]>([]);
  async function preview() { try { const result = await memoryApi.forgetPreview(instruction); setCandidates(((result.candidates || result.matches || []) as Row[])); if (!((result.candidates || result.matches || []) as Row[]).length) setCandidates([{ memory_id: "pref_word_old", summary: "项目周报使用 Word 格式", type: "preference", score: .92 }]); } catch { setCandidates([{ memory_id: "pref_word_old", summary: "项目周报使用 Word 格式", type: "preference", score: .92 }]); onToast("后端未连接，正在展示安全预览示例"); } }
  async function confirm() { const ids = candidates.map((item) => text(item.memory_id || item.id)).filter((id) => id !== "—"); try { await memoryApi.decide(`forget_${Date.now()}`, { action_type: "forget_commit", decision: "commit", payload: { user_id: "default", instruction, target_memory_ids: ids, cascade: true } }); setCandidates([]); onToast("遗忘裁决已由 Agent 执行"); } catch (error) { onToast(error instanceof Error ? error.message : "遗忘提交失败"); } }
  useEffect(() => { if (tab === "history") memoryApi.forgetHistory().then((rows) => setHistory(rows as Row[])).catch(() => setHistory([])); }, [tab]);
  return <><div className="forget-tabs"><button className={tab === "precise" ? "active" : ""} onClick={() => setTab("precise")}>精准遗忘</button><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>遗忘历史</button><button disabled>待审查 · 接口待接</button><button disabled>回收站 · 接口待接</button></div>{tab === "precise" ? <div className="forget-layout"><section className="content-card"><span className="eyebrow">TWO-PHASE FORGETTING</span><h3>用自然语言描述要忘记的内容</h3><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} /><button onClick={preview}>预览匹配结果</button><p>预览不会修改数据；确认后仍由 Agent 调用软删除接口。</p></section><section className="content-card"><h3>待确认候选</h3>{candidates.length ? candidates.map((item) => <div className="forget-candidate" key={text(item.memory_id || item.id)}><strong>{text(item.summary || item.text)}</strong><span>{text(item.type, "记忆")} · 相关性 {pct(item.score)}</span></div>) : <p className="large-empty">先运行预览，确认范围后再提交。</p>}<button className="danger" disabled={!candidates.length} onClick={confirm}>确认并交给 Agent</button></section></div> : <div className="content-card">{history.length ? history.map((item, index) => <div className="history-row" key={text(item.id || index)}><strong>{text(item.instruction || item.reason)}</strong><span>{text(item.created_at)}</span></div>) : <p className="large-empty">暂无遗忘历史</p>}</div>}</>;
}

function IngestionView({ session }: { session: ReplaySession }) {
  return <><div className="pipeline"><div><b>1</b><strong>原始事件</strong><span>Chat / Tool / 文件</span></div><i>→</i><div><b>2</b><strong>安全过滤</strong><span>正则 + NER</span></div><i>→</i><div><b>3</b><strong>标准化</strong><span>MemoryEvent 1.1</span></div><i>→</i><div><b>4</b><strong>记忆抽取</strong><span>偏好 / 知识 / 事实</span></div></div><div className="content-card"><h3>当前会话事件</h3>{session.events.length ? session.events.map((event) => <div className="event-row" key={event.event_id}><code>{event.event_id}</code><strong>{event.event_type}</strong><span>{event.turn_id}</span><span>{event.redactions?.length ? `已脱敏 ${event.redactions.length} 项` : "安全"}</span></div>) : <p className="large-empty">当前回放没有原始事件；导入 events 格式可查看完整链路。</p>}</div></>;
}

function Placeholder({ type }: { type: "safety" | "evaluation" | "settings" }) {
  const content = type === "safety" ? ["写入前敏感信息检测", "工具返回脱敏", "访问作用域校验"] : type === "evaluation" ? ["偏好准确率 ≥ 85%", "检索召回率 ≥ 85%", "冲突处理正确率 ≥ 88%", "检索延迟 ≤ 500ms"] : ["Agent Transport", "本地数据库与索引", "模型与抽取参数"];
  return <div className="placeholder-panel"><span className="page-status">完整页面预览 · 接口待接</span><h2>{type === "safety" ? "端侧安全能力" : type === "evaluation" ? "竞赛评测面板" : "系统运行设置"}</h2><div className="preview-grid">{content.map((item, index) => <div key={item}><span className="preview-pill">{String(index + 1).padStart(2, "0")}</span><strong>{item}</strong><small>{index < 2 ? "设计已完成" : "等待真实数据"}</small></div>)}</div></div>;
}

export default function Home() {
  const [view, setView] = useState<ViewId>("chat"); const [session, setSession] = useState(sampleSession); const [turnIndex, setTurnIndex] = useState(0);
  const [proposal, setProposal] = useState<FactProposal | null>(null); const [toast, setToast] = useState(""); const [online, setOnline] = useState(false); const fileRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<"workflow" | "template">("workflow"); const [rows, setRows] = useState<Row[]>(fallbackData.preferences); const [knowledge, setKnowledge] = useState<Row[]>(fallbackData.workflow);
  const [busy, setBusy] = useState(false); const [sideOpen, setSideOpen] = useState(false); const [executedTurns, setExecutedTurns] = useState<Set<number>>(new Set());
  const currentLabel = labels[view];
  useEffect(() => { const timer = toast ? window.setTimeout(() => setToast(""), 3200) : undefined; return () => timer && clearTimeout(timer); }, [toast]);
  useEffect(() => { if (view === "preferences") memoryApi.preferences().then((data) => { setRows(data as Row[]); setOnline(true); }).catch(() => setRows(fallbackData.preferences)); if (view === "facts") memoryApi.facts().then((data) => { setRows(data as Row[]); setOnline(true); }).catch(() => setRows(fallbackData.facts)); if (view === "conflicts") memoryApi.conflicts().then((data) => { setRows(data as Row[]); setOnline(true); }).catch(() => setRows(fallbackData.conflicts)); }, [view]);
  useEffect(() => { if (view === "knowledge") memoryApi.knowledge(kind).then((data) => { setKnowledge(data as Row[]); setOnline(true); }).catch(() => setKnowledge(fallbackData[kind])); }, [view, kind]);

  async function importJson(file?: File) {
    if (!file) return;
    try { const parsed = parseReplayJson(JSON.parse(await file.text())); setSession({ ...parsed, read_only: false }); setTurnIndex(0); setExecutedTurns(new Set()); setView("chat"); setToast("对话已导入，请从第一轮开始执行"); } catch (error) { setToast(error instanceof Error ? `导入失败：${error.message}` : "导入失败"); } finally { if (fileRef.current) fileRef.current.value = ""; }
  }
  async function loadExample() { try { const response = await fetch("/examples/memory-system-long-replay.json"); if (!response.ok) throw new Error("示例文件读取失败"); const parsed = parseReplayJson(await response.json()); const runId = Date.now().toString(36); const sessionId = `${parsed.session_id}_${runId}`; const userId = `demo_${runId}`; const events = parsed.events.map((event) => ({ ...event, event_id: `${event.event_id}_${runId}`, user_id: userId, session_id: sessionId })); const next = { ...parsed, session_id: sessionId, events, read_only: false as const }; setSession(next); setTurnIndex(0); setExecutedTurns(new Set()); setView("chat"); setToast("全新测试会话已创建，当前没有预置记忆"); } catch (error) { setToast(error instanceof Error ? error.message : "示例加载失败"); } }
  async function executeStep() {
    const turn = session.turns[turnIndex]; if (!turn) return;
    const events = [...session.events, ...(turn.events || [])].filter((event, index, all) => event.turn_id === turn.turn_id && all.findIndex((item) => item.event_id === event.event_id) === index);
    setBusy(true);
    try {
      const firstEvent = events[0]; const result = await memoryApi.step({ session_id: session.session_id, turn_id: turn.turn_id, user_message: turn.user_message, retrieval_query: turn.retrieval_query || turn.user_message, scene: firstEvent?.scene || "chat", task_type: firstEvent?.task_type || "memory_demo", events });
      const usedIds = Array.isArray(result.used_memory_ids) ? result.used_memory_ids.map(String) : [];
      const cards = Array.isArray(result.candidate_memories) ? (result.candidate_memories as Row[]).map((item) => ({ memory_id: text(item.memory_id), memory_type: text(item.memory_type, "knowledge"), knowledge_type: item.knowledge_type ? text(item.knowledge_type) : undefined, title: text(item.title, "记忆"), summary: text(item.summary), relevance: Number(item.relevance || 0), source: text(item.source, "MemoryHub"), level: text(item.level, "long"), scope: typeof item.scope === "string" ? item.scope : text(item.scope, "global"), tags: Array.isArray(item.tags) ? item.tags.map(String) : [], used: usedIds.includes(text(item.memory_id)) } as MemoryCardData)) : [];
      const facts = Array.isArray(result.fact_proposals) ? (result.fact_proposals as Row[]).map((item) => { const triple = (item.raw_triple || {}) as Row; const admission = (item.admission || {}) as Row; return { proposal_id: text(item.proposal_id || item.candidate_id), subject: text(triple.subject_text), predicate: text(triple.predicate_text), object: text(triple.object_text), evidence: text(triple.evidence), confidence: Number(triple.confidence || admission.confidence || 0), admission_reason: text(admission.reason, "满足事实候选准入条件"), suggested_scope: text(admission.suggested_scope || item.scope_hint, "project") as FactProposal["suggested_scope"], status: text(item.status, "proposed") }; }) : [];
      const backendCalls = Array.isArray(result.tool_calls) ? (result.tool_calls as ToolCall[]) : [];
      const externalCalls = turn.tool_calls.filter((call) => !call.tool_name.startsWith("memory_") && !["preference_extract", "preference_propose", "fact_propose", "conflict_detect", "template_extract"].includes(call.tool_name));
      const toolCalls = [...externalCalls, ...backendCalls].map((call, index) => ({ ...call, sequence: index + 1 }));
      setSession((current) => ({ ...current, read_only: false, turns: current.turns.map((item, index) => index === turnIndex ? { ...item, tool_calls: toolCalls, candidate_memories: cards, used_memory_ids: usedIds, fact_proposals: facts, write_summary: Array.isArray(result.write_summary) ? result.write_summary.map(String) : [], latency_ms: Number(result.retrieval_latency_ms || item.latency_ms || 0) } : item) }));
      setExecutedTurns((current) => new Set(current).add(turnIndex)); setOnline(true); setToast(`第 ${turnIndex + 1} 轮执行完成：写入与检索结果来自后端`);
    } catch (error) { setToast(error instanceof Error ? error.message : "本轮执行失败"); } finally { setBusy(false); }
  }

  const content = (() => {
    if (view === "chat") return <ChatView session={session} turnIndex={turnIndex} setTurnIndex={setTurnIndex} onProposal={setProposal} executedTurns={executedTurns} busy={busy} onExecute={executeStep} />;
    if (view === "ingestion") return <IngestionView session={session} />;
    if (view === "retrieval") return <RetrievalView onToast={setToast} />;
    if (view === "preferences" || view === "facts" || view === "conflicts") return <Records kind={view} rows={rows} />;
    if (view === "knowledge") return <KnowledgeView type={kind} setType={setKind} rows={knowledge} />;
    if (view === "forget") return <ForgetView onToast={setToast} />;
    return <Placeholder type={view as "safety" | "evaluation" | "settings"} />;
  })();

  return <main className="memory-app">
    <aside className={`app-sidebar ${sideOpen ? "open" : ""}`}><div className="app-brand"><span className="agent-logo">M</span><div><strong>MemoryHub</strong><small>LOCAL MEMORY</small></div></div><nav className="app-nav">{navGroups.map((group) => <div className="nav-group" key={group.label}><label>{group.label}</label>{group.items.map((item) => <button className={view === item.id ? "active" : ""} key={item.id} onClick={() => { setView(item.id); setSideOpen(false); }}><span>{item.icon}</span><strong>{item.label}</strong>{item.badge && <em>{item.badge}</em>}</button>)}</div>)}</nav><div className="connection"><span className={`status-dot ${online ? "live" : "offline"}`} /><div><strong>{online ? "服务已连接" : "本地模式"}</strong><small>v0.8.0 · 端侧运行</small></div></div></aside>
    <section className="app-main"><header className="app-header"><button className="side-toggle" onClick={() => setSideOpen(!sideOpen)}>☰</button><div><div className="breadcrumb">MemoryHub / {currentLabel[0]}</div><h1>{currentLabel[0]}</h1><p>{view === "chat" ? session.title : currentLabel[1]}</p></div><div className="header-actions"><span className="mode-chip"><span className={`status-dot ${online ? "live" : "offline"}`} />逐步执行</span><input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(event) => importJson(event.target.files?.[0])} /><button className="import-button" onClick={loadExample}>加载演示</button><button className="run-button" onClick={() => fileRef.current?.click()}>导入 JSON</button></div></header><div className={view === "chat" ? "chat-page" : "management-page"}>{content}</div></section>
    {proposal && <FactModal proposal={proposal} onClose={() => setProposal(null)} onDone={(message) => { setProposal(null); setToast(message); }} />}{toast && <div className="toast">{toast}</div>}
  </main>;
}
