param(
    [string]$Hotkey = "ctrl+alt+space",
    [string]$CommandHotkey = "ctrl+alt+e",
    [string]$CancelKey = "esc",
    [string]$Language = "en",
    [string]$Profile = "low-impact",
    [switch]$Check,
    [switch]$Quiet,
    [switch]$Diagnostics,
    [switch]$QualityFallback,
    [switch]$UseOllama
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Missing virtual environment. Run scripts\setup.ps1 first."
}

$argsList = @(
    "-m",
    "services.runtime.runner",
    "--hotkey",
    $Hotkey,
    "--command-hotkey",
    $CommandHotkey,
    "--cancel-key",
    $CancelKey
)

if ($Language -ne "") {
    $argsList += @("--language", $Language)
}

if ($Profile -ne "") {
    $argsList += @("--profile", $Profile)
}

if ($Check) {
    $argsList += "--check"
}

if ($Quiet) {
    $argsList += "--quiet"
}

if ($Diagnostics) {
    $argsList += "--diagnostics"
}

if ($QualityFallback) {
    $argsList += "--quality-fallback"
}

if ($UseOllama) {
    $argsList += "--use-ollama"
}

Push-Location $root
try {
    & $python @argsList
}
finally {
    Pop-Location
}
