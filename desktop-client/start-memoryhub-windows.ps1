$ErrorActionPreference = "Stop"

$sourceRepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $sourceRepoRoot "memoryhub\app.py"))) {
    # The deployed copy lives in Desktop\MemoryHub-D, outside the source tree.
    $sourceRepoRoot = "C:\Users\joe_0\Desktop\挑战杯\合并\XA202612-2-dev-remem-debug"
}
$desktop = [Environment]::GetFolderPath("Desktop")
$bundleDir = Join-Path $desktop "MemoryHub-D"
$clientExe = Join-Path $bundleDir "memoryhub-client.exe"
$pythonExe = "D:\python.exe"
$healthUrl = "http://127.0.0.1:8099/api/health"

function Test-MemoryHubHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $clientExe)) {
    throw "MemoryHub client not found: $clientExe"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Python runtime not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceRepoRoot "memoryhub\app.py"))) {
    throw "MemoryHub source repository not found: $sourceRepoRoot"
}

if (-not (Test-MemoryHubHealth)) {
    $logDir = Join-Path $bundleDir "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir "backend.out.log"
    $stderrLog = Join-Path $logDir "backend.err.log"
    # Windows demo mode has no Kylin embedding SDK.  Keep the repository's
    # Kylin production configuration intact and override only this child.
    $env:MEMORYHUB_EMBEDDING_PROVIDER = "mock"
    $env:MEMORYHUB_VECTOR_ENGINE_PROVIDER = "faiss"
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "memoryhub.app:app", "--host", "127.0.0.1", "--port", "8099") `
        -WorkingDirectory $sourceRepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru
    Set-Content -LiteralPath (Join-Path $logDir "backend.pid") -Value $process.Id

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Test-MemoryHubHealth) {
            $ready = $true
            break
        }
        if ($process.HasExited) {
            break
        }
    }
    if (-not $ready) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show(
            "MemoryHub 后端启动失败，请查看：$stderrLog",
            "MemoryHub 启动失败"
        ) | Out-Null
        exit 1
    }
}

Start-Process -FilePath $clientExe -WorkingDirectory $bundleDir
