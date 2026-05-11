#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$ROOT/artifacts/logs"
PID_FILE="$LOG_DIR/desktop-python-api.pid"
LOG_FILE="$LOG_DIR/desktop-python-api.log"

if [[ ! -x "$PYTHON" ]]; then
  echo "Missing .venv Python at $PYTHON. Run scripts/setup_macos.sh first." >&2
  exit 1
fi

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    sleep 1
  fi
fi

cd "$ROOT"
nohup "$PYTHON" -m services.runtime.api >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

APP="$ROOT/src-tauri/target/release/bundle/macos/WezaFlow.app"
if [[ -d "$APP" ]]; then
  open "$APP"
else
  echo "Runtime API started. Build or run the app with: npm run tauri -- dev"
fi
