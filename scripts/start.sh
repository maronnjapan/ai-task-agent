#!/usr/bin/env bash
# Start the backend (serves the UI at http://127.0.0.1:8765 by default).
#   ./scripts/start.sh            run in the background (logs in <data dir>/logs)
#   ./scripts/start.sh --foreground
#   ./scripts/start.sh --open     also open the browser
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
require_uv

FOREGROUND=0
OPEN=""
for arg in "$@"; do
  case "$arg" in
    --foreground|-f) FOREGROUND=1 ;;
    --open) OPEN="--open" ;;
  esac
done

DATA_DIR="$(data_dir)"
mkdir -p "$DATA_DIR/logs"
PID_FILE="$DATA_DIR/aiwm.pid"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  log "Already running (pid $(cat "$PID_FILE")). UI: $(cd "$BACKEND_DIR" && uv run --quiet aiwm url 2>/dev/null || echo "http://127.0.0.1:$(app_port)")"
  exit 0
fi

cd "$BACKEND_DIR"
if [ "$FOREGROUND" = "1" ]; then
  exec uv run aiwm start $OPEN
fi
nohup uv run aiwm start --no-prompt $OPEN >> "$DATA_DIR/logs/start.log" 2>&1 &
sleep 2
if [ -f "$PID_FILE" ]; then
  log "Started (pid $(cat "$PID_FILE"))."
  log "UI (open this URL once; it carries the session token): $(uv run --quiet aiwm url 2>/dev/null || echo "http://127.0.0.1:$(app_port)")"
  if [ "$(detect_platform)" = "wsl" ]; then
    log "From Windows, use the same URL with localhost instead of 127.0.0.1 (WSL2 forwards localhost)."
  fi
else
  warn "Backend did not report a pid yet; check $DATA_DIR/logs/start.log"
fi
