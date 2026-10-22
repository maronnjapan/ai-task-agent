#!/usr/bin/env bash
# Remove autostart entries, the virtual environment and (optionally) all data.
#   ./scripts/uninstall.sh          keep data directory
#   ./scripts/uninstall.sh --purge  also delete the data directory (tasks, artifacts, backups!)
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

"$SCRIPT_DIR/stop.sh" || true
if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
  require_uv
  (cd "$BACKEND_DIR" && uv run aiwm autostart remove) || true
fi
rm -rf "$BACKEND_DIR/.venv" "$FRONTEND_DIR/node_modules" "$FRONTEND_DIR/dist"
if [ "${1:-}" = "--purge" ]; then
  DATA_DIR="$(data_dir)"
  read -r -p "Delete ALL data in $DATA_DIR? [y/N] " answer
  if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
    rm -rf "$DATA_DIR"
    log "Removed $DATA_DIR"
  fi
fi
log "Uninstalled. The .env file was kept (contains your settings/API keys); delete it manually if desired."
