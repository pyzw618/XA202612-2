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
const PLUGIN_DIR = resolve(HERE, "../plugin")
const PLUGIN_FILES = ["memoryhub.plugin.mjs", "memoryhub_event_builder.mjs"]

function install() {
  const targetDir = resolve(process.argv[2] || join(process.cwd(), ".opencode", "plugins"))

  mkdirSync(targetDir, { recursive: true })
  for (const fileName of PLUGIN_FILES) {
    copyFileSync(join(PLUGIN_DIR, fileName), join(targetDir, fileName))
  }

  console.log(`[memoryhub-plugin] installed ${PLUGIN_FILES.join(", ")} to ${targetDir}`)
  console.log("[memoryhub-plugin] set MEMORYHUB_API_URL / MEMORYHUB_USER_ID before starting opencode.")
}

install()
