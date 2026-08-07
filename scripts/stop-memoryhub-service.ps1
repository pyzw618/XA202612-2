$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot "data\logs\memoryhub-service.pid"

if (-not (Test-Path $pidFile)) {
    Write-Host "No MemoryHub service PID file was found."
    exit 0
}

$servicePid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $servicePid
    $null = $process.WaitForExit(5000)
    Write-Host "MemoryHub service stopped (PID $servicePid)."
} else {
    Write-Host "MemoryHub service process $servicePid is no longer running."
}

Remove-Item -LiteralPath $pidFile -Force
