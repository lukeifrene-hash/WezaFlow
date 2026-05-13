#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="python3.12"
  else
    PYTHON_BIN="python3"
  fi
fi

"$PYTHON_BIN" -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip wheel
python -m pip install \
  -r requirements.txt \
  -r services/asr/requirements.txt \
  -r services/injection/requirements-macos.txt \
  -r services/llm/requirements.txt

npm ci

cat <<'MSG'
WezaFlow macOS setup complete.

Before the first recording, macOS may ask for:
- Microphone permission for the terminal or WezaFlow app.
- Accessibility permission so pyautogui can paste text into the active app.

For a dev run:
  npm run tauri -- dev

For a local release build:
  npm run tauri -- build
MSG
