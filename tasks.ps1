param(
    [Parameter(Position = 0)]
    [ValidateSet("Install", "Test", "InitDb", "StartServices", "Dev", "Build")]
    [string]$Task = "Test"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

switch ($Task) {
    "Install" {
        & (Join-Path $root "scripts\setup.ps1")
    }
    "Test" {
        & (Join-Path $root "scripts\test_pipeline.ps1")
    }
    "InitDb" {
        py -3 (Join-Path $root "scripts\init_db.py")
    }
    "StartServices" {
        & (Join-Path $root "scripts\start_services.ps1")
    }
    "Dev" {
        npm run tauri dev
    }
    "Build" {
        npm run tauri build
    }
}
