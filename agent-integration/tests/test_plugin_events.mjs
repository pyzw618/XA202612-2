import assert from "node:assert/strict"
import { buildEvent, normalizeToolRecord, TraceAccumulator } from "../plugin/opencode/memoryhub_events.mjs"

const cfg = { userId: "u1", scene: "code", taskType: "coding", maxResultChars: 8, toolAllow: ["bash"], recordSummaries: true, projectRoot: "C:/repo" }
const record = normalizeToolRecord({ tool: "bash", args: { command: "git status" }, output: { status: "completed", output: "123456789" }, sessionID: "s1", cfg })
assert.equal(record.result, "12345678\n...(truncated by memoryhub plugin)")
assert.equal(normalizeToolRecord({ tool: "curl", args: {}, output: {}, sessionID: "s1", cfg }), null)

const accumulator = new TraceAccumulator()
accumulator.add("s1", record)
const events = accumulator.drain("s1", cfg)
assert.equal(events.length, 1)
assert.equal(events[0].event_type, "agent_response")
assert.equal(events[0].payload.project_root, "C:/repo")
assert.equal(events[0].tool_calls[0].sequence, 1)
assert.match(events[0].source_hash, /^[0-9a-f]{64}$/)
assert.equal(accumulator.drain("s1", cfg).length, 0)
assert.equal(buildEvent({ sessionID: "s2", records: [{ result: "summary" }], cfg, summary: true }).event_type, "agent_summary")
console.log("all agent-integration plugin event tests passed")
