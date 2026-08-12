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
 * NOTE: this module deliberately exports ONLY the plugin factory. opencode's
 * classic plugin loader invokes every function export as a plugin factory, so
 * helper functions live in `./memoryhub_event_builder.mjs` to avoid spurious
 * "failed to load plugin" errors.
 *
 * Configuration (environment variables):
 *   MEMORYHUB_API_URL              default http://127.0.0.1:8000
 *   MEMORYHUB_USER_ID              default opencode
 *   MEMORYHUB_AUTO_RECORD          default true  (set to false to disable)
 *   MEMORYHUB_SCENE                default code
 *   MEMORYHUB_TASK_TYPE            default coding_task
 *   MEMORYHUB_MAX_RESULT_CHARS     default 4000  (tool result truncation)
 *   MEMORYHUB_RECORD_SUMMARIES     default true  (record sessions without tool calls as summaries)
 */
import { buildEventsFromSession, resolveConfig } from "./memoryhub_event_builder.mjs"

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
export const MemoryHubPlugin = async ({ client }, options = {}) => {
  const cfg = resolveConfig(options)
  if (!cfg.autoRecord) {
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
    event: async ({ event }) => {
      if (!event || event.type !== "session.idle") return
      const sessionID = event?.properties?.sessionID
      if (!sessionID || recorded.has(sessionID)) return
      recorded.add(sessionID)

      try {
        const payload = await client.session.messages({ path: { id: sessionID } })
        const messages = normalizeMessages(payload)
        const events = buildEventsFromSession({ sessionID, messages, cfg })
        if (events.length === 0) return

        const result = await postEvents(events, cfg.apiUrl)
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

function postEvents(events, apiUrl = "http://127.0.0.1:8000") {
  // Portable AbortSignal (older Node < 17.3 lacks AbortSignal.timeout; Bun has it).
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 15000)
  return fetch(`${apiUrl}/api/memory/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
    signal: controller.signal,
  })
    .then((response) => {
      if (!response.ok) throw new Error(`MemoryHub POST /events -> HTTP ${response.status}`)
      return response.json()
    })
    .finally(() => clearTimeout(timer))
}

export default MemoryHubPlugin
