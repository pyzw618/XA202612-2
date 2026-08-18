import { executeCli } from "./_cli.mjs"
export const description = "Search MemoryHub preference, knowledge and fact memories."
export const execute = (args = {}) => executeCli(["--json", "search", String(args.query || "")])
