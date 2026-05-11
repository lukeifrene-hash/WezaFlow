param(
    [string]$Audio = "",
    [string]$Manifest = "",
    [string]$Config = "",
    [string]$Preset = "",
    [int]$Runs = 2,
    [string]$Output = "artifacts/benchmarks/asr_benchmark.jsonl",
    [switch]$NoWarmup
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing virtual environment. Run scripts\setup.ps1 first."
}

$argsList = @(
    "-m",
    "services.asr.benchmark",
    "--runs",
    $Runs,
    "--output",
    $Output
)

foreach ($audioPath in ($Audio -split ";")) {
    if ($audioPath -eq "") {
        continue
    }
    $argsList += @("--audio", $audioPath)
}

foreach ($manifestPath in ($Manifest -split ";")) {
    if ($manifestPath -eq "") {
        continue
    }
    $argsList += @("--manifest", $manifestPath)
}

foreach ($configSpec in ($Config -split ";")) {
    if ($configSpec -eq "") {
        continue
    }
    $argsList += @("--config", $configSpec)
}

foreach ($presetName in ($Preset -split ";")) {
    if ($presetName -eq "") {
        continue
    }
    $argsList += @("--preset", $presetName)
}

if ($NoWarmup) {
    $argsList += "--no-warmup"
}

Push-Location $RepoRoot
try {
    & $python @argsList
}
finally {
    Pop-Location
}
