$ErrorActionPreference = "Stop"
Add-Type -AssemblyName PresentationFramework

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$backendUrl = "http://127.0.0.1:8010"

if (-not (Test-Path -LiteralPath $python)) {
    [System.Windows.MessageBox]::Show("Python environment not found. Please install project dependencies first.", "MemoryHub") | Out-Null
    exit 1
}

$ready = $false
try {
    $health = Invoke-RestMethod -Uri "$backendUrl/api/agent/health" -TimeoutSec 2
    $ready = $health.status -eq "ok"
} catch {
    $ready = $false
}

if (-not $ready) {
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "memoryhub.app:app", "--host", "127.0.0.1", "--port", "8010" `
        -WorkingDirectory $repo -WindowStyle Hidden | Out-Null

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod -Uri "$backendUrl/api/agent/health" -TimeoutSec 2
            if ($health.status -eq "ok") {
                $ready = $true
                break
            }
        } catch {
            $ready = $false
        }
    }
}

if (-not $ready) {
    [System.Windows.MessageBox]::Show("MemoryHub backend failed to start on port 8010.", "MemoryHub") | Out-Null
    exit 1
}

$env:MEMORYHUB_BACKEND_URL = $backendUrl
Start-Process -FilePath $python -ArgumentList "-m", "memoryhub_qml" -WorkingDirectory $repo | Out-Null
