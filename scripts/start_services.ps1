$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "artifacts\logs"
$pidFile = Join-Path $logDir "desktop-python-api.pid"

if (-not (Test-Path $python)) {
    throw "Missing virtual environment. Run scripts\setup.ps1 first."
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
        $env:OLLAMA_KEEP_ALIVE = "-1"
        Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    }
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existingPid = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($existingPid -match '^\d+$') {
        if (Get-Command taskkill -ErrorAction SilentlyContinue) {
            & taskkill /PID $existingPid /T /F | Out-Null
        }
        else {
            Stop-Process -Id ([int]$existingPid) -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 300
    }
}

$runtimeProcess = Start-Process -FilePath $python `
    -ArgumentList @("-m", "services.runtime.api") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -PassThru
Set-Content -Path $pidFile -Value $runtimeProcess.Id

$tauriExe = Join-Path $root "src-tauri\target\release\localflow.exe"
if (Test-Path $tauriExe) {
    Start-Process -FilePath $tauriExe `
        -WorkingDirectory $root
}
else {
    Write-Host "LocalFlow runtime API started. Tauri app is not built yet: $tauriExe"
}
