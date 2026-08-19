import { executeCli } from "./_cli.mjs"
export const description = "Explicitly remember a user preference or knowledge item."
export const execute = (args = {}) => executeCli(["--json", "remember", String(args.text || ""), "--type", String(args.memory_type || "preference")])
