# Install the MemoryHub Claude Code plugin into the user plugin directory.
#
# The plugin is self-contained: MCP server + hooks + record/context scripts.
# Copying it into ~/.claude/plugins makes Claude Code auto-discover it.
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts/install_plugin.ps1
#   # optionally pin the python interpreter used by hooks + MCP server:
#   powershell -ExecutionPolicy Bypass -File scripts/install_plugin.ps1 -PythonPath D:\Anaconda\envs\py12\python.exe
#
# After install, enable the plugin with `claude --plugin-dir <target>` or the
# /plugin manager, export the MEMORYHUB_* env vars, and restart Claude Code.
param(
  [string]$Target = "$env:USERPROFILE\.claude\plugins\memoryhub",
  [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$src = Join-Path $here "..\plugin\memoryhub"

if (-not (Test-Path -LiteralPath $src)) {
  Write-Error "plugin source not found: $src"
  exit 1
}

# fresh copy
if (Test-Path -LiteralPath $Target) {
  Remove-Item -LiteralPath $Target -Recurse -Force
}
Copy-Item -LiteralPath $src -Destination $Target -Recurse

# optionally pin the python interpreter into hooks.json and .mcp.json
if ($PythonPath) {
  $hooks = Join-Path $Target "hooks\hooks.json"
  $mcp = Join-Path $Target ".mcp.json"
  $escaped = [regex]::Escape($PythonPath)

  foreach ($file in @($hooks, $mcp)) {
    $json = Get-Content -LiteralPath $file -Raw -Encoding UTF8
    # replace `"command": "python"` (hooks) and `"command": "${MEMORYHUB_PYTHON:-python}"` (mcp)
    $json = $json -replace '"command"\s*:\s*"(?:python|\$\{MEMORYHUB_PYTHON:-python\})"', ('"command": "' + $PythonPath + '"')
    Set-Content -LiteralPath $file -Value $json -Encoding UTF8
    Write-Output "[memoryhub] pinned python in $file"
  }
}

Write-Output "[memoryhub] installed plugin to $Target"
Write-Output "[memoryhub] before starting Claude Code, export:"
Write-Output "    `$env:MEMORYHUB_API_URL = 'http://127.0.0.1:8000'"
Write-Output "    `$env:MEMORYHUB_USER_ID = 'claudecode'"
Write-Output "[memoryhub] start the MemoryHub REST service:"
Write-Output "    python claudecode-integration/scripts/start_memoryhub_server.py"
