$ErrorActionPreference = "Stop"
Add-Type -AssemblyName PresentationFramework

$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$backendUrl = "http://127.0.0.1:8010"

if (-not (Test-Path -LiteralPath $python)) {
    [System.Windows.MessageBox]::Show("没有找到项目虚拟环境，请先安装依赖。`n$python", "MemoryHub") | Out-Null
    exit 1
}

$ready = $false
try {
    $health = Invoke-RestMethod -Uri "$backendUrl/api/health" -TimeoutSec 2
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
            $health = Invoke-RestMethod -Uri "$backendUrl/api/health" -TimeoutSec 2
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
    [System.Windows.MessageBox]::Show("MemoryHub 后端启动失败，请检查端口 8010 或查看终端日志。", "MemoryHub") | Out-Null
    exit 1
}

$env:MEMORYHUB_BACKEND_URL = $backendUrl
Start-Process -FilePath $python -ArgumentList "-m", "memoryhub_qml" -WorkingDirectory $repo | Out-Null
