#!/usr/bin/env node
import { cp, mkdir } from "node:fs/promises"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const source = dirname(fileURLToPath(import.meta.url))
const root = resolve(process.argv[2] || ".opencode")
const plugins = root.endsWith("plugins") ? root : join(root, "plugins")
const opencodeRoot = root.endsWith("plugins") ? dirname(root) : root
await mkdir(plugins, { recursive: true })
await cp(join(source, "memoryhub.plugin.mjs"), join(plugins, "memoryhub.plugin.mjs"))
await cp(join(source, "memoryhub_events.mjs"), join(plugins, "memoryhub_events.mjs"))
for (const folder of ["commands", "skills", "tools"]) {
  await cp(join(source, folder), join(opencodeRoot, folder), { recursive: true })
}
console.log(`MemoryHub opencode plugin installed in ${opencodeRoot}`)
