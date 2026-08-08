/**
 * Install the MemoryHub plugin into opencode's project plugin directory.
 *
 * opencode only auto-loads plugins from `.opencode/plugins/` (or the global
 * `~/.config/opencode/plugins/`), so this copies the self-contained plugin
 * file there. Run with Node or Bun:
 *
 *   node scripts/install_plugin.mjs
 *   bun  scripts/install_plugin.mjs
 *
 * Optionally pass a target directory (default `.opencode/plugins`):
 *   node scripts/install_plugin.mjs ~/.config/opencode/plugins
 */
import { copyFileSync, mkdirSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN_SRC = resolve(HERE, "../plugin/memoryhub.plugin.mjs")

function install() {
  const targetDir = resolve(process.argv[2] || join(process.cwd(), ".opencode", "plugins"))
  const target = join(targetDir, "memoryhub.plugin.mjs")

  mkdirSync(targetDir, { recursive: true })
  copyFileSync(PLUGIN_SRC, target)

  console.log(`[memoryhub-plugin] installed to ${target}`)
  console.log("[memoryhub-plugin] set MEMORYHUB_API_URL / MEMORYHUB_USER_ID before starting opencode.")
}

install()
