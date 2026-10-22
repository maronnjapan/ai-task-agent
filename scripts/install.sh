#!/usr/bin/env bash
# Install Autonomous AI Work Manager on macOS / WSL / Linux.
#   ./scripts/install.sh            full install (backend + frontend build + setup)
#   ./scripts/install.sh --autostart  also register OS autostart
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PLATFORM="$(detect_platform)"
log "Platform: $PLATFORM"
log "Project : $PROJECT_ROOT"

# 1. uv (Python package manager)
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  log "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
require_uv

# 2. Python dependencies (uv downloads a compatible Python if needed)
log "Installing Python dependencies with uv..."
(cd "$BACKEND_DIR" && uv sync --frozen 2>/dev/null || uv sync)

# 3. Frontend build (Node.js 20+)
if command -v npm >/dev/null 2>&1; then
  log "Building the frontend..."
  (cd "$FRONTEND_DIR" && (npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund) && npm run build)
else
  warn "npm not found: the web UI will not be built. Install Node.js 20+ and run: cd frontend && npm install && npm run build"
fi

# 4. .env
if [ ! -f "$ENV_FILE" ]; then
  cp "$PROJECT_ROOT/.env.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE" || true
  if [ "$PLATFORM" != "macos" ]; then
    sed -i.bak 's/^SECRET_BACKEND=auto/SECRET_BACKEND=dotenv/' "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  fi
  log "Created $ENV_FILE"
fi

# 5. Data directory and database
mkdir -p "$(data_dir)"
(cd "$BACKEND_DIR" && uv run aiwm migrate)

# 6. API keys (Keychain on macOS, .env elsewhere)
if [ -t 0 ]; then
  (cd "$BACKEND_DIR" && uv run aiwm setup) || true
else
  warn "Non-interactive shell: run 'cd backend && uv run aiwm setup' to register API keys."
fi

# 7. Optional autostart
if [ "${1:-}" = "--autostart" ]; then
  (cd "$BACKEND_DIR" && uv run aiwm autostart install)
fi

log "Install complete. Start with: ./scripts/start.sh"
