param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$frontendRoot = Join-Path $ProjectRoot 'frontend'
$candidates = @(
  (Join-Path $frontendRoot 'desktop-dist/desktop-fixed/MemoryHub.exe'),
  (Join-Path $frontendRoot 'desktop-dist/win-unpacked/MemoryHub.exe')
)
$exe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $exe) {
  Write-Error "MemoryHub.exe not found. Run frontend/npm.cmd run desktop:build first."
  exit 1
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'MemoryHub.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe
$shortcut.Description = 'Kylin MemoryHub'
$shortcut.Save()

Write-Host "Created shortcut: $shortcutPath"
Write-Host "Target: $exe"
