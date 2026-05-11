$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$pip = Join-Path $venv "Scripts\pip.exe"

if (-not (Test-Path $python)) {
    py -3 -m venv $venv
}

& $python -m pip install --upgrade pip
& $pip install -r (Join-Path $root "requirements.txt")
& $pip install -r (Join-Path $root "services\asr\requirements.txt")
& $pip install -r (Join-Path $root "services\llm\requirements.txt")
& $pip install -r (Join-Path $root "services\context\requirements.txt")
& $pip install -r (Join-Path $root "services\injection\requirements.txt")
& $python (Join-Path $root "scripts\init_db.py")

if (Test-Path (Join-Path $root "package.json")) {
    Push-Location $root
    try {
        npm install
    }
    finally {
        Pop-Location
    }
}

if ((Test-Path (Join-Path $root "src-tauri\Cargo.toml")) -and (Get-Command cargo -ErrorAction SilentlyContinue)) {
    cargo build --manifest-path (Join-Path $root "src-tauri\Cargo.toml") --release
}
elseif (Test-Path (Join-Path $root "src-tauri\Cargo.toml")) {
    Write-Warning "Rust/Cargo is not installed. Install Rust before building the Tauri desktop shell."
}
