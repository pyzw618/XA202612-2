$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
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

if (-not (Test-MemoryHubHealth)) {
    $logDir = Join-Path $bundleDir "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir "backend.out.log"
    $stderrLog = Join-Path $logDir "backend.err.log"
    $process = Start-Process -FilePath $pythonExe `
        -ArgumentList @("-m", "uvicorn", "memoryhub.app:app", "--host", "127.0.0.1", "--port", "8099") `
        -WorkingDirectory $repoRoot `
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
