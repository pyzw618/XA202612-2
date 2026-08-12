/**
 * MemoryHub plugin — pure event builder (no opencode SDK dependency).
 *
 * Exported as a separate module so the plugin file (`memoryhub.plugin.mjs`)
 * only exports the plugin factory function. opencode's classic plugin loader
 * calls every function export as a plugin factory, so keeping helper
 * functions here avoids spurious "failed to load plugin" errors.
 */
import { createHash } from "node:crypto"

export const DEFAULT_CONFIG = {
  apiUrl: "http://127.0.0.1:8000",
  userId: "opencode",
  autoRecord: true,
  scene: "code",
  taskType: "coding_task",
  maxResultChars: 4000,
  recordSummaries: true,
}

/**
 * Resolve effective configuration.
 *
 * Priority: process environment > plugin options (from the global/project
 * `plugin` array tuple) > built-in defaults.
 */
export function resolveConfig(options = {}) {
  const envBool = (name, fallback) =>
    process.env[name] !== undefined ? String(process.env[name]).toLowerCase() !== "false" : fallback

  return {
    apiUrl: (process.env.MEMORYHUB_API_URL || options.apiUrl || DEFAULT_CONFIG.apiUrl).replace(/\/$/, ""),
    userId: process.env.MEMORYHUB_USER_ID || options.userId || DEFAULT_CONFIG.userId,
    autoRecord: envBool("MEMORYHUB_AUTO_RECORD", options.autoRecord ?? DEFAULT_CONFIG.autoRecord),
    scene: process.env.MEMORYHUB_SCENE || options.scene || DEFAULT_CONFIG.scene,
    taskType: process.env.MEMORYHUB_TASK_TYPE || options.taskType || DEFAULT_CONFIG.taskType,
    maxResultChars: parseInt(
      process.env.MEMORYHUB_MAX_RESULT_CHARS ||
        String(options.maxResultChars ?? DEFAULT_CONFIG.maxResultChars),
      10,
    ),
    recordSummaries: envBool("MEMORYHUB_RECORD_SUMMARIES", options.recordSummaries ?? DEFAULT_CONFIG.recordSummaries),
  }
}

const CONFIG = resolveConfig()

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function sha256Hex(value) {
  return createHash("sha256").update(value, "utf8").digest("hex")
}

/** Format a Date as the contract's UTC second-precision string. */
export function occurredAt(date = new Date()) {
  const d = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date()
  const iso = d.toISOString() // YYYY-MM-DDTHH:MM:SS.sssZ
  return iso.slice(0, 19) + "Z"
}

/** Extract a JS Date from the SDK's `time` shapes ({created}, {completed}, number, ISO string). */
export function resolveTime(info) {
  const raw = info?.time
  if (raw == null) return undefined
  if (typeof raw === "number") return new Date(raw)
  if (typeof raw === "string") return new Date(raw)
  if (typeof raw === "object") {
    if (raw.created != null) return new Date(raw.created)
    if (raw.completed != null) return new Date(raw.completed)
  }
  return undefined
}

export function truncate(value, maxChars) {
  if (value === null || value === undefined) return null
  let text
  if (typeof value === "string") text = value
  else {
    try {
      text = JSON.stringify(value)
    } catch {
      text = String(value)
    }
  }
  if (maxChars > 0 && text.length > maxChars) {
    return text.slice(0, maxChars) + "\n…(truncated by memoryhub plugin)"
  }
  return text
}

const STATUS_MAP = {
  completed: "success",
  error: "error",
  cancelled: "cancelled",
  running: "partial",
  pending: "partial",
  interrupted: "partial",
}

function mapToolStatus(state) {
  const raw = state && (state.status || state.value)
  return STATUS_MAP[String(raw).toLowerCase()] || "partial"
}

/** Convert one tool Part into a MemoryHub ToolCallResult-compatible dict. */
function toToolCall(part, sequence, sessionID, cfg) {
  const input = part.input ?? part.arguments ?? {}
  const output = part.output ?? part.result ?? null
  return {
    call_id: part.id || `call_${sequence}_${String(sessionID).slice(0, 8)}`,
    tool_name: String(part.tool || part.name || "unknown_tool"),
    arguments: input && typeof input === "object" ? input : { value: input },
    result: truncate(output, cfg.maxResultChars),
    status: mapToolStatus(part.state),
    sequence,
    error: part.error ? String(part.error) : "",
  }
}

function defaultQuality() {
  return {
    score: 1.0,
    status: "accepted",
    completeness: 1.0,
    validity: 1.0,
    consistency: 1.0,
    freshness: 1.0,
    issues: [],
  }
}

/**
 * Build MemoryHub MemoryEvents from a session's message list.
 *
 * @param {object} input
 * @param {string} input.sessionID
 * @param {Array}  input.messages  Array of `{ info: {role,time}, parts: [...] }`
 * @param {object} input.cfg       Configuration (same shape as CONFIG)
 * @returns {Array<object>}       MemoryEvent payloads (may be empty)
 */
export function buildEventsFromSession({ sessionID, messages, cfg = CONFIG }) {
  if (!Array.isArray(messages) || messages.length === 0) return []

  const toolCalls = []
  let finalText = ""
  let lastTime = null

  for (const message of messages) {
    const info = message?.info ?? message
    if (info?.time) lastTime = lastTime || resolveTime(info)
    const role = info?.role
    const parts = message?.parts || []
    if (role !== "assistant" && role !== "tool") continue
    for (const part of parts) {
      if (!part || typeof part !== "object") continue
      if (part.type === "text") {
        if (typeof part.text === "string" && part.text.trim()) finalText = part.text.trim()
      } else if (part.type === "tool") {
        toolCalls.push(toToolCall(part, toolCalls.length + 1, sessionID, cfg))
      }
    }
  }

  if (toolCalls.length === 0) {
    if (!cfg.recordSummaries || !finalText) return []
    const event = {
      event_id: `evt_op_${sha256Hex(`${sessionID}:summary`).slice(0, 12)}`,
      source_type: "user_behavior",
      event_type: "agent_summary",
      user_id: cfg.userId,
      session_id: sessionID,
      turn_id: sessionID,
      scene: cfg.scene,
      task_type: cfg.taskType,
      occurred_at: occurredAt(lastTime ? new Date(lastTime) : undefined),
      text: finalText,
      payload: { action: "session_summary", tool_call_count: 0 },
      tool_calls: [],
      schema_version: "1.1",
      source_hash: "",
      redactions: [],
      quality: defaultQuality(),
    }
    event.source_hash = sha256Hex(JSON.stringify({ ...event, source_hash: "", quality: undefined }))
    return [event]
  }

  const event = {
    event_id: `evt_op_${sha256Hex(sessionID).slice(0, 12)}`,
    source_type: "tool_result",
    event_type: "agent_response",
    user_id: cfg.userId,
    session_id: sessionID,
    turn_id: sessionID,
    scene: cfg.scene,
    task_type: cfg.taskType,
    occurred_at: occurredAt(lastTime ? new Date(lastTime) : undefined),
    text: finalText || "opencode session completed",
    payload: { action: "session_record", tool_call_count: toolCalls.length },
    tool_calls: toolCalls,
    schema_version: "1.1",
    source_hash: "",
    redactions: [],
    quality: defaultQuality(),
  }
  event.source_hash = sha256Hex(JSON.stringify({ ...event, source_hash: "", quality: undefined }))
  return [event]
}
