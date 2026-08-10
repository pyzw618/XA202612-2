/**
 * MemoryHub auto-record plugin for opencode.
 *
 * When an opencode session goes idle, this plugin collects the session's
 * messages (assistant text + tool calls), builds one `MemoryEvent` in the
 * Kylin-MemoryHub `agent_response` / `user_behavior` contract and POSTs it to
 * the MemoryHub REST API (`POST /api/memory/events`), where safety filtering
 * and preference/knowledge/fact extraction run automatically.
 *
 * The plugin never blocks or breaks opencode: every failure is logged via the
 * SDK and swallowed.
 *
 * Configuration (environment variables):
 *   MEMORYHUB_API_URL              default http://127.0.0.1:8010
 *   MEMORYHUB_USER_ID              default opencode
 *   MEMORYHUB_AUTO_RECORD          default true  (set to false to disable)
 *   MEMORYHUB_SCENE                default code
 *   MEMORYHUB_TASK_TYPE            default coding_task
 *   MEMORYHUB_MAX_RESULT_CHARS     default 4000  (tool result truncation)
 *   MEMORYHUB_RECORD_SUMMARIES     default true  (record sessions without tool calls as summaries)
 */
import { createHash } from "node:crypto"

const CONFIG = {
  apiUrl: (process.env.MEMORYHUB_API_URL || "http://127.0.0.1:8010").replace(/\/$/, ""),
  userId: process.env.MEMORYHUB_USER_ID || "opencode",
  autoRecord: (process.env.MEMORYHUB_AUTO_RECORD || "true").toLowerCase() !== "false",
  scene: process.env.MEMORYHUB_SCENE || "code",
  taskType: process.env.MEMORYHUB_TASK_TYPE || "coding_task",
  maxResultChars: parseInt(process.env.MEMORYHUB_MAX_RESULT_CHARS || "4000", 10),
  recordSummaries: (process.env.MEMORYHUB_RECORD_SUMMARIES || "true").toLowerCase() !== "false",
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for tests)
// ---------------------------------------------------------------------------

export function sha256Hex(value) {
  return createHash("sha256").update(value, "utf8").digest("hex")
}

/** Format a Date as the contract's UTC second-precision string. */
export function occurredAt(date = new Date()) {
  const iso = date.toISOString() // YYYY-MM-DDTHH:MM:SS.sssZ
  return iso.slice(0, 19) + "Z"
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
    if (info?.time) lastTime = lastTime || info.time
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

function withTimeout(ms) {
  // Portable AbortSignal (older Node < 17.3 lacks AbortSignal.timeout; Bun has it).
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  return { signal: controller.signal, done: () => clearTimeout(timer) }
}

async function postEvents(events) {
  const { signal, done } = withTimeout(15000)
  try {
    const response = await fetch(`${CONFIG.apiUrl}/api/memory/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
      signal,
    })
    if (!response.ok) {
      throw new Error(`MemoryHub POST /events -> HTTP ${response.status}`)
    }
    return response.json()
  } finally {
    done()
  }
}

function normalizeMessages(payload) {
  // SDK client returns `{ info, parts }[]`; be tolerant of `{ data: [...] }` too.
  const list = Array.isArray(payload) ? payload : payload?.data
  if (!Array.isArray(list)) return []
  return list.map((item) => {
    if (item && Array.isArray(item.parts) && item.info) return item
    if (item && Array.isArray(item.parts)) return item
    return { info: item, parts: item?.parts || [] }
  })
}

// ---------------------------------------------------------------------------
// Plugin factory
// ---------------------------------------------------------------------------

/**
 * @param {object} ctx  { project, client, $, directory, worktree }
 * @returns {object}    Hook map consumed by opencode.
 */
export const MemoryHubPlugin = async ({ client }) => {
  if (!CONFIG.autoRecord) {
    return {}
  }
  if (!client?.session?.messages) {
    // Old/partial SDK clients: fail soft so opencode keeps working.
    try {
      await client?.app?.log?.({
        body: { service: "memoryhub-plugin", level: "warn", message: "session.messages unavailable; memory recording disabled" },
      })
    } catch {}
    return {}
  }

  const recorded = new Set()

  const log = async (level, message) => {
    try {
      await client.app.log({ body: { service: "memoryhub-plugin", level, message } })
    } catch {}
  }

  return {
    "session.idle": async ({ event }) => {
      const sessionID = event?.sessionID ?? event?.session?.id ?? event?.properties?.sessionID
      if (!sessionID || recorded.has(sessionID)) return
      recorded.add(sessionID)

      try {
        const payload = await client.session.messages({ path: { id: sessionID } })
        const messages = normalizeMessages(payload)
        const events = buildEventsFromSession({ sessionID, messages })
        if (events.length === 0) return

        const result = await postEvents(events)
        await log(
          "info",
          `recorded session ${sessionID}: accepted=${result.accepted} rejected=${result.rejected} ` +
            `ids=${(result.event_ids || []).join(",")} extraction_failures=${result.extraction_failures}`,
        )
      } catch (err) {
        await log("warn", `failed to record session ${sessionID}: ${err && err.message ? err.message : String(err)}`)
      }
    },
  }
}

export default MemoryHubPlugin
