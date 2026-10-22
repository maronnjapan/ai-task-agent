#!/usr/bin/env bash
# Stop a running backend.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DATA_DIR="$(data_dir)"
PID_FILE="$DATA_DIR/aiwm.pid"
if [ ! -f "$PID_FILE" ]; then
  log "Not running (no pid file at $PID_FILE)."
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for _ in $(seq 1 20); do
    if ! kill -0 "$PID" 2>/dev/null; then break; fi
    sleep 0.5
  done
  if kill -0 "$PID" 2>/dev/null; then
    warn "Process $PID did not exit; sending SIGKILL"
    kill -9 "$PID" || true
  fi
  log "Stopped (pid $PID)."
else
  log "Stale pid file; removing."
fi
rm -f "$PID_FILE" "$DATA_DIR/aiwm.lock"
