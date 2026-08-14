param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8099
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$healthUrl = "http://${BindHost}:${Port}/api/agent/health"

try {
    $response = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
        Write-Host "MemoryHub service is already running at http://${BindHost}:${Port}"
        exit 0
    }
} catch {
    # No healthy service is listening; start an independent backend process.
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found. Create .venv and install the project dependencies first."
}

$logDir = Join-Path $projectRoot "data\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$pidFile = Join-Path $logDir "memoryhub-service.pid"

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $python
$startInfo.Arguments = "-m uvicorn memoryhub.app:app --host $BindHost --port $Port"
$startInfo.WorkingDirectory = $projectRoot
$startInfo.UseShellExecute = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$process = [System.Diagnostics.Process]::Start($startInfo)
if (-not $process) {
    throw "Unable to create the MemoryHub service process."
}

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -UseBasicParsing $healthUrl -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            Write-Host "MemoryHub service started independently (PID $($process.Id)) at http://${BindHost}:${Port}"
            exit 0
        }
    } catch {
        if ($process.HasExited) {
            throw "MemoryHub service exited during startup. Run the uvicorn command in a terminal to inspect the error."
        }
    }
}

throw "MemoryHub service did not become ready. Run the uvicorn command in a terminal to inspect the error."
