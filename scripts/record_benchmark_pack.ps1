param(
    [string]$OutputDir = "artifacts/benchmark_pack",
    [switch]$List
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing virtual environment. Run scripts\setup.ps1 first."
}

$argsList = @(
    "-m",
    "services.runtime.benchmark_pack",
    "--output-dir",
    $OutputDir
)

if ($List) {
    $argsList += "--list"
}

Push-Location $RepoRoot
try {
    & $python @argsList
}
finally {
    Pop-Location
}
