import { executeCli } from "./_cli.mjs"
export const description = "Get prompt-ready MemoryHub context for the current task."
export const execute = (args = {}) => executeCli(["--json", "context", String(args.query || "")])
