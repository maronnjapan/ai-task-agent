#!/usr/bin/env bash
# Shared helpers for the shell scripts (macOS / WSL / Linux).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
ENV_FILE="${AIWM_ENV_FILE:-$PROJECT_ROOT/.env}"
export AIWM_ENV_FILE="$ENV_FILE"

log()  { printf '\033[1;34m[aiwm]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[aiwm]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[aiwm]\033[0m %s\n' "$*" >&2; exit 1; }

detect_platform() {
  case "$(uname -s)" in
    Darwin) echo macos ;;
    Linux)
      if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null || [ -n "${WSL_DISTRO_NAME:-}" ]; then echo wsl; else echo linux; fi ;;
    *) echo unknown ;;
  esac
}

data_dir() {
  if [ -n "${AIWM_DATA_DIR:-}" ]; then echo "$AIWM_DATA_DIR"; return; fi
  if [ -f "$ENV_FILE" ]; then
    local configured
    configured="$(grep -E '^AIWM_DATA_DIR=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"' || true)"
    if [ -n "$configured" ]; then eval echo "$configured"; return; fi
  fi
  echo "$HOME/.ai-work-manager"
}

app_port() {
  local port="${APP_PORT:-}"
  if [ -z "$port" ] && [ -f "$ENV_FILE" ]; then
    port="$(grep -E '^APP_PORT=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | tr -d '"' || true)"
  fi
  echo "${port:-8765}"
}

require_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then export PATH="$HOME/.local/bin:$PATH"; else
      die "uv is not installed. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
  fi
}
