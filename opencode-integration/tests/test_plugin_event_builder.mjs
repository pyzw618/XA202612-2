/**
 * Unit tests for the MemoryHub plugin's event builder (pure functions).
 * Run with Node:
 *   node opencode-integration/tests/test_plugin_event_builder.mjs
 */
import assert from "node:assert"
import { buildEventsFromSession, occurredAt, sha256Hex, truncate } from "../plugin/memoryhub_event_builder.mjs"

const cfg = { ...{}, userId: "opencode", scene: "code", taskType: "coding_task", maxResultChars: 100, recordSummaries: true }

function sessionMessages() {
  return [
    { info: { role: "user", time: "2026-08-08T08:00:00.000Z" }, parts: [{ type: "text", text: "生成项目周报" }] },
    {
      info: { role: "assistant", time: "2026-08-08T08:00:05.000Z" },
      parts: [
        { type: "reasoning", text: "thinking..." },
        {
          type: "tool",
          id: "tool_1",
          tool: "read",
          state: { status: "completed" },
          input: { filePath: "report.md" },
          output: { content: "# 周报\n" },
        },
        {
          type: "tool",
          id: "tool_2",
          tool: "bash",
          state: { status: "error" },
          input: { command: "pandoc x" },
          output: "pandoc: file not found",
          error: "exit code 1",
        },
        { type: "text", text: "已生成周报，使用 Markdown 格式。" },
      ],
    },
  ]
}

// --- occurredAt ---
assert.match(occurredAt(new Date("2026-08-08T08:09:10.789Z")), /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
assert.strictEqual(occurredAt(new Date("2026-08-08T08:09:10.789Z")), "2026-08-08T08:09:10Z")

// --- sha256Hex ---
assert.strictEqual(sha256Hex("").length, 64)

// --- truncate ---
assert.strictEqual(truncate("hello world", 5), "hello\n…(truncated by memoryhub plugin)")
assert.strictEqual(truncate({ a: 1 }, 100), JSON.stringify({ a: 1 }))

// --- buildEventsFromSession: agent_response with tool calls ---
const events = buildEventsFromSession({ sessionID: "sess_1", messages: sessionMessages(), cfg })
assert.strictEqual(events.length, 1, "one event expected")
const ev = events[0]
assert.strictEqual(ev.source_type, "tool_result")
assert.strictEqual(ev.event_type, "agent_response")
assert.strictEqual(ev.turn_id, "sess_1")
assert.strictEqual(ev.session_id, "sess_1")
assert.match(ev.occurred_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
assert.match(ev.source_hash, /^[0-9a-f]{64}$/)
assert.strictEqual(ev.text, "已生成周报，使用 Markdown 格式。")
assert.strictEqual(ev.tool_calls.length, 2)
assert.strictEqual(ev.tool_calls[0].tool_name, "read")
assert.strictEqual(ev.tool_calls[0].status, "success")
assert.strictEqual(ev.tool_calls[0].sequence, 1)
assert.strictEqual(ev.tool_calls[1].tool_name, "bash")
assert.strictEqual(ev.tool_calls[1].status, "error")
assert.strictEqual(ev.tool_calls[1].sequence, 2)
assert.strictEqual(ev.quality.status, "accepted")

// --- summary-only session ---
const summary = buildEventsFromSession({
  sessionID: "sess_2",
  messages: [
    { info: { role: "user" }, parts: [{ type: "text", text: "hi" }] },
    { info: { role: "assistant" }, parts: [{ type: "text", text: "hello" }] },
  ],
  cfg,
})
assert.strictEqual(summary.length, 1)
assert.strictEqual(summary[0].source_type, "user_behavior")
assert.strictEqual(summary[0].event_type, "agent_summary")
assert.strictEqual(summary[0].text, "hello")

// --- empty / no-content sessions are skipped ---
assert.deepStrictEqual(buildEventsFromSession({ sessionID: "s3", messages: [], cfg }), [])
const noRecord = buildEventsFromSession({
  sessionID: "s4",
  messages: [{ info: { role: "user" }, parts: [{ type: "text", text: "hi" }] }],
  cfg: { ...cfg, recordSummaries: false },
})
assert.deepStrictEqual(noRecord, [])

console.log("all plugin event-builder tests passed")
