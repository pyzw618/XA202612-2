/**
 * opencode integration. CLI is the implementation boundary; tools and hooks
 * only adapt opencode arguments/events to `memoryhub` commands and events.
 */
import { buildEvent, normalizeToolRecord, resolveConfig, TraceAccumulator } from "./memoryhub_events.mjs"

async function runCli(args) {
  if (typeof Bun !== "undefined" && Bun.$) {
    const command = process.env.MEMORYHUB_PYTHON
      ? [process.env.MEMORYHUB_PYTHON, "-m", "memoryhub_cli", ...args]
      : ["memoryhub", ...args]
    const child = Bun.spawn(command, { stdout: "pipe", stderr: "pipe" })
    return (await new Response(child.stdout).text()).trim()
  }
  const { execFile } = await import("node:child_process")
  return await new Promise((resolve) => {
    execFile("memoryhub", args, { timeout: 15000 }, (error, stdout, stderr) => {
      if (error?.code === "ENOENT") {
        execFile(process.env.MEMORYHUB_PYTHON || "python", ["-m", "memoryhub_cli", ...args], { timeout: 15000 }, (_fallbackError, fallbackOut, fallbackErr) => resolve(String(fallbackOut || fallbackErr).trim()))
        return
      }
      resolve(String(stdout || stderr).trim())
    })
  })
}

function toolWrapper(command, description, buildArgs, toolFactory) {
  const execute = async (args = {}) => {
    try { return await runCli(buildArgs(args)) } catch (error) { return JSON.stringify({ error: { code: "memoryhub.plugin.cli_failed", message: String(error) } }) }
  }
  const fallback = {
    description,
    args: {},
    execute,
  }
  if (!toolFactory) return fallback
  const s = toolFactory.schema
  const args = command === "remember"
    ? { text: s.string().describe("Text to remember"), memory_type: s.string().optional().describe("preference or knowledge subtype") }
    : { query: s.string().describe("MemoryHub query") }
  return toolFactory({ description, args, execute })
}

function postEvents(events, apiUrl) {
  if (!events.length) return Promise.resolve({ accepted: 0, rejected: 0, event_ids: [] })
  return fetch(`${apiUrl}/api/memory/events`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ events }) }).then(async (response) => {
    if (!response.ok) throw new Error(`MemoryHub POST /events -> HTTP ${response.status}`)
    return response.json()
  })
}

export const MemoryHubPlugin = async (ctx = {}) => {
  const cfg = resolveConfig({ projectRoot: ctx.worktree || ctx.directory })
  if (!cfg.autoRecord) return {}
  cfg.projectRoot = ctx.worktree || ctx.directory || cfg.projectRoot
  let opencodeTool
  try { opencodeTool = (await import("@opencode-ai/plugin")).tool } catch {}
  const accumulator = new TraceAccumulator()
  const log = async (level, message) => { try { await ctx.client?.app?.log?.({ body: { service: "memoryhub-plugin", level, message } }) } catch {} }
  const flush = async (sessionID, summary = false) => {
    const events = accumulator.drain(sessionID, cfg, { summary })
    if (!events.length) return
    try { await postEvents(events, cfg.apiUrl) } catch (error) { await log("warn", `failed to record session ${sessionID}: ${String(error)}`) }
  }
  return {
    tool: {
      memoryhub_search: toolWrapper("search", "Search MemoryHub preference, knowledge and fact memories.", (args) => ["--json", "search", String(args.query || "")], opencodeTool),
      memoryhub_get_context: toolWrapper("context", "Get prompt-ready MemoryHub context for the current task.", (args) => ["--json", "context", String(args.query || "")], opencodeTool),
      memoryhub_remember: toolWrapper("remember", "Explicitly remember a user preference or knowledge item.", (args) => ["--json", "remember", String(args.text || ""), "--type", String(args.memory_type || "preference")], opencodeTool),
    },
    "tool.execute.after": async (input = {}, output = {}) => {
      const sessionID = input.sessionID || input.sessionId || input.session_id || output.sessionID
      const record = normalizeToolRecord({ tool: input.tool, args: input.args || input.arguments, output, sessionID, cfg })
      accumulator.add(sessionID, record)
    },
    event: async ({ event } = {}) => {
      const sessionID = event?.properties?.sessionID || event?.properties?.sessionId
      if (!sessionID) return
      if (event.type === "session.status" && String(event.properties?.status || event.properties?.status?.type) === "idle") await flush(sessionID)
      if (event.type === "session.deleted") await flush(sessionID, true)
    },
    "experimental.session.compacting": async (input = {}, output = {}) => {
      const sessionID = input.sessionID || input.sessionId
      if (!sessionID || !ctx.client?.session?.messages) return
      try {
        const context = await runCli(["--compact", "context", "--max-chars", "2500", "current task"])
        if (output && typeof output === "object") output.context = `${output.context || ""}\n\nMemoryHub context:\n${context}`.trim()
      } catch (error) { await log("debug", `compacting context unavailable: ${String(error)}`) }
    },
  }
}

export default MemoryHubPlugin
