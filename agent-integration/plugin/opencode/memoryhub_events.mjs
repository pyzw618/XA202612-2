/** Pure event and tool-trace helpers used by the opencode plugin. */
import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { join } from "node:path"

export const DEFAULT_CONFIG = {
  apiUrl: "http://127.0.0.1:8099",
  userId: "opencode",
  scene: "code",
  taskType: "coding_task",
  maxResultChars: 1000,
  toolAllow: ["read", "edit", "write", "bash", "grep", "glob", "webfetch"],
  recordSummaries: true,
  recordProjects: true,
}

export function resolveConfig(options = {}, env = process.env) {
  const bool = (key, fallback) => env[key] === undefined ? fallback : !["0", "false", "no", "off"].includes(String(env[key]).toLowerCase())
  let file = {}
  const root = options.projectRoot || options.worktree
  if (root) {
    // Configuration files are optional; plugin loading must remain fail-soft.
    try { file = JSON.parse(readFileSync(join(root, ".memoryhub", "config.json"), "utf8")) } catch {}
  }
  const source = { ...DEFAULT_CONFIG, ...file, ...options }
  const auto = source.autoRecord && typeof source.autoRecord === "object" ? source.autoRecord : {}
  const allowed = env.MEMORYHUB_TOOL_ALLOW || options.toolAllow || file.toolAllow || auto.toolAllow || DEFAULT_CONFIG.toolAllow
  const configuredAutoRecord = typeof source.autoRecord === "object" ? auto.enabled !== false : source.autoRecord !== false
  return {
    ...source,
    apiUrl: String(env.MEMORYHUB_API_URL || source.apiUrl).replace(/\/$/, ""),
    userId: String(env.MEMORYHUB_USER_ID || source.userId),
    scene: String(env.MEMORYHUB_SCENE || source.scene),
    taskType: String(env.MEMORYHUB_TASK_TYPE || source.taskType),
    autoRecord: bool("MEMORYHUB_AUTO_RECORD", configuredAutoRecord),
    recordSummaries: bool("MEMORYHUB_RECORD_SUMMARIES", source.recordSummaries !== false),
    maxResultChars: Number(env.MEMORYHUB_MAX_RESULT_CHARS || options.maxResultChars || file.maxResultChars || auto.toolResultMaxChars || DEFAULT_CONFIG.maxResultChars) || 1000,
    recordProjects: source.recordProjects !== false && auto.recordProjects !== false,
    toolAllow: Array.isArray(allowed) ? allowed.map(String) : String(allowed).split(",").map((v) => v.trim()).filter(Boolean),
  }
}

export function truncate(value, maxChars) {
  if (value === null || value === undefined) return null
  const text = typeof value === "string" ? value : JSON.stringify(value)
  return maxChars > 0 && text.length > maxChars ? `${text.slice(0, maxChars)}\n...(truncated by memoryhub plugin)` : text
}

export function sha256Hex(value) {
  return createHash("sha256").update(String(value), "utf8").digest("hex")
}

function nowUtc() {
  return new Date().toISOString().slice(0, 19) + "Z"
}

function quality() {
  return { score: 1, status: "accepted", completeness: 1, validity: 1, consistency: 1, freshness: 1, issues: [] }
}

function statusOf(output) {
  const status = String(output?.status || output?.state?.status || "success").toLowerCase()
  return { completed: "success", success: "success", error: "error", cancelled: "cancelled", running: "partial", pending: "partial" }[status] || "partial"
}

export function normalizeToolRecord({ tool, args = {}, output = {}, sessionID, cfg = DEFAULT_CONFIG }) {
  const toolName = String(tool || "unknown_tool")
  if (cfg.toolAllow?.length && !cfg.toolAllow.includes(toolName)) return null
  if (toolName.startsWith("memoryhub")) return null
  return {
    call_id: String(output?.call_id || output?.callId || `${sessionID || "session"}_${Date.now()}`),
    tool_name: toolName,
    arguments: args && typeof args === "object" ? args : { value: args },
    result: truncate(output?.output ?? output?.result ?? output, cfg.maxResultChars),
    status: statusOf(output),
    sequence: 0,
    error: output?.error ? String(output.error) : "",
  }
}

export function buildEvent({ sessionID, records = [], cfg = DEFAULT_CONFIG, summary = false }) {
  const toolCalls = records.map((record, index) => ({ ...record, sequence: index + 1 }))
  const text = summary ? String(records.at(-1)?.result || "") : "opencode tool activity"
  if (!toolCalls.length && (!cfg.recordSummaries || !text)) return null
  const event = {
    event_id: `evt_op_${sha256Hex(`${sessionID}:${summary ? "summary" : Date.now()}`).slice(0, 16)}`,
    source_type: summary ? "user_behavior" : "tool_result",
    event_type: summary ? "agent_summary" : "agent_response",
    user_id: cfg.userId,
    session_id: sessionID,
    turn_id: sessionID,
    scene: cfg.scene,
    task_type: cfg.taskType,
    occurred_at: nowUtc(),
    text,
    payload: {
      action: summary ? "session_summary" : "tool_trace",
      tool_call_count: toolCalls.length,
      ...(cfg.projectRoot && cfg.recordProjects ? { project_root: cfg.projectRoot, project_name: String(cfg.projectRoot).split(/[\\/]/).at(-1) } : {}),
    },
    tool_calls: toolCalls,
    schema_version: "1.1",
    source_hash: "",
    redactions: [],
    quality: quality(),
  }
  event.source_hash = sha256Hex(JSON.stringify({ ...event, source_hash: "", quality: undefined }))
  return event
}

export class TraceAccumulator {
  constructor() { this.pending = new Map() }
  add(sessionID, record) {
    if (!sessionID || !record) return
    const records = this.pending.get(sessionID) || []
    records.push(record)
    this.pending.set(sessionID, records)
  }
  drain(sessionID, cfg, { summary = false } = {}) {
    const records = this.pending.get(sessionID) || []
    this.pending.delete(sessionID)
    const event = buildEvent({ sessionID, records, cfg, summary })
    return event ? [event] : []
  }
  sessions() { return [...this.pending.keys()] }
}
