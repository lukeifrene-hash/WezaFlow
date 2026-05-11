param(
    [double]$Seconds = 3.0,
    [string]$Output = "artifacts/test.wav"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing virtual environment. Run scripts\setup.ps1 first."
}

Push-Location $RepoRoot
try {
    & $python -m services.runtime.audio_smoke --seconds $Seconds --output $Output
}
finally {
    Pop-Location
}
